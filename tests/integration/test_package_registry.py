import pytest
from naheng.packages.registry import ModelRegistry,content_hash
from naheng.packages.domain_check import reduction_condition
def test_package_identity_and_tampering(tmp_path):
    p=dict(package_id="p",chemistry_id="synthetic_two_site",parameter_revision="v1",dynamics_ast={},domain={},evidence_refs=[])
    r=ModelRegistry(tmp_path); r.register(p,content_hash(p))
    with pytest.raises(ValueError): r.register({**p,"parameter_revision":"v2"},content_hash(p))
    with pytest.raises(ValueError): r.register({**p,"chemistry_id":"lithium"})
def test_reduction_is_not_unconditionally_admitted():
    assert reduction_condition(None)["status"]=="UNKNOWN"
    assert reduction_condition([2,4])["status"]=="FAIL"
    assert reduction_condition([2,2])["status"]=="PASS"
