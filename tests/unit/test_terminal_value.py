"""Original terminal fairness target plus full-denominator comparable frontiers."""
from dataclasses import replace
import importlib.util
import math
import os
import sys
import pytest


def load(variable,module_name,public_name):
    if os.environ.get(variable):
        spec=importlib.util.spec_from_file_location(module_name,os.environ[variable])
        module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); return module
    return importlib.import_module(public_name)


F=load('NAHENG_FINANCE_CANDIDATE','finance_terminal_candidate','naheng.economics.lifecycle')
P=load('NAHENG_PARETO_CANDIDATE','pareto_candidate','naheng.economics.pareto')
from naheng.domain.contracts import Action
from naheng.economics.ledger import EnergyLedger


def asset(capacity=100.,rul=None,status='unknown'):
    return F.AssetEndpoint('physical-g0',capacity,100.,rul,'synthetic_math_endpoint',status)


def endpoints(*,energy=3600000.,capacity=100.,rul=None,status='unknown',time=10.):
    return F.TerminalState(0.,'initial',.6,3600000.,(asset(),),'synthetic_math_initial'),F.TerminalState(time,'completed' if time==10. else 'early_exit',.3,energy,(asset(capacity,rul,status),),'synthetic_math_terminal')


def assumption(**values):
    return F.FinancialAssumptions('explicit_synthetic_values','common_terminal_v1',10.,**values)


def test_selling_initial_stored_energy_cannot_profit_without_common_terminal_adjustment():
    action=Action(action_id='math-draw',snapshot_id='math-snapshot',start_s=0.,duration_s=10.,current_A=.02)
    ledger=EnergyLedger('r',tariff_source='synthetic_fixture'); row=ledger.append(action,execution_id='actual-math',energy_J=1800000.)
    initial,final=endpoints(energy=1800000.)
    result=F.settle_lifecycle([row],run_id='r',initial=initial,final=final,assumptions=assumption(stored_energy_value_CNY_per_kWh=.30)).to_dict()
    assert result['realized_cash_CNY']==pytest.approx(.15)
    assert result['terminal_value_adjustment_CNY']==pytest.approx(-.15)
    assert result['conditional_comparison_value_CNY']==pytest.approx(0.)


@pytest.mark.parametrize('missing',['energy','capacity','rul'])
def test_missing_required_terminal_value_remains_none_with_known_operating_cash(missing):
    values={'energy':None} if missing=='energy' else {'capacity':None} if missing=='capacity' else {'rul':None,'status':'right_censored'}
    initial,final=endpoints(**values)
    result=F.settle_lifecycle([],run_id='r',initial=initial,final=final,
        assumptions=assumption(rul_value_CNY_per_s=1. if missing=='rul' else 0.)).to_dict()
    assert result['realized_cash_CNY']==0 and result['conditional_comparison_value_CNY'] is None
    assert result['unknown_reasons']
    assert result['final']['assets'][0]['rul_s'] is None


def test_disabled_RUL_value_preserves_censoring_instead_of_infinity_or_zero_RUL():
    initial,final=endpoints(status='right_censored')
    result=F.settle_lifecycle([],run_id='r',initial=initial,final=final,assumptions=assumption()).to_dict()
    assert result['conditional_comparison_value_CNY']==0
    assert result['final']['assets'][0]['rul_s'] is None and result['final']['assets'][0]['rul_status']=='right_censored'


def test_early_exit_uses_same_endpoint_rule_and_explicit_unserved_value_not_fake_duration():
    initial,final=endpoints(time=5.)
    result=F.settle_lifecycle([],run_id='r',initial=initial,final=final,assumptions=assumption(unserved_value_CNY_per_s=.01)).to_dict()
    assert result['final']['status']=='early_exit' and result['unserved_time_s']==5.
    assert result['realized_cash_CNY']==0 and result['conditional_comparison_value_CNY']==pytest.approx(-.05)


@pytest.mark.parametrize('value',[math.nan,math.inf,-math.inf,True])
def test_nonfinite_or_boolean_financial_assumptions_refuse(value):
    with pytest.raises(ValueError): assumption(stored_energy_value_CNY_per_kWh=value)


def context(ids=('a','b'),metric='independent_operating_upper_bound'):
    return P.ComparisonContext('1'*64,'physical_voltage_domain_exit','declared_synthetic_operating_distribution',.05,
        '2'*64,'3'*64,'4'*64,ids,10.,risk_metric=metric)


def outcome(policy,ctx,events=(False,False),values=(1.,1.),independent=False,statuses=('complete','complete')):
    return P.PolicyOutcome(policy,ctx,tuple(P.CaseOutcome(cid,status,value,event,'synthetic_math_case',independent)
        for cid,status,value,event in zip(ctx.registered_case_ids,statuses,values,events)))


def test_N0_or_nonindependent_unknown_risk_is_not_zero_or_probability_frontier():
    result=P.pareto_frontier([outcome('p',context())])
    row=result['records'][0]
    assert row['independent_operating_n']==0 and row['operating_probability_upper_bound'] is None
    assert row['frontier_risk_score'] is None and result['frontier_policy_ids']==[]
    empty=P.pareto_frontier([P.PolicyOutcome('empty',context(ids=()),())])
    assert empty['records'][0]['full_registered_n']==0
    assert empty['records'][0]['conservative_registered_case_fraction'] is None
    assert empty['frontier_policy_ids']==[]


def test_failed_case_denominator_cannot_be_dropped_or_unknown_cash_treated_as_zero():
    ctx=context(metric='conservative_registered_case_fraction')
    result=P.pareto_frontier([outcome('p',ctx,events=(False,None),values=(1.,None),statuses=('complete','failed'))])
    row=result['records'][0]
    assert row['full_registered_n']==2 and row['conservative_registered_case_fraction']==.5
    assert row['mean_conditional_comparison_value_CNY'] is None and result['frontier_policy_ids']==[]
    with pytest.raises(ValueError,match='denominator'):
        P.PolicyOutcome('dropped',ctx,(P.CaseOutcome('a','complete',1.,False,'synthetic_math_case'),))


@pytest.mark.parametrize('field,value',[('alpha',.10),('event_definition','operational_temperature_stop'),
    ('risk_scope','stress_not_operating'),('frozen_protocol_sha256','5'*64),('information_permissions_sha256','6'*64),
    ('terminal_rule_sha256','7'*64),('financial_assumptions_sha256','8'*64)])
def test_incomparable_protocol_risk_alpha_information_or_terminal_rules_refuse(field,value):
    ctx=context()
    with pytest.raises(ValueError,match='Different protocol'):
        P.pareto_frontier([outcome('a',ctx),outcome('b',replace(ctx,**{field:value}))])


def test_finite_registered_frontier_is_empirical_and_keeps_probability_unknown():
    ctx=context(metric='conservative_registered_case_fraction')
    result=P.pareto_frontier([outcome('low-risk',ctx,values=(1.,1.)),
        outcome('higher-value',ctx,events=(True,False),values=(2.,2.)),
        outcome('dominated',ctx,events=(True,False),values=(.5,.5))])
    assert result['frontier_policy_ids']==['higher-value','low-risk']
    assert result['risk_metric_is_operating_probability'] is False
    assert all(row['operating_probability_upper_bound'] is None for row in result['records'])


def test_independent_whole_trajectory_zero_event_bound_matches_analytic_formula():
    ids=tuple('case-'+str(i) for i in range(299)); ctx=context(ids=ids)
    cases=tuple(P.CaseOutcome(cid,'complete',1.,False,'synthetic_statistical_method_fixture',True) for cid in ids)
    result=P.pareto_frontier([P.PolicyOutcome('math-only-independent-flag-fixture',ctx,cases)])
    assert result['records'][0]['operating_probability_upper_bound']==pytest.approx(1-.05**(1/299),abs=1e-13)
    assert result['records'][0]['operating_probability_upper_bound']>0
