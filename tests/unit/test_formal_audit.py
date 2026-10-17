from naheng.formal.audit import audit_axioms
from naheng.formal.checker import check

TARGET='Naheng.Chemistry.element_rate_from_ports'

def test_axiom_parser_allowed_and_empty_dependencies():
    assert audit_axioms(f"'{TARGET}' depends on axioms: [propext, Classical.choice, Quot.sound]", [TARGET])['status'] == 'passed'
    assert audit_axioms(f"'{TARGET}' does not depend on any axioms", [TARGET])['status'] == 'passed'

def test_axiom_parser_rejects_transitive_sorry_custom_and_native():
    for forbidden in ['sorryAx', 'HiddenFalse', 'Lean.ofReduceBool']:
        output = f"'{TARGET}' depends on axioms: [propext, {forbidden}]"
        audit = audit_axioms(output, [TARGET])
        assert audit['status'] == 'failed'
        assert audit['rejected'][TARGET] == [forbidden]

def test_missing_target_and_duplicate_target_rejected():
    assert audit_axioms('', [TARGET])['missing'] == [TARGET]
    output=f"'{TARGET}' depends on axioms: []\n'{TARGET}' depends on axioms: []"
    assert audit_axioms(output, [TARGET])['status'] == 'failed'

def test_incomplete_core_cannot_pass(tmp_path,monkeypatch):
    # Synthetic control only: incomplete exports must never acquire authority.
    import json
    fixture_root=tmp_path/'incomplete-control'
    (fixture_root/'formal').mkdir(parents=True)
    (fixture_root/'formal/exports.json').write_text(json.dumps({'suites':{'core':{
        'implementation_status':'unimplemented','checked':False,'targets':[]}}}))
    monkeypatch.setattr('naheng.formal.checker.ROOT',fixture_root)
    result=check('core',tmp_path/'result')
    assert result['exit_code'] == 2
    assert result['status'] == 'blocked'
    assert result['checked'] is False
    assert not result['evidence']

def test_missing_lake_cannot_pass(tmp_path,monkeypatch):
    monkeypatch.setattr('naheng.formal.checker._lake',lambda:None)
    result=check('foundation',tmp_path)
    assert result['exit_code'] == 2
    assert result['checked'] is False
    assert result['status'] == 'blocked'


def test_audit_timeout_is_unknown_and_never_registers_partial_prints(tmp_path,monkeypatch):
    # Control-flow fixture only: no simulated compiler output is proof evidence.
    calls=[]
    def incomplete(command,cwd,log,timeout=120):
        calls.append(command)
        failed=len(calls)==3
        return {'command':command,'exit_code':2 if failed else 0,'timed_out':failed,
                'stdout':"Lean (version 4.19.0)" if len(calls)==1 else '',
                'stderr':'fixture audit interruption' if failed else ''}
    monkeypatch.setattr('naheng.formal.checker._lake',lambda:'fixture-only-lake')
    monkeypatch.setattr('naheng.formal.checker.run_command',incomplete)
    result=check('foundation',tmp_path)
    assert len(calls)==3 and result['exit_code']==2 and result['status']=='blocked'
    assert not result['checked'] and result['evidence']==[] and result['audit'] is None
