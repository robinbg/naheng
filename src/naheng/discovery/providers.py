"""Local typed proof/refinement provider. No external LLM credentials/calls."""
import copy
from .grammar import CandidateError,parse_candidate,total_rate_expr,parameter,canonical_sha

def required_shared_expressions(candidate):
    c=parse_candidate(candidate)
    if c.target_kind=='joint_rates':return [total_rate_expr(),parameter('c')]
    if c.target_kind=='stored_amount_rate':return [total_rate_expr()]
    if c.target_kind=='trapping_rate':return [parameter('c')]
    if c.target_kind=='linear_readout':return [c.weight.to_dict()]
    raise CandidateError('Unsupported proof target')

def refine_conditions(candidate,feedback):
    """Append physical parameter sharing; never output/occupation equality premises."""
    c=parse_candidate(candidate);raw=c.to_dict()
    existing={canonical_sha(r['expression']) for r in raw['parameter_relations'] if r['kind']=='within_group_equal'}
    added=[]
    for expr in required_shared_expressions(raw):
        if canonical_sha(expr) not in existing:
            relation={'kind':'within_group_equal','expression':expr};raw['parameter_relations'].append(relation);added.append(relation)
    refined=parse_candidate(raw)
    return {'candidate':refined.to_dict(),'added_parameter_relations':added,
        'trigger_status':feedback['status'],'witness_sha256':canonical_sha(feedback.get('witness')),
        'provider':'local_typed_parameter_refinement_not_LLM_or_learned_selector',
        'nonempty_domain_witness':refined.domain_witness,'unchanged':not added,
        'scope':'Conditional finite physical cube; model applicability independently checked'}

def lean_expression(expr,site='i'):
    if expr['op']=='param':return expr['value']+' '+site
    if expr['op']=='const':
        from fractions import Fraction
        value=Fraction(expr['value']);return f'(({value.numerator} : ℝ) / {value.denominator})'
    children=[lean_expression(x,site) for x in expr['args']]
    if expr['op']=='neg':return '(-'+children[0]+')'
    operators={'add':'+','sub':'-','mul':'*','div':'/'}
    return '('+children[0]+' '+operators[expr['op']]+' '+children[1]+')'

def emit_theorem(candidate,target):
    """Fixed trusted template compiler: unrestricted user Lean is not accepted."""
    import re
    if not re.fullmatch(r'Attempt_[0-9]{3}',target):raise CandidateError('Invalid generated declaration identity')
    c=parse_candidate(candidate);n=c.n_sites;k=len(set(c.groups))
    group=''.join(f'if i.val = {i} then {g} else ' for i,g in enumerate(c.groups[:-1]))+str(c.groups[-1])
    groupdef=f'def {target}_group (i : Fin {n}) : Fin {k} := {group}'
    hypotheses=[];shared={}
    for index,rel in enumerate(c.relations):
        expr=rel.expr.to_dict();name=f'h{index}';ei=lean_expression(expr,'i');ej=lean_expression(expr,'j')
        if rel.kind=='within_group_equal':
            hypotheses.append(f'({name} : ∀ i j, {target}_group i = {target}_group j → {ei} = {ej})')
            shared[canonical_sha(expr)]=name
        else:
            op='<' if rel.kind=='positive' else '≤'
            hypotheses.append(f'({name} : ∀ i, 0 {op} {ei})')
    header=f'theorem {target} (N a b c : Fin {n} → ℝ) (hN : ∀ i, 0 < N i)\n'+\
        '(ha : ∀ i, 0 ≤ a i) (hb : ∀ i, 0 ≤ b i) (hc : ∀ i, 0 ≤ c i)\n'+ '\n'.join(hypotheses)
    rs=shared.get(canonical_sha(total_rate_expr()));cs=shared.get(canonical_sha(parameter('c')))
    # Missing parameter conditions are deliberately attempted and produce actual Lean type errors.
    if c.target_kind=='joint_rates':
        conclusion=f'ClassRHSTrappingSufficient N {target}_group a b c'
        if rs and cs:
            body=f'  apply (class_rhs_trapping_sufficient_iff N hN {target}_group a b c).2\n  intro i j hg\n  exact ⟨by simpa only [add_assoc] using {rs} i j hg, {cs} i j hg⟩'
        else:body=f'  exact (class_rhs_trapping_sufficient_iff N hN {target}_group a b c).2'
    elif c.target_kind=='stored_amount_rate':
        conclusion=(f'∀ x z, PhysicalOccupation x → PhysicalOccupation z →\n'
            f'    (∀ k, classAmount N {target}_group x k = classAmount N {target}_group z k) →\n'
            '    detailedAmountRate N a b c x = detailedAmountRate N a b c z')
        body=(f'  have hr : ClassReadoutSufficient N {target}_group (fun i => a i + b i + c i) :=\n'
            f'    class_readout_sufficient_of_shared_coefficients N {target}_group (fun i => a i + b i + c i)'+
            (f' (by intro i j hg; simpa only [add_assoc] using {rs} i j hg)' if rs else '')+'\n'
            '  intro x z hx hz hq\n'
            '  rw [detailed_rate_is_source_minus_weighted_readout, detailed_rate_is_source_minus_weighted_readout]\n'
            '  rw [hr x z hx hz hq]')
    else:
        expr=parameter('c') if c.target_kind=='trapping_rate' else c.weight.to_dict();w=lean_expression(expr)
        name=shared.get(canonical_sha(expr));conclusion=f'ClassReadoutSufficient N {target}_group (fun i => {w})'
        body=f'  exact class_readout_sufficient_of_shared_coefficients N {target}_group (fun i => {w})'+(' '+name if name else '')
    return groupdef+'\n'+header+' :\n  '+conclusion+' := by\n'+body+'\n'

def external_provider(config):
    if config.get('enabled'):raise CandidateError('External LLM not configured/authorized in this package')
    return {'status':'disabled','actual_calls':0,'LLM_claim':False}
