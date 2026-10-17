"""Control fixtures for exact, non-shrinking core audit composition."""
from copy import deepcopy
import pytest
from naheng.formal.checker import _audit_plan

def fixture():
    groups=('foundation','reduction','aging','contracts')
    entries={name:{'implementation_status':'implemented','targets':[
        f'Naheng.{name}.statement_{i}' for i in range(n)]}
        for name,n in zip(groups,(17,72,30,59))}
    targets=[t for name in groups for t in entries[name]['targets']]
    return targets,{'suites':entries}

def test_every_original_target_is_audited_once_in_its_native_module():
    targets,manifest=fixture(); plan=_audit_plan('core',targets,manifest)
    assert len(targets)==178 and len(plan)==10
    assert [t for batch in plan for t in batch['targets']]==targets
    assert all(0<len(batch['targets'])<=20 for batch in plan)
    assert [batch['module'] for batch in plan]==(['Naheng.Foundation']+
        ['Naheng.Reduction']*4+['Naheng.Aging']*2+['Naheng.Contracts']*3)

@pytest.mark.parametrize('mutation',['omit','reorder','extra','duplicate','unimplemented','missing_group'])
def test_incomplete_or_ambiguous_core_is_rejected(mutation):
    targets,manifest=fixture(); manifest=deepcopy(manifest)
    if mutation=='omit': targets=targets[:-1]
    if mutation=='reorder': targets=list(reversed(targets))
    if mutation=='extra': targets=targets+['Naheng.fake.extra']
    if mutation=='duplicate': manifest['suites']['aging']['targets'][0]=targets[0]
    if mutation=='unimplemented': manifest['suites']['reduction']['implementation_status']='unimplemented'
    if mutation=='missing_group': del manifest['suites']['contracts']
    with pytest.raises(ValueError): _audit_plan('core',targets,manifest)
