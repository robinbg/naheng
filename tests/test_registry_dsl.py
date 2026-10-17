from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import math
import pytest

from naheng.packages.registry import ModelRegistry,content_hash
from naheng.domain.expressions import ExpressionError

ROOT=Path(__file__).resolve().parents[1]

def builtin():return json.loads((ROOT/'model_packages/research_base/package.json').read_text(encoding='utf-8'))

def generic():
 return {'package_id':'typed-flux','chemistry_id':'synthetic_two_site','parameter_revision':'flux-v1','state_definition':{'amount_mol':'mol'},
 'dynamics_ast':{'kind':'expressions_v1','expressions':{'amount_mol':{'op':'var','value':'flux'}},'input_units':{},'parameters':{'flux':{'value':.002,'unit':'mol/s','source_id':'synthetic-flux-test'}},'derivative_units':{'amount_mol':'mol/s'}},
 'readout_ast':{'expressions':{'amount':{'op':'var','value':'amount_mol'}},'units':{'amount':'mol'}},'reduction_map':{},
 'domain':{'temperature_K':[273.15,333.15],'max_current_A':.3},'evidence_refs':[],'artifact_hashes':{}}

def test_builtin_is_executed_and_chemical_inventory_closes():
 r=ModelRegistry(ROOT);package=r.register(builtin())
 state={'x1':.37,'x2':.64,'trapped_mol':.001,'reservoir_mol':.02,'temperature_K':298.15}
 result=r.evaluate(package['package_id'],state,{'current_A':.1,'ambient_K':298.15},parameter_revision=package['parameter_revision'])
 d=result['dynamics']
 assert abs(.012*d['x1']+.008*d['x2']+d['trapped_mol']+d['reservoir_mol'])<1e-14
 assert result['reduction']['q']==pytest.approx(.012*.37+.008*.64)
 assert result['readouts']['current_A']==.1
 assert math.isfinite(result['readouts']['voltage_V'])
 assert result['evidence_validity']=='unverified'
 assert 'validation_status' not in package  # no unapproved public contract extension
 changed=r.evaluate(package['package_id'],state,{'current_A':-.1,'ambient_K':298.15},parameter_revision=package['parameter_revision'])
 assert changed['dynamics']['x1'] != d['x1']

@pytest.mark.parametrize('field,value',[('x1','mol'),('temperature_K','V')])
def test_builtin_state_units_are_not_silently_converted(field,value):
 p=builtin();p['state_definition'][field]=value
 with pytest.raises(ValueError,match='units mismatch'):ModelRegistry(ROOT).register(p)

def test_typed_ast_real_execution_and_parameter_revision():
 r=ModelRegistry(ROOT);p=r.register(generic())
 result=r.evaluate(p['package_id'],{'amount_mol':.1},{},parameter_revision='flux-v1')
 assert result['dynamics']=={'amount_mol':.002}
 assert result['readouts']=={'amount':.1}
 with pytest.raises(ValueError,match='revision is stale'):r.evaluate(p['package_id'],{'amount_mol':.1},{},parameter_revision='flux-v2')

@pytest.mark.parametrize('expression',[{'op':'add','args':[{'op':'var','value':'amount_mol'},{'op':'var','value':'flux'}]}, {'op':'exp','args':[{'op':'var','value':'amount_mol'}]}, {'op':'var','value':'hidden_truth'}, {'op':'call','value':'exec','args':[]}])
def test_unsafe_or_dimensionally_invalid_ast_rejected(expression):
 p=generic();p['dynamics_ast']['expressions']['amount_mol']=expression
 with pytest.raises((ValueError,ExpressionError)):ModelRegistry(ROOT).register(p)

def test_textual_mapping_cannot_execute_arbitrary_code():
 p=builtin();p['reduction_map']['q']="__import__('os').system('echo unsafe')"
 with pytest.raises(ExpressionError):ModelRegistry(ROOT).register(p)

def test_changed_parameter_or_expression_marks_previous_evidence_stale():
 for mutation in ('parameters','reduction_map'):
  r=ModelRegistry(ROOT);p=builtin();r.register(p);changed=deepcopy(p)
  if mutation=='parameters':changed['parameters']={'resistance_ohm':.1}
  else:changed['reduction_map']['q']='N1*x1'
  with pytest.raises(ValueError,match='invalidates evidence'):r.register(changed,content_hash(p))
  assert r.packages[p['package_id']]['evidence_validity']=='stale'

def test_bound_file_change_makes_execution_stale(tmp_path):
 path=tmp_path/'evidence.txt';path.write_text('initial',encoding='utf-8')
 import hashlib
 p=generic();p['artifact_hashes']={'evidence.txt':hashlib.sha256(path.read_bytes()).hexdigest()}
 r=ModelRegistry(tmp_path);r.register(p);path.write_text('changed',encoding='utf-8')
 with pytest.raises(ValueError,match='source changed'):r.evaluate(p['package_id'],{'amount_mol':.1},{},parameter_revision='flux-v1')
 assert r.packages[p['package_id']]['evidence_validity']=='stale'

def test_metadata_registration_never_grants_execution_or_domain_pass(tmp_path):
 p={'package_id':'metadata','chemistry_id':'synthetic_two_site','parameter_revision':'v1','dynamics_ast':{},'domain':{},'evidence_refs':[]}
 r=ModelRegistry(tmp_path);r.register(p)
 with pytest.raises(ValueError,match='not executable'):r.evaluate('metadata',{}, {},parameter_revision='v1')
 snapshot=SimpleNamespace(model_package_id='metadata',parameter_revision='v1')
 assert r.applicable('metadata',snapshot)['status']=='UNKNOWN'

def test_undeclared_hidden_input_and_nonfinite_state_are_rejected():
 r=ModelRegistry(ROOT);p=r.register(generic())
 with pytest.raises(ValueError,match='Undeclared inputs'):r.evaluate(p['package_id'],{'amount_mol':.1},{'truth_capacity':1},parameter_revision='flux-v1')
 with pytest.raises(ValueError,match='Finite real'):r.evaluate(p['package_id'],{'amount_mol':float('nan')},{},parameter_revision='flux-v1')


@pytest.mark.parametrize('parameters',[{'resistance_ohm':True},{'rate_s_inv':[.001,float('nan')]},{'base_voltage_V':float('inf')},{'model_kind':'public_data_case'}])
def test_parameter_types_and_synthetic_provenance_cannot_be_falsified(parameters):
    p=builtin();p['parameters']=parameters
    with pytest.raises(ValueError):ModelRegistry(ROOT).register(p)

def test_declared_state_temperature_domain_is_enforced_before_evaluation():
    r=ModelRegistry(ROOT);p=r.register(builtin())
    state={'x1':.5,'x2':.5,'trapped_mol':0,'reservoir_mol':.02,'temperature_K':500}
    with pytest.raises(ValueError,match='State temperature outside'):r.evaluate(p['package_id'],state,{'current_A':.1,'ambient_K':298.15},parameter_revision=p['parameter_revision'])
