"""Server-selected exact-class execution inside the conditional lifecycle path.

The worker's imported execution source and live public proof root are distinct.
Missing/stale proof chooses the actual detailed backend. A grouped state is
never lifted to an invented detailed particle.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from collections.abc import Mapping
import re
import numpy as np

from naheng.models.site_model import SiteModel, IntegrationResult
from naheng.packages.registry import content_hash
from naheng.packages import current_class as cc
from naheng.packages import contracts as chemical_contracts
from naheng.lifecycle.capacity_protocol import CapacityProtocol, protocol_capacity

SELECTED_CORE='artifacts/formal/core-required-public-20261014-b/manifest.json'

def make_theory_selection(proof_root):
    """Trusted server configuration only; the API accepts no artifact path."""
    root=Path(proof_root).resolve();path=root/SELECTED_CORE
    proof=cc.read_declarations(path,proof_root=root)
    return {'schema_version':1,'manifest_relative':SELECTED_CORE,
        'manifest_sha256':cc.sha(path) if path.is_file() else None,
        'initial_status':proof['status'],'initial_checked_ids':proof['used_checked_ids'],
        'required_source_object_hashes':proof['bound_source_and_object_hashes'],
        'selection_scope':'Server-selected current proof bytes; missing/stale is detailed fallback'}

def _private_sources():
    paths=(Path(__file__).resolve(),Path(chemical_contracts.__file__).resolve())
    return {str(p):cc.sha(p) for p in paths}

_PROJECTION_ORIGIN=object()
_PROJECTION_DERIVED={'projection_sha256','source_snapshot_id','projected_snapshot_id'}
_PROJECTION_FIELDS={'snapshot_id','source_snapshot_sha256','parameter_revision','parameter_sha256','groups',
    'state_names','state_units','samples','weights','binding_sha256','posterior_scope','numeric_mapping_certificate','identity'}|_PROJECTION_DERIVED

def validate_projection_record(record,model,binding):
    """Check transfer integrity/shape only; a client hash is not authorization."""
    if type(record) is not dict or set(record)!=_PROJECTION_FIELDS:raise ValueError('Complete canonical producer projection required')
    record=json.loads(json.dumps(record,allow_nan=False))
    for name in ['source_snapshot_sha256','parameter_sha256','binding_sha256','projection_sha256']:
        if not isinstance(record[name],str) or not re.fullmatch(r'[0-9a-f]{64}',record[name]):raise ValueError('Malformed projection hash: '+name)
    payload={name:value for name,value in record.items() if name not in _PROJECTION_DERIVED}
    if cc.digest(payload)!=record['projection_sha256']:raise ValueError('Projection payload checksum mismatch')
    if (record['source_snapshot_id']!=record['snapshot_id'] or not isinstance(record['snapshot_id'],str) or not record['snapshot_id']
        or record['projected_snapshot_id']!='grouped-'+record['projection_sha256'][:24]):raise ValueError('Projection derived identity mismatch')
    bound=binding.record
    if (record['parameter_revision']!=bound['parameter_revision'] or record['parameter_sha256']!=cc.parameter_hash(model)
        or record['binding_sha256']!=bound['binding_sha256'] or record['groups']!=bound['groups']):raise ValueError('Projection source/model/binding mismatch')
    groups=tuple(tuple(g) for g in bound['groups']);m=len(groups)
    names,units=record['state_names'],record['state_units'];rows,weights=record['samples'],record['weights']
    expected=['q_class_'+str(i) for i in range(m)]+list(model.state_names[2:])
    if (type(names) is not list or type(units) is not list or len(names)!=len(units) or len(names)!=len(set(names))
        or names[:m+3]!=expected or units[:m+3]!=['mol']*m+list(model.state_units[2:])
        or set(names[m+3:])-{'rate_scale','side_rate_scale'} or units[m+3:]!=['1']*(len(names)-m-3)):
        raise ValueError('Projection state names/units mismatch')
    if type(rows) is not list or not rows or type(weights) is not list or len(rows)!=len(weights):raise ValueError('Projection samples/weights shape mismatch')
    if any(type(w) not in (int,float) or not math.isfinite(w) or w<0 for w in weights) or abs(math.fsum(weights)-1)>1e-6:
        raise ValueError('Projection weights must be finite, nonnegative and normalized')
    for row in rows:
        if type(row) is not list or len(row)!=len(names) or any(type(v) not in (int,float) or not math.isfinite(v) for v in row):raise ValueError('Projection sample shape or finite domain invalid')
        cc.lift_constraints(row,model,groups)
        if row[m]<0 or row[m+1]<0 or not model.params.temperature_min_K<=row[m+2]<=model.params.temperature_max_K:raise ValueError('Projection non-site state domain invalid')
        for name in names[m+3:]:
            value=row[names.index(name)]
            if (value<=0 if name=='rate_scale' else value<0):raise ValueError('Projection multiplicative uncertainty domain invalid')
    return record

@dataclass(frozen=True,init=False)
class Projection(Mapping):
    """Server-produced immutable transfer value; not measurement/host security."""
    _record_json:str
    _producer_projection_sha256:str
    _producer_snapshot_sha256:str
    _producer_binding_sha256:str
    _origin:object
    def __init__(self,*args,**kwargs):raise TypeError('Projection is created only from the server posterior at prepare')
    def to_record(self):return json.loads(self._record_json)
    def __getitem__(self,key):return self.to_record()[key]
    def __iter__(self):return iter(self.to_record())
    def __len__(self):return len(self.to_record())

def _freeze_projection(record,model,binding,snapshot):
    record=validate_projection_record(record,model,binding)
    if (record['source_snapshot_sha256']!=cc.digest(snapshot.model_dump(mode='json')) or record['snapshot_id']!=snapshot.snapshot_id
        or record['weights']!=list(snapshot.weights) or record['parameter_revision']!=snapshot.parameter_revision):raise ValueError('Projection does not originate in this permitted server posterior')
    groups=binding.record['groups'];names=snapshot.state_names;extras=[n for n in names if n not in model.state_names]
    expected=[]
    for source in snapshot.samples:
        state=[source[names.index(n)] for n in model.state_names]
        expected.append([math.fsum(model.params.site_capacity_mol[i]*state[i] for i in g) for g in groups]+state[2:]+[source[names.index(n)] for n in extras])
    if record['samples']!=expected or record['state_names'][len(groups)+3:]!=extras:raise ValueError('Projection samples differ from actual server posterior reduction')
    result=object.__new__(Projection)
    for name,value in {'_record_json':json.dumps(record,sort_keys=True,allow_nan=False),'_producer_projection_sha256':record['projection_sha256'],
        '_producer_snapshot_sha256':record['source_snapshot_sha256'],'_producer_binding_sha256':record['binding_sha256'],'_origin':_PROJECTION_ORIGIN}.items():object.__setattr__(result,name,value)
    return result

def lift_grouped_posterior(projected,model,binding):
    """Return a weighted union of correlated sets, never fabricated particles."""
    if type(projected) is not Projection or projected._origin is not _PROJECTION_ORIGIN:raise TypeError('Server-produced immutable Projection required; client records/hashes are not authority')
    record=validate_projection_record(projected.to_record(),model,binding)
    if (record['projection_sha256']!=projected._producer_projection_sha256 or record['source_snapshot_sha256']!=projected._producer_snapshot_sha256
        or record['binding_sha256']!=projected._producer_binding_sha256):raise ValueError('Projection producer identity changed')
    latest=cc.revalidate(binding,model,projected['parameter_revision'])
    if latest['status']=='FAIL':raise ValueError(latest['reason'])
    if projected['parameter_sha256']!=cc.parameter_hash(model) or projected['binding_sha256']!=binding.record['binding_sha256']:
        raise ValueError('Low/high transition cannot cross-bind parameters or projection')
    groups=tuple(tuple(g) for g in projected['groups']);m=len(groups)
    if [list(g) for g in groups]!=binding.record['groups']:raise ValueError('Low/high class partition mismatch')
    sets=[]
    for row,weight in zip(projected['samples'],projected['weights']):
        lifted=cc.lift_constraints(row,model,groups)
        lifted.update(weight=weight,preserved_non_site_state={name:row[i] for i,name in enumerate(projected['state_names']) if i>=m})
        sets.append(lifted)
    return {'representation':'weighted_union_of_correlated_linear_constraint_sets','sets':sets,
        'source_projected_snapshot_id':projected['projected_snapshot_id'],'source_projection_sha256':projected['projection_sha256'],
        'unique_detailed_snapshot':None,'reconstruction_scope':'All site compositions satisfying each class equality, not marginal interval products',
        'identity':latest,'numerical_set_certificate':'UNKNOWN'}

class LifecycleGroupedModel(cc.GroupedModel):
    """SiteModel-shaped grouped execution without a fictitious occupancy lift."""
    def __init__(self,model,groups):
        super().__init__(model,groups)
        self.state_names=tuple('q_class_'+str(i) for i in range(len(groups)))+tuple(model.state_names[2:])
        self.state_units=('mol',)*len(groups)+tuple(model.state_units[2:])
    def initial_state(self,soc=.6,temperature_K=298.15):
        return np.r_[self.capacity*soc,0.,self.params.reservoir_initial_mol,temperature_K]
    def inventory_mol(self,state):
        state=self._validate(state)
        return float(np.sum(state[:-1]))
    def integrate(self,state,current_A,duration_s,ambient_K=298.15,thermal_W=0.):
        initial=self._validate(state)
        value=super().integrate(initial,current_A,duration_s,ambient_K,thermal_W)
        final=np.asarray(value['state'])
        # The inherited solver reports a finite endpoint, not a certified path.
        return IntegrationResult(state=final,energy_J=value['energy_J'],events=value['events'],
            inventory_residual_mol=self.inventory_mol(final)-self.inventory_mol(initial),
            times_s=np.array([0.,value['elapsed_s']]),states=np.vstack((initial,final)),
            voltages_V=np.array([self.observe(initial,current_A)['voltage_V'],value['observable']['voltage_V']]),
            elapsed_s=value['elapsed_s'],thermal_management_energy_J=abs(thermal_W)*value['elapsed_s']/self.params.thermal_cop)
    def protocol_capacity(self,state,protocol):
        """Same declared initialization/stop classification in grouped amounts."""
        state=self._validate(state);m=len(self.groups);total=math.fsum(self.params.site_capacity_mol)
        active=max(0.,1-float(state[m])/total);inventory=self.inventory_mol(state)
        initial=state.copy();initial[:m]=self.capacity*protocol.initial_occupancy*active
        initial[m+1]=inventory-initial[m]-float(initial[:m].sum());initial[-1]=protocol.temperature_K
        if initial[m+1]<0:
            return {'status':'unknown','reason':'insufficient_inventory_for_protocol_initialization','capacity_C':None,'protocol_id':protocol.protocol_id}
        if active==0:
            return {'status':'unknown','reason':'zero_accessibility_without_voltage_cutoff_witness','capacity_C':None,
                'capacity_Ah':None,'delivered_charge_C':0.,'elapsed_s':0.,'protocol_id':protocol.protocol_id,
                'provenance_type':'synthetic','initialization_assumption':'trapped_accessibility_v1','uncalibrated':True}
        diagnostic=LifecycleGroupedModel(SiteModel(replace(self.params,voltage_min_V=protocol.cutoff_voltage_V)),self.groups)
        try:result=diagnostic.integrate(initial,protocol.discharge_current_A,protocol.maximum_duration_s,ambient_K=protocol.temperature_K)
        except (ValueError,RuntimeError) as error:
            return {'status':'unknown','reason':str(error),'capacity_C':None,'delivered_charge_C':None,'protocol_id':protocol.protocol_id}
        elapsed=float(result.elapsed_s);events=result.events
        if not math.isfinite(elapsed) or elapsed<0 or elapsed>protocol.maximum_duration_s+1e-6:
            return {'status':'unknown','reason':'invalid_protocol_elapsed_time','capacity_C':None,'delivered_charge_C':None,
                    'protocol_id':protocol.protocol_id,'events':events,'provenance_type':'synthetic'}
        delivered=protocol.discharge_current_A*elapsed
        cutoff=any(e['name']=='voltage_low' for e in events)
        competing=any(e['name']!='voltage_low' for e in events)
        status,reason=('unknown','competing_protocol_exit') if competing else ('computed','observed_numerical_voltage_cutoff') if cutoff else (
            'right_censored','maximum_duration_without_voltage_cutoff') if elapsed>=protocol.maximum_duration_s-1e-6 else ('unknown','incomplete_protocol_horizon')
        return {'status':status,'reason':reason,'capacity_C':delivered if status=='computed' else None,
            'capacity_lower_bound_C':delivered if status in {'computed','right_censored'} else None,
            'capacity_Ah':delivered/3600 if status=='computed' else None,'delivered_charge_C':delivered,
            'elapsed_s':elapsed,'events':events,'inventory_residual_mol':result.inventory_residual_mol,
            'protocol_id':protocol.protocol_id,'provenance_type':'synthetic','initialization_assumption':'trapped_accessibility_v1','uncalibrated':True,
            'derived_protocol_parameter_sha256':cc.parameter_hash(diagnostic.model)}

class ForecastExecution:
    """One immutable input selection; revalidate at particle/protocol/output use."""
    def __init__(self,model,snapshot,package,selection,*,proof_root):
        self.model=model;self.snapshot=snapshot;self.proof_root=Path(proof_root).resolve()
        self.selection=json.loads(json.dumps(selection)) if selection is not None else None
        if package['package_id']!=snapshot.model_package_id or package['parameter_revision']!=snapshot.parameter_revision:
            raise ValueError('Registered package/posterior identity mismatch')
        if package.get('parameter_hash')!=content_hash(asdict(model.params)):
            raise ValueError('Actual model cannot inherit a different registered parameter hash')
        self.package_hash=package['package_hash'];self.source_hashes=_private_sources()
        self.manifest=self.proof_root/SELECTED_CORE
        if self.selection is not None and self.selection.get('manifest_relative')!=SELECTED_CORE:
            raise ValueError('Unsupported server-selected proof identity')
        self.binding=cc.bind(model,snapshot.parameter_revision,self.manifest if self.selection is not None else None,
            model_package_id=snapshot.model_package_id,proof_root=self.proof_root)
        self.projected=None;self._calls=[];self._projection_identity=None
    def identity(self):
        identity=cc.revalidate(self.binding,self.model,self.snapshot.parameter_revision)
        if _private_sources()!=self.source_hashes:
            return {'status':'FAIL','reason':'Transition/contract implementation changed; binding stale','used_checked_ids':[]}
        if self.selection is None or self.selection.get('initial_status')!='PASS':
            return {'status':'UNKNOWN','reason':'No initially checked server selection','used_checked_ids':[]}
        expected=self.selection.get('manifest_sha256')
        if not self.manifest.is_file() or cc.sha(self.manifest)!=expected:
            return {'status':'UNKNOWN','reason':'Selected proof bytes changed after job input freeze','used_checked_ids':[]}
        proof=self.binding.record['proof']
        if proof['bound_source_and_object_hashes']!=self.selection.get('required_source_object_hashes'):
            return {'status':'UNKNOWN','reason':'Frozen source/object proof selection differs from worker read','used_checked_ids':[]}
        return identity
    def prepare(self,snapshot,query,model):
        if snapshot.model_dump()!=self.snapshot.model_dump() or cc.parameter_hash(model)!=cc.parameter_hash(self.model):
            raise ValueError('Execution context cannot cross-bind another posterior/model')
        if query.snapshot_id!=snapshot.snapshot_id:raise ValueError('Query snapshot mismatch')
        if query.future_policy_id!='fixed-current-v1':raise ValueError('Only the actual fixed-current lifecycle policy is implemented')
        if query.environment_id not in {'constant-ambient-v1','ambient-'+str(query.ambient_K)}:raise ValueError('Explicit constant ambient identity required')
        self.projected=_freeze_projection(cc.project_posterior(snapshot,model,self.binding),model,self.binding,snapshot)
        self._projection_identity=self.projected['identity']
        latest=self.identity()
        if latest['status']=='FAIL':raise ValueError(latest['reason'])
        if self._projection_identity['status']!='PASS':
            latest={'status':'UNKNOWN','reason':'Projection proof was not current; explicitly recreate context after evidence recovery','used_checked_ids':[]}
        return latest
    def particle(self,detailed,row):
        if self.projected is None:raise ValueError('Prepare exact input before selecting a particle')
        latest=self.identity()
        if latest['status']=='FAIL':raise ValueError(latest['reason'])
        if self._projection_identity['status']!='PASS':
            latest={'status':'UNKNOWN','reason':'Projection proof not current in this context','used_checked_ids':[]}
        groups=tuple(tuple(g) for g in self.binding.record['groups'])
        _,conditions=cc.coefficient_groups(detailed,groups)
        if any(c['status']=='FAIL' for c in conditions):raise ValueError('Sampled model violates shared-class conditions')
        names=self.snapshot.state_names;state=np.array([row[names.index(n)] for n in detailed.state_names])
        # Each sampled parameter vector is instantiated and bound independently;
        # uncertainty is not permission to reuse the base parameter receipt.
        particle_binding=cc.bind(detailed,self.snapshot.parameter_revision,self.manifest if latest['status']=='PASS' else None,
            proposed_groups=groups,model_package_id=self.snapshot.model_package_id,proof_root=self.proof_root)
        particle_identity=cc.revalidate(particle_binding,detailed,self.snapshot.parameter_revision)
        grouped=latest['status']=='PASS' and particle_identity['status']=='PASS' and len(groups)<2
        backend=LifecycleGroupedModel(detailed,groups) if grouped else detailed
        if grouped:state=np.r_[[math.fsum(detailed.params.site_capacity_mol[i]*state[i] for i in g) for g in groups],state[2:]]
        backend._p02_route='checked_grouped' if grouped else 'detailed_fallback'
        backend._p02_ids=latest['used_checked_ids'] if grouped else []
        backend._p02_binding=particle_binding
        self._calls.append({'kind':'particle_backend_selection','route':backend._p02_route,'used_checked_ids':backend._p02_ids,
                            'particle_parameter_sha256':cc.parameter_hash(detailed),'particle_binding_sha256':particle_binding.record['binding_sha256']})
        return backend,state,{'route':backend._p02_route,'used_checked_ids':backend._p02_ids,'condition_evaluation':latest,
            'binding_sha256':self.binding.record['binding_sha256'],'particle_parameter_sha256':cc.parameter_hash(detailed),
            'particle_binding_sha256':particle_binding.record['binding_sha256'],'particle_condition_evaluation':particle_identity}
    def _contracts(self):
        latest=self.identity()
        if latest['status']=='FAIL':raise ValueError(latest['reason'])
        proof=chemical_contracts.declarations(self.proof_root,self.manifest if latest['status']=='PASS' else None)
        return latest,proof
    def capacity(self,backend,state,protocol):
        latest,proof=self._contracts()
        # A selected grouped backend may not continue on proof withdrawal.
        if isinstance(backend,LifecycleGroupedModel) and latest['status']!='PASS':
            raise ValueError('Grouped proof withdrawn during execution; preserve set and explicitly restart detailed forecast')
        if isinstance(backend,LifecycleGroupedModel):
            particle_identity=cc.revalidate(backend._p02_binding,backend.model,self.snapshot.parameter_revision)
            if particle_identity['status']!='PASS':raise ValueError('Actual sampled parameter binding withdrawn before protocol')
        contract=chemical_contracts.accessibility_application(backend,state,protocol,proof)
        derived=SiteModel(replace(backend.params,voltage_min_V=protocol.cutoff_voltage_V))
        derived_binding=cc.bind(derived,self.snapshot.parameter_revision,self.manifest if latest['status']=='PASS' else None,
            model_package_id=self.snapshot.model_package_id,proof_root=self.proof_root)
        contract['derived_protocol_parameter_sha256']=cc.parameter_hash(derived)
        contract['derived_protocol_binding_sha256']=derived_binding.record['binding_sha256']
        contract['derived_protocol_condition_evaluation']=cc.revalidate(derived_binding,derived,self.snapshot.parameter_revision)
        if isinstance(backend,LifecycleGroupedModel) and contract['derived_protocol_condition_evaluation']['status']!='PASS':
            raise ValueError('Derived protocol parameter binding unavailable; grouped diagnostic withheld')
        value=backend.protocol_capacity(state,protocol) if isinstance(backend,LifecycleGroupedModel) else protocol_capacity(backend,state,protocol)
        value['theory_aging_contract']=contract
        self._calls.append({'kind':'actual_protocol_capacity','route':getattr(backend,'_p02_route','detailed_fallback'),
                            'status':value['status'],'used_checked_ids':contract['used_checked_ids']})
        return value
    def outputs(self,backend,state,current_A):
        latest,proof=self._contracts()
        grouped=isinstance(backend,LifecycleGroupedModel)
        if grouped and latest['status']!='PASS':raise ValueError('Grouped proof withdrawn before output publication')
        if grouped and cc.revalidate(backend._p02_binding,backend.model,self.snapshot.parameter_revision)['status']!='PASS':
            raise ValueError('Actual sampled parameter binding withdrawn before output')
        groups=backend.groups if grouped else ((0,),(1,))
        # Detailed fallback does not claim that reduction IDs were used.
        applicable=latest if grouped else {'status':'UNKNOWN','used_checked_ids':[]}
        output=chemical_contracts.output_application(backend,state,current_A,applicable,proof,groups)
        if grouped:
            lifted=cc.lift_constraints(state,backend.model,backend.groups)
            lifted['preserved_non_site_state']={name:float(state[i]) for i,name in enumerate(backend.state_names) if not name.startswith('q_class_')}
        else:lifted={'kind':'permitted_posterior_detailed_sample','unique_reconstruction_claim':False}
        self._calls.append({'kind':'actual_output_contract','used_checked_ids':output['used_checked_ids']})
        return {'theory_output_contract':output,'final_state_representation':lifted}
    def summary(self,paths):
        latest=self.identity()
        if latest['status']!='PASS' and any(p.get('theory_execution',{}).get('route')=='checked_grouped' for p in paths):
            raise ValueError('Proof withdrawn before grouped forecast publication; completed prediction withheld')
        return {'status':latest['status'],'current_identity':latest,'frozen_selection':self.selection,
            'binding_sha256':self.binding.record['binding_sha256'],'calls':self._calls,
            'executed_dimensions':[p.get('executed_state_dimension') for p in paths],
            'numerical_error':'UNKNOWN','strict_admission':'UNKNOWN','full_P02_gate_complete':False,
            'aging_scope':'Actual trapping accessibility protocol initialization; no film-to-SiteModel mapping asserted',
            'source_hashes':{**cc.source_hashes(),**self.source_hashes}}
