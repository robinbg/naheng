"""Synthetic finance arithmetic; one genuine small S04 phase integration adapter."""
from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

if os.environ.get('NAHENG_FINANCE_CANDIDATE'):
    spec=importlib.util.spec_from_file_location('finance_candidate',os.environ['NAHENG_FINANCE_CANDIDATE'])
    F=importlib.util.module_from_spec(spec); sys.modules[spec.name]=F; spec.loader.exec_module(F)
else:
    from naheng.economics import lifecycle as F
from naheng.domain.contracts import Action
from naheng.economics.ledger import EnergyLedger


def asset(name='g0',capacity=100.,rul=None):
    return F.AssetEndpoint(name,capacity,100.,rul,'synthetic_math_endpoint',rul_status='known' if rul is not None else 'unknown')


def endpoints(final_assets=None, final_energy=3600000., final_t=10.,kind='actual'):
    return (F.TerminalState(0.,'initial',.6,3600000.,(asset(),),'synthetic_math_initial'),
            F.TerminalState(final_t,'completed',.6,final_energy,(asset(),) if final_assets is None else final_assets,'synthetic_math_final',kind))


def assumptions(**values):
    return F.FinancialAssumptions('explicit_synthetic_financial_fixture','fixed_terminal_rule',10.,**values)


def entry(energy=3600000.,thermal=0.,start=0.,duration=10.,execution='one',executed=True):
    action=Action(action_id='math-action-'+execution,snapshot_id='math-snapshot',start_s=start,duration_s=duration,current_A=.02)
    ledger=EnergyLedger('math-run',tariff_source='explicit_synthetic_tariffs')
    return ledger.append(action,execution_id=execution,energy_J=energy,thermal_energy_J=thermal,executed=executed,duration_s=duration)


def settle(rows,**kwargs):
    initial,final=endpoints()
    return F.settle_lifecycle(rows,run_id='math-run',initial=initial,final=final,assumptions=assumptions(),**kwargs).to_dict()


def test_thermal_ledger_cost_is_deducted_exactly_once_and_shadow_never_final_cash():
    result=settle([entry(thermal=3600000.)],planning_shadow_costs=(2.,3.))
    assert result['realized_cash_CNY']==pytest.approx(.15)
    assert result['conditional_comparison_value_CNY']==pytest.approx(.15)
    assert result['planning_shadow_deducted_CNY']==0
    assert result['planning_shadow_costs_recorded_CNY']==[2.,3.]
    assert result['thermal_cost_already_in_energy_rows_not_deducted_again']


def test_duplicate_execution_and_alias_overlapping_interval_are_rejected():
    original=entry()
    with pytest.raises(ValueError,match='Duplicate execution'): settle([original,original])
    alias={**original,'execution_id':'renamed'}
    with pytest.raises(ValueError,match='Overlapping'): settle([original,alias])


def test_projected_energy_never_becomes_realized_cash_or_duplicates_actual_interval():
    initial,final=endpoints(final_t=10.,kind='conditional_projection')
    actual=entry(energy=3600000.,duration=5.)
    projected={**entry(energy=7200000.,start=5.,duration=5.,execution='future'),'classification':'projected'}
    result=F.settle_lifecycle([actual],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),projected_entries=[projected]).to_dict()
    assert result['realized_cash_CNY']==pytest.approx(.30)
    assert result['projected_cash_CNY']==pytest.approx(.60)
    assert result['conditional_comparison_value_CNY']==pytest.approx(.90)
    bad={**projected,'start_s':0.}
    with pytest.raises(ValueError,match='intervals overlap'):
        F.settle_lifecycle([actual],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),projected_entries=[bad])
    with pytest.raises(ValueError,match='Projected ledger'): settle([projected])


def test_unexecuted_refusal_preserves_zero_cash_without_advancing_terminal_time():
    initial,final=endpoints(final_t=0.)
    final=replace(final,status='cancelled')
    result=F.settle_lifecycle([entry(energy=0.,executed=False)],run_id='math-run',initial=initial,final=final,assumptions=assumptions()).to_dict()
    assert result['realized_cash_CNY']==0 and result['unserved_time_s']==10


def test_health_residual_already_reflects_loss_so_shadow_is_not_deducted_again():
    initial,final=endpoints(final_assets=(asset(capacity=80.),))
    result=F.settle_lifecycle([entry()],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),planning_shadow_costs=(2.,)).to_dict()
    assert result['terminal_value_adjustment_CNY']==pytest.approx(-2.)
    assert result['conditional_comparison_value_CNY']==pytest.approx(-1.7)
    assert result['final']['assets'][0]['soh']==.8


def test_actual_maintenance_and_replacement_cash_use_physical_generation_once():
    initial,final=endpoints(final_assets=(asset('g1'),))
    replacement=F.CashEvent('r','replacement-bill','g0','replacement','replacement',5.,5.,100.,8.,'synthetic_bill',introduced_asset_id='g1')
    result=F.settle_lifecycle([entry()],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),cash_events=(replacement,)).to_dict()
    assert result['realized_cash_CNY']==pytest.approx(-91.7)
    assert result['terminal_value_adjustment_CNY']==pytest.approx(0.)
    with pytest.raises(ValueError,match='double count'): settle([],cash_events=(replacement,))


def test_duplicate_obligation_overlapping_item_and_repeat_disposal_refuse():
    bill=F.CashEvent('m1','bill1','g0','bearing','maintenance',2.,4.,1.,0.,'synthetic_bill')
    with pytest.raises(ValueError,match='obligation'): settle([],cash_events=(bill,replace(bill,event_id='m2')))
    with pytest.raises(ValueError,match='Overlapping'): settle([],cash_events=(bill,replace(bill,event_id='m2',obligation_id='bill2',start_s=3.,end_s=5.)))
    initial,final=endpoints(final_assets=(),final_energy=0.)
    disposal=F.CashEvent('d1','dispose1','g0','disposal','retirement',5.,5.,0.,8.,'synthetic_sale')
    with pytest.raises(ValueError,match='absent|disposed'):
        F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),cash_events=(disposal,replace(disposal,event_id='d2',obligation_id='dispose2',start_s=6.,end_s=6.)))


def test_service_disabled_ineligible_missing_rules_and_qualified_are_separate():
    initial,final=endpoints()
    service=F.ServiceSettlement('s',0.,10.,100.,eligible=True)
    disabled=settle([],services=(service,))
    assert disabled['realized_cash_CNY']==0 and disabled['services'][0]['status']=='disabled'
    enabled=assumptions(service_enabled=True)
    missing=F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=enabled,services=(service,)).to_dict()
    assert missing['realized_cash_CNY'] is None and missing['services'][0]['booked_CNY']==0
    ineligible=F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=enabled,services=(replace(service,eligible=False),)).to_dict()
    assert ineligible['realized_cash_CNY']==0 and ineligible['services'][0]['status']=='ineligible'
    allowed=replace(service,rule_ref='synthetic_rule',eligibility_ref='synthetic_qualification',source_ref='synthetic_actual_settlement')
    valid=F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=enabled,services=(allowed,)).to_dict()
    assert valid['realized_cash_CNY']==100 and valid['terminal_value_is_realized_income'] is False


def test_unknown_cash_obligation_is_none_while_known_energy_subtotal_is_preserved():
    maintenance=F.CashEvent('m','bill','g0','maintenance','maintenance',5.,5.,None,0.,'missing_amount_source')
    result=settle([entry()],cash_events=(maintenance,))
    assert result['realized_cash_CNY'] is None and result['known_realized_cash_CNY']==pytest.approx(.3)


def test_caller_inputs_and_frozen_result_cannot_be_mutated_through_serialization():
    rows=[entry()]; before=deepcopy(rows); initial,final=endpoints()
    result=F.settle_lifecycle(rows,run_id='math-run',initial=initial,final=final,assumptions=assumptions())
    digest=result.content_sha256; changed=result.to_dict(); changed['actual_energy_entries'][0]['net_cashflow']=999
    assert rows==before and result.content_sha256==digest
    assert result.to_dict()['realized_cash_CNY']==pytest.approx(.3)


def test_existing_S04_genuine_small_exact_phase_outputs_adapt_without_runner_edit():
    from naheng.models.site_model import SiteModel,SiteParameters
    from naheng.lifecycle.runner import _cycles,CyclePolicy,LifecycleEconomics
    model=SiteModel(SiteParameters(thermal_cop=1.5))
    actual=_cycles(model,model.initial_state(),1,CyclePolicy(discharge_A=.02,charge_A=-.02,phase_duration_s=.5,thermal_W=.1),298.15)
    accounting=LifecycleEconomics(); ledger=[]
    for phase in actual['phases']:
        e,thermal=phase['energy_J'],phase['thermal_electric_energy_J']
        row={'cycle_start':phase['cycle'],'cycle_count':phase['cycle_count'],'phase':phase['phase'],'policy_id':phase['policy_id'],
             'energy_J':e,'thermal_electric_energy_J':thermal,'exported_energy_J':max(e,0.),'imported_energy_J':max(-e,0.),
             'sales':max(e,0.)/3600000*.30,'purchases':max(-e,0.)/3600000*.15,'thermal_cost':thermal/3600000*.15,
             'currency':'CNY','provenance_type':'synthetic','source_id':accounting.source_id}
        row['net_cashflow']=row['sales']-row['purchases']-row['thermal_cost']; ledger.append(row)
    published={'status':actual['status'],'elapsed_s':actual['elapsed_s'],'provenance_type':'synthetic','phases':actual['phases'],
               'exact_phase_ledger':ledger,'macro_projected_ledger':[],'maintenance':[],
               'economics':{'assumptions':asdict(accounting),'valuation_is_realized_revenue':False,'terminal_probe_energy_in_operating_sales':False}}
    initial,final=endpoints(final_t=actual['elapsed_s'])
    exact_assumptions=replace(assumptions(),scheduled_horizon_s=actual['elapsed_s'])
    result=F.from_lifecycle_result(published,run_id='math-run',initial=initial,final=final,assumptions=exact_assumptions,source_ref='actual_synthetic_S04_phases_with_math_endpoint_fixture').to_dict()
    assert len(result['actual_energy_entries'])==2 and result['projected_cash_CNY']==0
    assert result['realized_cash_CNY']==pytest.approx(sum(row['net_cashflow'] for row in ledger))
    assert sum(row['thermal_electric_energy_J'] for row in result['actual_energy_entries'])==pytest.approx(.1*1./1.5)
    wrong=deepcopy(published); wrong['exact_phase_ledger'][0]['energy_J']+=1
    with pytest.raises(ValueError,match='differs'): F.from_lifecycle_result(wrong,run_id='math-run',initial=initial,final=final,assumptions=exact_assumptions,source_ref='bad_math_source')


def test_projected_replacement_cash_is_separate_and_unknown_amount_never_zero():
    initial,final=endpoints(final_assets=(asset('g1'),),kind='conditional_projection')
    event=F.CashEvent('p','projected-bill','g0','replacement','replacement',5.,5.,100.,8.,'synthetic_projection',classification='projected',introduced_asset_id='g1')
    result=F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),cash_events=(event,)).to_dict()
    assert result['realized_cash_CNY']==0 and result['projected_cash_CNY']==-92
    assert result['conditional_comparison_value_CNY']==-92
    missing=replace(event,cost_CNY=None)
    unknown=F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),cash_events=(missing,)).to_dict()
    assert unknown['projected_cash_CNY'] is None and unknown['conditional_comparison_value_CNY'] is None


def test_auxiliary_service_alias_does_not_create_two_actual_payments():
    initial,final=endpoints()
    event=F.ServiceSettlement('s',0.,10.,2.,'synthetic_aux_rule','explicit_qualification','actual_math_receipt#payment1',True,service_kind='auxiliary')
    with pytest.raises(ValueError,match='source service'):
        F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=assumptions(service_enabled=True),services=(event,replace(event,settlement_id='alias')))


def test_explicit_synthetic_configuration_units_and_unknown_rules_are_validated():
    config_path=Path(__file__).resolve().parents[2]/'configs/economics/synthetic_lifecycle.json'
    config=json.loads(config_path.read_bytes())
    actual=F.financial_assumptions_from_config(config)
    assert actual.service_enabled is False and actual.provenance_type=='synthetic'
    assert actual.stored_energy_value_CNY_per_kWh==.15
    bad=deepcopy(config); bad['units']['energy']='kWh'
    with pytest.raises(ValueError,match='unit'): F.financial_assumptions_from_config(bad)
    with pytest.raises(ValueError,match='Unknown'): F.financial_assumptions_from_config({**config,'guaranteed_fire_probability':0})


def test_S04_maintenance_adapter_requires_exact_generation_source_amount_and_time():
    from naheng.lifecycle.runner import LifecycleEconomics
    accounting=LifecycleEconomics()
    # Explicit synthetic parser/arithmetic fixture, not a claimed new ODE run.
    phase={'cycle':0,'cycle_count':1,'phase':'discharge','policy_id':'structure-only',
           'execution_mode':'exact_integration','start_s':0.,'elapsed_s':10.,'energy_J':0.,'thermal_electric_energy_J':0.}
    row={'cycle_start':0,'cycle_count':1,'phase':'discharge','policy_id':'structure-only','energy_J':0.,
         'thermal_electric_energy_J':0.,'exported_energy_J':0.,'imported_energy_J':0.,'sales':0.,'purchases':0.,
         'thermal_cost':0.,'net_cashflow':0.,'currency':'CNY','provenance_type':'synthetic','source_id':accounting.source_id}
    result={'status':'right_censored','elapsed_s':10.,'phases':[phase],'exact_phase_ledger':[row],
        'macro_projected_ledger':[],'provenance_type':'synthetic','maintenance':[{'cell_id':'cell-1','kind':'replacement',
        'time_s':5.,'replacement_cost':100.,'salvage_value':8.}],
        'economics':{'assumptions':asdict(accounting),'valuation_is_realized_revenue':False,'terminal_probe_energy_in_operating_sales':False}}
    initial,final=endpoints(final_assets=(asset('g1'),))
    event=F.CashEvent('r','receipt1','g0','replacement','replacement',5.,5.,100.,8.,
                      'synthetic_parser_fixture#maintenance[0]',introduced_asset_id='g1')
    args=dict(run_id='math-run',initial=initial,final=final,assumptions=assumptions(),source_ref='synthetic_parser_fixture')
    actual=F.from_lifecycle_result(result,**args,cash_events=(event,)).to_dict()
    assert actual['realized_cash_CNY']==-92 and actual['terminal_value_adjustment_CNY']==0
    with pytest.raises(ValueError,match='exactly one'): F.from_lifecycle_result(result,**args)
    with pytest.raises(ValueError,match='differs'): F.from_lifecycle_result(result,**args,cash_events=(replace(event,cost_CNY=101.),))


def test_retirement_residual_cash_and_removed_asset_initial_value_are_separate_once():
    initial,final=endpoints(final_assets=(),final_energy=0.)
    initial=replace(initial,stored_energy_J=0.)
    final=replace(final,status='retired')
    disposal=F.CashEvent('sale','sale-receipt','g0','disposal','retirement',10.,10.,0.,8.,'synthetic_actual_sale')
    result=F.settle_lifecycle([],run_id='math-run',initial=initial,final=final,assumptions=assumptions(),cash_events=(disposal,),planning_shadow_costs=(2.,)).to_dict()
    assert result['realized_cash_CNY']==8 and result['terminal_value_adjustment_CNY']==-10
    assert result['conditional_comparison_value_CNY']==-2 and result['planning_shadow_deducted_CNY']==0
