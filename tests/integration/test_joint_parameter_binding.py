"""Actual registered descriptor binding, including the first real hash defect."""
from dataclasses import asdict
import json
from pathlib import Path
import pytest

from naheng.domain.contracts import PosteriorSnapshot
from naheng.estimation.calibration import GaussianNoise, content_hash
from naheng.estimation.joint_gaussian_observer import JointGaussianObserver
from naheng.runtime.forecast_jobs import _package_model

ROOT = Path(__file__).resolve().parents[2]


def inputs():
    raw = json.loads((ROOT / 'tests/fixtures/calibration_builtin/request_joint_gaussian.json').read_bytes())
    source = json.loads((ROOT / raw['training_source']['path']).read_bytes())
    snapshot = PosteriorSnapshot.model_validate(source['prior_snapshot'])
    model = _package_model(raw['model_package'], ROOT, snapshot)
    noise = GaussianNoise.model_validate_json(json.dumps(raw['noise']))
    return raw, snapshot, model, noise


def test_real_registered_descriptor_adopts_with_its_original_parameter_identity():
    raw, snapshot, model, noise = inputs()
    observer = JointGaussianObserver(snapshot, model, noise)
    assert observer.adoption_record['model_parameter_sha256'] == raw['model_package']['parameter_hash']
    assert observer.adoption_record['model_parameter_sha256'] == noise.binding.parameter_sha256
    assert observer.snapshot.model_dump() == snapshot.model_dump()


def test_compact_state_serializer_cannot_replace_registered_parameter_identity():
    _, snapshot, model, noise = inputs()
    compact = content_hash(asdict(model.params))
    assert compact != noise.binding.parameter_sha256
    incorrect = noise.model_copy(update={'binding': noise.binding.model_copy(update={'parameter_sha256': compact})})
    with pytest.raises(ValueError, match='physical parameter hash mismatch'):
        JointGaussianObserver(snapshot, model, incorrect)
