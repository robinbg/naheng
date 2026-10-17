"""Deterministic synthetic cash accounting and separate terminal comparison.

Inputs are existing executed EnergyLedger rows, explicit cash obligations and
owned asset endpoint evidence. Valuations are assumptions, never realized sales.
The caller verifies artifact/source provenance; no model, Run or registry changes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math


def _finite(value, name, *, nonnegative=False, optional=False):
    if optional and value is None: return
    if type(value) not in (int, float) or not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(name + ' requires finite nonboolean SI/money value')


def _name(value, name):
    if not isinstance(value, str) or not value.strip(): raise ValueError(name + ' requires explicit identity/source')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class FinancialAssumptions:
    source_ref: str
    terminal_rule_id: str
    scheduled_horizon_s: float
    stored_energy_value_CNY_per_kWh: float = .15
    replacement_cost_CNY_per_asset: float = 100.
    health_residual_fraction: float = .10
    rul_value_CNY_per_s: float = 0.
    unserved_value_CNY_per_s: float = 0.
    currency: str = 'CNY'
    provenance_type: str = 'synthetic'
    service_enabled: bool = False
    early_exit_rule: str = 'value_actual_endpoint_and_mark_unserved'

    def __post_init__(self):
        _name(self.source_ref, 'financial source'); _name(self.terminal_rule_id, 'terminal rule')
        for name in ('scheduled_horizon_s', 'stored_energy_value_CNY_per_kWh', 'replacement_cost_CNY_per_asset',
                     'health_residual_fraction', 'rul_value_CNY_per_s', 'unserved_value_CNY_per_s'):
            _finite(getattr(self, name), name, nonnegative=True)
        if self.health_residual_fraction > 1 or self.currency != 'CNY' or self.provenance_type != 'synthetic':
            raise ValueError('Explicit synthetic CNY residual fraction in [0,1] required')
        if type(self.service_enabled) is not bool or self.early_exit_rule != 'value_actual_endpoint_and_mark_unserved':
            raise ValueError('Explicit supported service/early-exit assumptions required')


@dataclass(frozen=True)
class AssetEndpoint:
    asset_id: str
    capacity_C: float | None
    pristine_capacity_C: float | None
    rul_s: float | None
    source_ref: str
    rul_status: str = 'unknown'

    def __post_init__(self):
        _name(self.asset_id, 'physical asset identity'); _name(self.source_ref, 'asset endpoint evidence')
        for name in ('capacity_C', 'pristine_capacity_C', 'rul_s'):
            _finite(getattr(self, name), name, nonnegative=True, optional=True)
        if self.pristine_capacity_C == 0: raise ValueError('Pristine capacity must be positive or unknown')
        if self.rul_status not in ('known', 'right_censored', 'unknown'):
            raise ValueError('RUL status must preserve censoring/unknown')
        if (self.rul_status == 'known') != (self.rul_s is not None):
            raise ValueError('Censored/unknown RUL is None, never zero/infinity or a window endpoint')


@dataclass(frozen=True)
class TerminalState:
    timestamp_s: float
    status: str
    soc: float | None
    stored_energy_J: float | None
    assets: tuple[AssetEndpoint, ...]
    source_ref: str
    evidence_kind: str = 'actual'

    def __post_init__(self):
        _finite(self.timestamp_s, 'terminal timestamp', nonnegative=True)
        _finite(self.soc, 'SOC', nonnegative=True, optional=True)
        _finite(self.stored_energy_J, 'stored energy J', nonnegative=True, optional=True)
        _name(self.source_ref, 'terminal evidence')
        if self.soc is not None and self.soc > 1: raise ValueError('SOC must be in [0,1] or unknown')
        if self.status not in ('initial', 'completed', 'early_exit', 'retired', 'right_censored', 'cancelled', 'failed', 'unknown'):
            raise ValueError('Explicit terminal/early-exit state required')
        if self.evidence_kind not in ('actual', 'conditional_projection'):
            raise ValueError('Actual or conditional-projection endpoint required')
        if type(self.assets) is not tuple or any(type(a) is not AssetEndpoint for a in self.assets):
            raise TypeError('Immutable typed asset endpoints required')
        if len({a.asset_id for a in self.assets}) != len(self.assets): raise ValueError('Duplicate physical endpoint asset')


@dataclass(frozen=True)
class CashEvent:
    event_id: str
    obligation_id: str
    asset_id: str
    component_id: str
    kind: str
    start_s: float
    end_s: float
    cost_CNY: float | None
    residual_credit_CNY: float | None
    source_ref: str
    classification: str = 'actual'
    introduced_asset_id: str | None = None

    def __post_init__(self):
        for name in ('event_id', 'obligation_id', 'asset_id', 'component_id', 'source_ref'): _name(getattr(self,name), name)
        for name in ('start_s', 'end_s'): _finite(getattr(self,name), name, nonnegative=True)
        for name in ('cost_CNY', 'residual_credit_CNY'): _finite(getattr(self,name), name, nonnegative=True, optional=True)
        if self.end_s < self.start_s or self.kind not in ('maintenance', 'replacement', 'retirement'):
            raise ValueError('Explicit cash kind and ordered actual/projected time interval required')
        if self.classification not in ('actual', 'projected'): raise ValueError('Cash event actual/projected classification required')
        if self.kind == 'replacement':
            _name(self.introduced_asset_id, 'replacement introduced physical identity')
            if self.introduced_asset_id == self.asset_id: raise ValueError('Replacement must have new physical asset identity')
        elif self.introduced_asset_id is not None: raise ValueError('Only replacement introduces a physical asset')
        if self.kind == 'maintenance' and self.residual_credit_CNY not in (0., None):
            raise ValueError('Maintenance cannot sell/residual-credit the same owned asset')


@dataclass(frozen=True)
class ServiceSettlement:
    settlement_id: str
    start_s: float
    end_s: float
    amount_CNY: float | None
    rule_ref: str | None = None
    eligibility_ref: str | None = None
    source_ref: str | None = None
    eligible: bool | None = None
    classification: str = 'actual'
    service_kind: str = 'demand_response'

    def __post_init__(self):
        _name(self.settlement_id, 'service settlement')
        for name in ('start_s','end_s'): _finite(getattr(self,name), name, nonnegative=True)
        _finite(self.amount_CNY,'service amount',nonnegative=True,optional=True)
        if self.end_s < self.start_s or self.classification not in ('actual','projected'):
            raise ValueError('Explicit service time/classification required')
        if self.eligible is not None and type(self.eligible) is not bool: raise ValueError('Service eligibility must be boolean or unknown')
        if self.service_kind not in ('demand_response','auxiliary'): raise ValueError('Explicit demand-response or auxiliary service required')


@dataclass(frozen=True)
class LifecycleFinanceResult:
    payload_json: str

    def to_dict(self): return json.loads(self.payload_json)
    @property
    def content_sha256(self): return hashlib.sha256(self.payload_json.encode()).hexdigest()


def financial_assumptions_from_config(config):
    """Read the explicit small synthetic config; never silently accept new rules."""
    if not isinstance(config,dict) or config.get('schema_version')!=1:
        raise ValueError('Explicit financial config schema1 required')
    units={'energy':'J','capacity':'C','time':'s','stored_energy_value':'CNY/kWh','cost':'CNY'}
    if config.get('units')!=units: raise ValueError('Financial configuration unit identity mismatch')
    names={item.name for item in fields(FinancialAssumptions)}
    if set(config)-names-{'schema_version','units','assumption_scope'}:
        raise ValueError('Unknown financial rule fields require a new explicit schema')
    _name(config.get('assumption_scope'),'synthetic assumption scope')
    return FinancialAssumptions(**{name:config[name] for name in names if name in config})


def _exposure_intervals(row, *, projected):
    """Derive time support, without inventing energy for individual cycles.

S04 aggregates each same phase across equal two-phase cycles. duration_s is its
total exposure, not a contiguous calendar duration. Supplied interval metadata
must equal the layout derived from the source's period/count/offset declaration.
"""
    periodic=row.get('aggregation')=='same_phase_across_cycles'
    if periodic:
        if not projected or row.get('execution_mode')!='cycle_map_jump':
            raise ValueError('Periodic aggregate exposure is a projected S04 cycle-map only')
        count=row.get('cycle_count'); cycle=row.get('cycle_start')
        if type(count) is not int or not 1<=count<=1000 or type(cycle) is not int or cycle<0:
            raise ValueError('Explicit positive periodic cycle count and source cycle index required')
        period=row.get('cycle_period_s'); offset=row.get('phase_offset_s')
        _finite(period,'cycle_period_s',nonnegative=True); _finite(offset,'phase_offset_s',nonnegative=True)
        if period<=0 or row.get('phase') not in ('discharge','charge'):
            raise ValueError('Supported S04 equal two-phase periodic layout required')
        width=period/2; expected_offset=0. if row['phase']=='discharge' else width
        if not math.isclose(offset,expected_offset,rel_tol=1e-12,abs_tol=1e-9):
            raise ValueError('Periodic phase offset differs from original two-phase layout')
        if not math.isclose(row['duration_s'],count*width,rel_tol=1e-12,abs_tol=1e-9):
            raise ValueError('Aggregate duration differs from source count and phase width')
        if row['start_s']-offset < -1e-9:
            raise ValueError('Periodic cycle anchor precedes common clock zero')
        derived=[(row['start_s']+index*period,row['start_s']+index*period+width) for index in range(count)]
    else:
        if any(name in row for name in ('aggregation','cycle_period_s','phase_offset_s')):
            raise ValueError('Unknown exposure aggregation metadata is not a contiguous execution')
        if row.get('execution_mode')=='exact_integration' and row.get('cycle_count')!=1:
            raise ValueError('Exact S04 phase must identify one genuine cycle')
        derived=[(row['start_s'],row['start_s']+row['duration_s'])] if row['executed'] and row['duration_s']>0 else []
    if 'exposure_intervals_s' in row:
        supplied=row['exposure_intervals_s']
        if not isinstance(supplied,(tuple,list)) or len(supplied)!=len(derived):
            raise ValueError('Exposure metadata does not equal derived source support')
        for interval,expected in zip(supplied,derived):
            if not isinstance(interval,(tuple,list)) or len(interval)!=2:
                raise ValueError('Explicit ordered exposure endpoints required')
            for value in interval:_finite(value,'exposure endpoint',nonnegative=True)
            if any(not math.isclose(value,target,rel_tol=1e-12,abs_tol=1e-9) for value,target in zip(interval,expected)):
                raise ValueError('Exposure metadata differs from source periodic layout')
    return derived


def _overlap(left,right):
    return max(left[0],right[0])<min(left[1],right[1])-1e-9


def _energy_rows(entries, run_id, initial, final, *, projected=False):
    validated=[]; ids=set(); intervals=[]
    for raw in entries:
        if not isinstance(raw,dict): raise TypeError('Existing EnergyLedger entry dictionaries required')
        row=json.loads(json.dumps(raw,allow_nan=False))
        for name in ('execution_id','action_id','snapshot_id','tariff_source'): _name(row.get(name),name)
        if row['execution_id'] in ids: raise ValueError('Duplicate execution: '+row['execution_id'])
        ids.add(row['execution_id'])
        if row.get('run_id') != run_id or row.get('currency') != 'CNY' or row.get('provenance_type') != 'synthetic':
            raise ValueError('Run/currency/synthetic energy entry identity mismatch')
        if type(row.get('executed')) is not bool or (not row['executed'] and (row.get('energy_J') != 0 or row.get('thermal_electric_energy_J') != 0)):
            raise ValueError('Unexecuted proposal cannot earn/cost actual energy')
        if not projected and row.get('classification','actual') != 'actual':
            raise ValueError('Projected ledger cannot enter realized energy cash')
        if projected and row.get('classification') != 'projected': raise ValueError('Explicit projected energy row label required')
        for name in ('energy_J','thermal_electric_energy_J','buy_price_per_kWh','sell_price_per_kWh','start_s','duration_s'):
            _finite(row.get(name),name,nonnegative=name!='energy_J')
        exposures=_exposure_intervals(row,projected=projected)
        if row['start_s'] < initial.timestamp_s-1e-9 or row['start_s'] > final.timestamp_s+1e-9 or any(a<initial.timestamp_s-1e-9 or b>final.timestamp_s+1e-9 for a,b in exposures):
            raise ValueError('Energy entry outside endpoint time interval')
        if row['executed']:
            if any(_overlap(exposure,old) for exposure in exposures for old in intervals):
                raise ValueError('Overlapping actual/projection execution intervals')
            intervals.extend(exposures)
        row['exposure_intervals_s']=[list(interval) for interval in exposures]
        row['duration_semantics']='aggregate_disjoint_phase_exposure' if row.get('aggregation')=='same_phase_across_cycles' else 'actual_contiguous_interval_or_unexecuted_proposal'
        row['last_exposure_end_s']=exposures[-1][1] if exposures else row['start_s']
        expected={'exported_energy_J':max(row['energy_J'],0.),'imported_energy_J':max(-row['energy_J'],0.)}
        expected['sales']=expected['exported_energy_J']/3600000*row['sell_price_per_kWh']
        expected['purchases']=expected['imported_energy_J']/3600000*row['buy_price_per_kWh']
        expected['thermal_cost']=row['thermal_electric_energy_J']/3600000*row['buy_price_per_kWh']
        expected['net_cashflow']=expected['sales']-expected['purchases']-expected['thermal_cost']
        for name,value in expected.items():
            _finite(row.get(name),name)
            if not math.isclose(row[name],value,rel_tol=1e-12,abs_tol=1e-12): raise ValueError('Existing energy cash arithmetic mismatch: '+name)
        validated.append(row)
    return validated


def _endpoint_value(endpoint, assumptions, reasons):
    health=[]; rul=[]
    for asset in endpoint.assets:
        soh=None if asset.capacity_C is None or asset.pristine_capacity_C is None else asset.capacity_C/asset.pristine_capacity_C
        health.append(None if soh is None else assumptions.replacement_cost_CNY_per_asset*assumptions.health_residual_fraction*soh)
        rul.append(None if asset.rul_s is None and assumptions.rul_value_CNY_per_s else assumptions.rul_value_CNY_per_s*(asset.rul_s or 0.))
        if soh is None: reasons.append('unknown_capacity_or_pristine:'+asset.asset_id)
        if assumptions.rul_value_CNY_per_s and asset.rul_s is None: reasons.append('unknown_or_censored_RUL:'+asset.asset_id)
    energy=None if endpoint.stored_energy_J is None else endpoint.stored_energy_J/3600000*assumptions.stored_energy_value_CNY_per_kWh
    if energy is None: reasons.append('unknown_stored_energy:'+endpoint.source_ref)
    values=[energy,*health,*rul]
    return None if any(v is None for v in values) else sum(values)


def settle_lifecycle(entries, *, run_id, initial, final, assumptions, cash_events=(),
                     projected_entries=(), services=(), planning_shadow_costs=()):
    """Return immutable realized cash, separate projections and terminal comparison.

Physical asset IDs distinguish generations. Disposal residual cash and ownership
at the terminal endpoint cannot both value the same sold/retired asset.
"""
    if type(initial) is not TerminalState or type(final) is not TerminalState or type(assumptions) is not FinancialAssumptions:
        raise TypeError('Typed immutable endpoints and financial assumptions required')
    _name(run_id,'RunID')
    cash_events=tuple(cash_events); services=tuple(services); planning_shadow_costs=tuple(planning_shadow_costs)
    if initial.evidence_kind!='actual' or initial.status!='initial' or final.timestamp_s<initial.timestamp_s:
        raise ValueError('Actual initial endpoint and ordered common time required')
    if final.timestamp_s-initial.timestamp_s>assumptions.scheduled_horizon_s+1e-9:
        raise ValueError('Terminal exceeds declared common scheduled horizon')
    if final.status=='completed' and not math.isclose(final.timestamp_s-initial.timestamp_s,assumptions.scheduled_horizon_s,abs_tol=1e-9):
        raise ValueError('Completed status cannot hide early exit/unserved scheduled time')
    actual=_energy_rows(entries,run_id,initial,final)
    projected=_energy_rows(projected_entries,run_id,initial,final,projected=True)
    if {r['execution_id'] for r in actual}&{r['execution_id'] for r in projected}:
        raise ValueError('Same execution counted in actual and projected cash')
    if any(_overlap(a,p) for row_a in actual for row_p in projected
           for a in row_a['exposure_intervals_s'] for p in row_p['exposure_intervals_s']):
        raise ValueError('Actual and projected intervals overlap and double count operation')
    if projected and final.evidence_kind!='conditional_projection':
        raise ValueError('Projected phases need a matching explicitly projected final endpoint')
    event_ids=set(); obligations=set(); prior_events=[]; introduced=set(); removed=set(); reasons=[]
    active={a.asset_id for a in initial.assets}; final_ids={a.asset_id for a in final.assets}
    buckets={'actual':[],'projected':[]}
    if any(type(event) is not CashEvent for event in cash_events): raise TypeError('Typed cash obligations required')
    for event in sorted(cash_events,key=lambda e:e.start_s):
        if event.event_id in event_ids or event.obligation_id in obligations: raise ValueError('Duplicate cash event/obligation')
        event_ids.add(event.event_id); obligations.add(event.obligation_id)
        if event.start_s<initial.timestamp_s or event.end_s>final.timestamp_s: raise ValueError('Cash event outside common endpoints')
        for old in prior_events:
            overlap=max(event.start_s,old.start_s)<min(event.end_s,old.end_s)
            same_point=event.start_s==event.end_s==old.start_s==old.end_s
            if (event.asset_id,event.component_id)==(old.asset_id,old.component_id) and (overlap or same_point):
                raise ValueError('Overlapping duplicate physical cash item')
        prior_events.append(event)
        if event.classification=='projected' and final.evidence_kind!='conditional_projection':
            raise ValueError('Projected obligation needs a matching projected endpoint')
        if event.asset_id not in active: raise ValueError('Cash obligation refers to absent/already disposed physical asset')
        if event.kind in ('replacement','retirement'):
            if event.asset_id in removed: raise ValueError('Same physical residual sold twice')
            if event.asset_id in final_ids: raise ValueError('Disposed residual and final asset valuation double count')
            removed.add(event.asset_id); active.remove(event.asset_id)
            if event.introduced_asset_id is not None:
                if event.introduced_asset_id in introduced or event.introduced_asset_id in active or event.introduced_asset_id in removed:
                    raise ValueError('Replacement physical identity repeated')
                introduced.add(event.introduced_asset_id); active.add(event.introduced_asset_id)
        net=None if event.cost_CNY is None or event.residual_credit_CNY is None else event.residual_credit_CNY-event.cost_CNY
        if net is None: reasons.append('unknown_cash_obligation:'+event.obligation_id)
        buckets[event.classification].append(net)
    if active!=final_ids: raise ValueError('Initial/replacement/disposal asset lineage does not equal final ownership')
    service_ids=set(); service_source_items=set(); service_rows=[]
    for service in services:
        if type(service) is not ServiceSettlement: raise TypeError('Typed service settlements required')
        if service.settlement_id in service_ids: raise ValueError('Duplicate service settlement')
        service_ids.add(service.settlement_id)
        item=(service.service_kind,service.source_ref,service.start_s,service.end_s)
        if service.source_ref and item in service_source_items: raise ValueError('Same source service settlement counted twice under an alias')
        service_source_items.add(item)
        if service.start_s<initial.timestamp_s or service.end_s>final.timestamp_s: raise ValueError('Service outside common time')
        eligible=assumptions.service_enabled and service.eligible is True and all(
            isinstance(v,str) and v.strip() for v in (service.rule_ref,service.eligibility_ref,service.source_ref)) and service.amount_CNY is not None
        if service.classification=='projected' and final.evidence_kind!='conditional_projection': raise ValueError('Projected service needs projected endpoint')
        booked=service.amount_CNY if eligible else 0.
        missing=assumptions.service_enabled and not eligible and service.eligible is not False
        if missing: reasons.append('service_income_withheld_UNKNOWN:'+service.settlement_id)
        buckets[service.classification].append(None if missing else booked)
        service_rows.append({**asdict(service),'booked_CNY':booked,'status':'booked' if eligible else 'disabled' if not assumptions.service_enabled else 'ineligible' if service.eligible is False else 'withheld_UNKNOWN'})
    for cost in planning_shadow_costs: _finite(cost,'planning shadow',nonnegative=True)
    known=lambda values:sum(v for v in values if v is not None)
    actual_energy=sum(r['net_cashflow'] for r in actual)
    projected_energy=sum(r['net_cashflow'] for r in projected)
    actual_cash=None if any(v is None for v in buckets['actual']) else actual_energy+known(buckets['actual'])
    projected_cash=None if any(v is None for v in buckets['projected']) else projected_energy+known(buckets['projected'])
    initial_value=_endpoint_value(initial,assumptions,reasons)
    final_value=_endpoint_value(final,assumptions,reasons)
    terminal_adjustment=None if initial_value is None or final_value is None else final_value-initial_value
    unserved=max(0.,assumptions.scheduled_horizon_s-(final.timestamp_s-initial.timestamp_s))
    conditional=None if actual_cash is None or projected_cash is None or terminal_adjustment is None else actual_cash+projected_cash+terminal_adjustment-unserved*assumptions.unserved_value_CNY_per_s
    endpoints=lambda ep:{**asdict(ep),'assets':[{**asdict(a),'soh':None if a.capacity_C is None or a.pristine_capacity_C is None else a.capacity_C/a.pristine_capacity_C} for a in ep.assets]}
    payload={'run_id':run_id,'currency':'CNY','assumptions':asdict(assumptions),'assumptions_sha256':_hash(asdict(assumptions)),
        'realized_operating_energy_cash_CNY':actual_energy,'known_realized_cash_CNY':actual_energy+known(buckets['actual']),
        'realized_cash_CNY':actual_cash,'projected_operating_cash_CNY':projected_energy,'projected_cash_CNY':projected_cash,
        'initial_valuation_CNY':initial_value,'final_valuation_CNY':final_value,'terminal_value_adjustment_CNY':terminal_adjustment,
        'conditional_comparison_value_CNY':conditional,'unserved_time_s':unserved,
        'conditional_unserved_value_CNY':unserved*assumptions.unserved_value_CNY_per_s,
        'initial':endpoints(initial),'final':endpoints(final),'actual_energy_entries':actual,'projected_energy_entries':projected,
        'cash_events':[asdict(e) for e in cash_events],'services':service_rows,
        'planning_shadow_costs_recorded_CNY':list(planning_shadow_costs),'planning_shadow_deducted_CNY':0.,
        'thermal_cost_already_in_energy_rows_not_deducted_again':True,'terminal_value_is_realized_income':False,
        'terminal_probe_energy_is_operating_sales':False,'unknown_reasons':sorted(set(reasons)),
        'scope':'Explicit synthetic accounting/conditional terminal assumptions; source authenticity and independent science remain caller responsibilities'}
    return LifecycleFinanceResult(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False))


def _validate_S04_cycle_layout(phases,result):
    """Check source cycle identities and periodic group/clock consistency."""
    indexed={}; groups={}
    for phase in phases:
        if not isinstance(phase,dict) or phase.get('execution_mode') not in ('exact_integration','cycle_map_jump'):
            raise ValueError('Unsupported or missing S04 source execution mode')
        required={'cycle','cycle_count','phase','policy_id','start_s','elapsed_s'}
        if phase['execution_mode']=='cycle_map_jump':
            required|={'aggregation','cycle_period_s','phase_offset_s'}
            if not required<=phase.keys():raise ValueError('Complete S04 periodic metadata required')
            if phase['aggregation']!='same_phase_across_cycles':raise ValueError('Supported S04 periodic aggregation required')
        elif not required<=phase.keys():raise ValueError('Complete S04 exact phase metadata required')
        count=phase.get('cycle_count'); cycle=phase.get('cycle')
        if type(count) is not int or count<1 or type(cycle) is not int or cycle<0:
            raise ValueError('S04 source cycle index/count invalid')
        row={'start_s':phase['start_s'],'duration_s':phase['elapsed_s'],'executed':True,
             'phase':phase['phase'],'cycle_count':count,'cycle_start':cycle,
             **{key:phase[key] for key in ('execution_mode','aggregation','cycle_period_s','phase_offset_s','exposure_intervals_s') if key in phase}}
        for key in ('start_s','duration_s'):_finite(row[key],key,nonnegative=True)
        exposures=_exposure_intervals(row,projected=phase['execution_mode']=='cycle_map_jump')
        for index,interval in enumerate(exposures):
            key=(cycle+index,phase['phase'])
            if key in indexed:raise ValueError('S04 source cycle phase repeated under changed metadata')
            indexed[key]=interval
        if phase['execution_mode']=='cycle_map_jump':
            key=(cycle,count,phase['policy_id'])
            groups.setdefault(key,[]).append(phase)
    for grouped in groups.values():
        if len(grouped)!=2 or {phase['phase'] for phase in grouped}!={'discharge','charge'}:
            raise ValueError('Incomplete source periodic phase pair')
        first,second=grouped
        if not math.isclose(first['cycle_period_s'],second['cycle_period_s'],abs_tol=1e-9) or not math.isclose(
                first['start_s']-first['phase_offset_s'],second['start_s']-second['phase_offset_s'],abs_tol=1e-9):
            raise ValueError('Source periodic pair uses inconsistent period/clock anchor')
    if 'completed_cycles' in result:
        completed=result['completed_cycles']
        if type(completed) is not int or completed<0:raise ValueError('S04 completed cycle count invalid')
        for cycle in range(completed):
            if (cycle,'discharge') not in indexed or (cycle,'charge') not in indexed:
                raise ValueError('S04 completed cycle omitted from financial exposure')
        if any(cycle>completed for cycle,_ in indexed):raise ValueError('S04 source cycle exceeds completion/partial tail')
    for cycle in {cycle for cycle,_ in indexed}:
        if (cycle,'discharge') in indexed and (cycle,'charge') in indexed:
            if not math.isclose(indexed[(cycle,'discharge')][1],indexed[(cycle,'charge')][0],abs_tol=1e-9):
                raise ValueError('S04 source discharge/charge cycle layout not contiguous')
    return indexed


def from_lifecycle_result(result, *, run_id, initial, final, assumptions, source_ref,
                          cash_events=(), services=(), planning_shadow_costs=()):
    """Adapt existing S04 public result without modifying its runner or ledgers.

Caller supplies evidence-bearing endpoints (including per-generation IDs); the
adapter faithfully keeps exact integrations apart from cycle-map projections.
"""
    _name(source_ref,'S04 source artifact')
    if not isinstance(result,dict) or result.get('provenance_type')!='synthetic': raise ValueError('Explicit synthetic S04 public result required')
    if not {'status','elapsed_s','phases','exact_phase_ledger','macro_projected_ledger','maintenance','economics'}<=result.keys():
        raise ValueError('Complete public S04 phase/accounting fields required')
    _finite(result['elapsed_s'],'S04 actual/projected elapsed_s',nonnegative=True)
    if not math.isclose(final.timestamp_s-initial.timestamp_s,result['elapsed_s'],abs_tol=1e-9):
        raise ValueError('S04 elapsed time differs from common endpoints')
    economics=result.get('economics',{})
    if economics.get('valuation_is_realized_revenue') is not False or economics.get('terminal_probe_energy_in_operating_sales') is not False:
        raise ValueError('S04 terminal probe/valuation must be excluded from realized sales')
    phases=result.get('phases',[]); indexed={}; actual=[]; projected=[]
    _validate_S04_cycle_layout(phases,result)
    if not math.isclose(sum(phase['elapsed_s'] for phase in phases),result['elapsed_s'],abs_tol=1e-9):
        raise ValueError('S04 full elapsed interval omitted from phase ledger')
    for phase in phases:
        key=(phase['cycle'],phase['cycle_count'],phase['phase'],phase['policy_id'])
        if key in indexed: raise ValueError('Duplicate S04 phase identity')
        indexed[key]=phase
    seen=set()
    for name,label,target in (('exact_phase_ledger','actual',actual),('macro_projected_ledger','projected',projected)):
        for row in result.get(name,[]):
            key=(row['cycle_start'],row['cycle_count'],row['phase'],row['policy_id'])
            if key in seen or key not in indexed: raise ValueError('S04 cash phase duplicate or no actual/projection source')
            seen.add(key); phase=indexed[key]
            if (phase['execution_mode']=='cycle_map_jump')!=(label=='projected'): raise ValueError('S04 exact/projected classification mismatch')
            if not math.isclose(row['energy_J'],phase['energy_J'],abs_tol=1e-12) or not math.isclose(row['thermal_electric_energy_J'],phase['thermal_electric_energy_J'],abs_tol=1e-12):
                raise ValueError('S04 energy ledger differs from underlying phase')
            accounting=economics.get('assumptions',{})
            for metadata_name in ('execution_mode','aggregation','cycle_period_s','phase_offset_s'):
                if metadata_name in row and row[metadata_name]!=phase.get(metadata_name):raise ValueError('Ledger periodic metadata differs from source phase')
            entry={**row,'run_id':run_id,'execution_id':source_ref+':phase:'+_hash(key),'action_id':source_ref+':phase:'+_hash(key),
                'snapshot_id':'S04-condition:'+source_ref,'start_s':phase['start_s'],'duration_s':phase['elapsed_s'],
                'executed':True,'classification':label,'tariff_source':row.get('source_id'),
                'buy_price_per_kWh':accounting.get('buy_price_per_kWh'),'sell_price_per_kWh':accounting.get('sell_price_per_kWh')}
            entry.update({key:phase[key] for key in ('execution_mode','aggregation','cycle_period_s','phase_offset_s','exposure_intervals_s') if key in phase})
            target.append(entry)
    if len(seen)!=len(indexed): raise ValueError('S04 phase omitted from financial denominator')
    maintenance=result.get('maintenance',[])
    for index,row in enumerate(maintenance):
        reference=source_ref+'#maintenance['+str(index)+']'
        matching=[event for event in cash_events if type(event) is CashEvent and event.source_ref==reference]
        if len(matching)!=1: raise ValueError('S04 maintenance needs exactly one explicit physical-generation cash mapping: '+reference)
        event=matching[0]
        if (event.kind!=row['kind'] or event.start_s!=row['time_s'] or event.end_s!=row['time_s']
                or event.cost_CNY!=row['replacement_cost'] or event.residual_credit_CNY!=row['salvage_value']):
            raise ValueError('S04 explicit cash mapping differs from original maintenance row')
    return settle_lifecycle(actual,run_id=run_id,initial=initial,final=final,assumptions=assumptions,
                            projected_entries=projected,cash_events=cash_events,services=services,
                            planning_shadow_costs=planning_shadow_costs)
