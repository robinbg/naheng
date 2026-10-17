import pytest
from naheng.formal.checker import _audit_target_batches

@pytest.mark.parametrize('count',[1,17,20,21,59,178])
def test_every_target_including_last_partial_batch_is_audited_exactly_once(count):
    targets=[f'Fixture.target_{i}' for i in range(count)]
    batches=_audit_target_batches(targets)
    assert [t for b in batches for t in b]==targets
    assert all(0<len(b)<=20 for b in batches)

@pytest.mark.parametrize('targets',[[],['Fixture.t','Fixture.t'],['Fixture.t\n#eval IO.println "bad"'],['not-qualified']])
def test_duplicates_or_code_in_target_names_never_enter_prover(targets):
    with pytest.raises(ValueError):_audit_target_batches(targets)
