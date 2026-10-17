"""Narrow lifecycle controls; simulated reader loss is labelled, no proof build."""

# --- published-formal-evidence guard (see docs/adr/0027) ---------------------
# These tests verify that runtime behaviour is bound to *published* formal
# evidence: active pointers, the compiled objects they name, and the runtime
# refresh. That evidence is a build product and is not redistributed, so a fresh
# clone cannot verify a binding that has not been built yet. Skipping is visible
# and reasoned; present-but-inconsistent evidence still fails the assertion.
import pytest as _pytest_publication_guard
from naheng.formal.publication_availability import (  # noqa: E402
    SKIP_REASON as _PUBLICATION_SKIP_REASON,
    publication_evidence_available as _publication_evidence_available)

pytestmark = _pytest_publication_guard.mark.skipif(
    not _publication_evidence_available(), reason=_PUBLICATION_SKIP_REASON)
# ---------------------------------------------------------------------------

from pathlib import Path
from unittest.mock import patch
import json,sys
ROOT=Path(__file__).resolve().parents[2]
from naheng.packages import current_class as cc
from naheng.models.site_model import SiteModel

def test_initial_review_unavailable_stays_unknown(tmp_path):
    model=SiteModel();binding=cc.bind(model,'r',model_package_id='test',proof_root=tmp_path)
    assert binding.record['mapping_review_verified_at_bind'] is False
    actual=cc.revalidate(binding,model,'r')
    assert actual['status']=='UNKNOWN' and actual['used_checked_ids']==[]
    assert not (tmp_path/cc.MAPPING_REVIEW_RELATIVE).exists()

def test_verified_mapping_review_lost_is_fail_even_without_initial_core():
    model=SiteModel();binding=cc.bind(model,'r',model_package_id='test',proof_root=ROOT)
    assert binding.record['mapping_review_verified_at_bind'] is True
    assert binding.record['proof']['status']=='UNKNOWN'  # deliberately no selected theorem manifest
    with patch.object(cc,'reviewed_mapping_source',return_value=False):
        actual=cc.revalidate(binding,model,'r')
    assert actual['status']=='FAIL' and actual['used_checked_ids']==[]

def test_legacy_proof_pass_cannot_be_relabelled_unverified():
    model=SiteModel();binding=cc.bind(model,'r',ROOT/'artifacts/formal/core-required-public-20261014-b/manifest.json',model_package_id='test',proof_root=ROOT)
    assert binding.record['proof']['status']=='PASS'
    for flag in ('absent','false'):
        record=binding.record
        if flag=='absent':record.pop('mapping_review_verified_at_bind')
        else:record['mapping_review_verified_at_bind']=False
        legacy=cc.GroupBinding(json.dumps(record,sort_keys=True))
        with patch.object(cc,'reviewed_mapping_source',return_value=False):actual=cc.revalidate(legacy,model,'r')
        assert actual['status']=='FAIL' and actual['used_checked_ids']==[]

def test_parameter_change_does_not_become_unknown(tmp_path):
    model=SiteModel();binding=cc.bind(model,'r',model_package_id='test',proof_root=tmp_path)
    assert cc.revalidate(binding,model,'changed')['status']=='FAIL'

