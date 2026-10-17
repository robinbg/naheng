from copy import deepcopy
import pytest
from naheng.discovery.grammar import CandidateError,DOMAIN,expression,parse_candidate,parameter,total_rate_expr
from naheng.discovery.dataset import build_dataset,candidate_templates,instantiate

def candidate():return instantiate(candidate_templates()[0],build_dataset()['roles']['train'][0])

def test_typed_partition_and_nonempty_physical_witness_are_reproducible():
    a=parse_candidate(candidate());b=parse_candidate(deepcopy(candidate()))
    assert a.candidate_id==b.candidate_id and a.domain_witness
    assert a.features()['n_groups']<a.features()['n_sites']
    assert all(float(v)>0 for v in a.domain_witness['N'])

@pytest.mark.parametrize('bad',[{'op':'param','value':'qdot'},{'op':'param','value':'x'},
    {'op':'call','value':'__import__','args':[]},{'op':'div','args':[parameter('a'),parameter('b')]}])
def test_output_assumptions_code_calls_and_unguarded_division_are_invalid(bad):
    with pytest.raises(CandidateError):expression(bad)

def test_mixed_dimensions_cannot_be_added():
    with pytest.raises(CandidateError,match='SI dimensions'):
        expression({'op':'add','args':[parameter('N'),parameter('a')]})
    assert expression(total_rate_expr()).unit==(0,-1)

def test_copying_target_equality_into_assumptions_is_rejected():
    data=candidate();data['parameter_relations']=[{'kind':'output_equal','expression':parameter('a')}]
    with pytest.raises(CandidateError,match='Output/target'):parse_candidate(data)

def test_empty_or_singleton_state_domain_and_identity_partition_are_rejected():
    data=candidate();data['domain']='x=0.5'
    with pytest.raises(CandidateError,match='Full nonempty'):parse_candidate(data)
    data=candidate();data['groups']=list(range(data['n_sites']))
    with pytest.raises(CandidateError,match='nontrivial'):parse_candidate(data)

def test_incompatible_parameter_premises_require_nonempty_domain_witness():
    data=candidate();data['parameter_relations']=[{'kind':'positive','expression':parameter('a')},
        {'kind':'nonnegative','expression':{'op':'neg','args':[parameter('a')]}}]
    with pytest.raises(CandidateError,match='nonempty_domain_required'):parse_candidate(data)

def test_readout_units_and_expression_size_are_checked():
    data=candidate();data['target']={'kind':'linear_readout','weight_expression':parameter('N')}
    with pytest.raises(CandidateError,match='mol or mol/s'):parse_candidate(data)
    e=parameter('a')
    for _ in range(8):e={'op':'neg','args':[e]}
    with pytest.raises(CandidateError,match='excessive'):expression(e)

@pytest.mark.parametrize('field,value',[('schema_version',True),('target',{'kind':[]}),('groups',None)])
def test_malformed_types_are_rejected_without_runtime_crash(field,value):
    data=candidate();data[field]=value
    with pytest.raises(CandidateError):parse_candidate(data)
