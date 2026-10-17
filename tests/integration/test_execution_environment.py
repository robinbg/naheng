import pytest
from naheng.runtime.execution_environment import capture_environment,assert_environment_unchanged
from pathlib import Path

def test_missing_or_changed_core_lock_is_not_certified(tmp_path):
    actual=Path(__file__).resolve().parents[2]
    record=capture_environment(actual)
    assert record["lock_match"]
    assert_environment_unchanged(actual,record)
    changed={**record,"installed_packages":{**record["installed_packages"],"numpy":"wrong-version"}}
    with pytest.raises(RuntimeError,match="changed"):
        assert_environment_unchanged(actual,changed)
    (tmp_path/"uv.lock").write_text('version=1\n[[package]]\nname="numpy"\nversion="0.0"')
    with pytest.raises(RuntimeError,match="differ"):
        capture_environment(tmp_path)