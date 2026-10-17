import Naheng.Reduction.Exact
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Tactic.Linarith
set_option pp.proofs false

/- Published instantaneous residual slice. This is a pointwise real-arithmetic rate bound.
   It is not a trajectory, probabilistic, voltage or physical-cell certificate. -/
namespace Naheng.Reduction
open scoped BigOperators
variable {ι : Type*} [Fintype ι]

noncomputable def rateResidualBudget (N a b c : ι → ℝ) (rbar : ℝ) : ℝ :=
  ∑ i, N i * |a i + b i + c i - rbar|

theorem detailed_rate_residual_identity (N a b c x : ι → ℝ) (rbar : ℝ) :
    detailedAmountRate N a b c x - (totalSource N a - rbar * totalAmount N x) =
      -(∑ i, N i * (a i + b i + c i - rbar) * x i) := by
  have termwise : detailedAmountRate N a b c x =
      ∑ i, ((N i * a i - rbar * (N i * x i)) -
        N i * (a i + b i + c i - rbar) * x i) := by
    apply Finset.sum_congr rfl
    intro i _
    dsimp [siteDerivative]
    ring
  rw [termwise]
  simp only [totalSource, totalAmount, Finset.sum_sub_distrib, Finset.mul_sum]
  ring

#print detailed_rate_residual_identity
#print axioms detailed_rate_residual_identity

theorem rate_residual_budget_nonnegative (N a b c : ι → ℝ) (rbar : ℝ)
    (hN : ∀ i, 0 ≤ N i) : 0 ≤ rateResidualBudget N a b c rbar := by
  exact Finset.sum_nonneg (fun i _ => mul_nonneg (hN i) (abs_nonneg _))

#print rate_residual_budget_nonnegative
#print axioms rate_residual_budget_nonnegative

theorem detailed_rate_residual_abs_bound (N a b c x : ι → ℝ) (rbar : ℝ)
    (hN : ∀ i, 0 ≤ N i) (hx0 : ∀ i, 0 ≤ x i) (hx1 : ∀ i, x i ≤ 1) :
    |detailedAmountRate N a b c x - (totalSource N a - rbar * totalAmount N x)| ≤
      rateResidualBudget N a b c rbar := by
  rw [detailed_rate_residual_identity, abs_neg]
  calc
    |∑ i, N i * (a i + b i + c i - rbar) * x i| ≤
        ∑ i, |N i * (a i + b i + c i - rbar) * x i| := by
      exact Finset.abs_sum_le_sum_abs
        (fun i => N i * (a i + b i + c i - rbar) * x i) Finset.univ
    _ ≤ rateResidualBudget N a b c rbar := by
      apply Finset.sum_le_sum
      intro i _
      rw [abs_mul, abs_mul, abs_of_nonneg (hN i), abs_of_nonneg (hx0 i)]
      simpa only [mul_one] using
        (mul_le_mul_of_nonneg_left (hx1 i) (mul_nonneg (hN i) (abs_nonneg _)))

#print detailed_rate_residual_abs_bound
#print axioms detailed_rate_residual_abs_bound

/- The standard scalar margin lemma gains no chemistry authority by itself. -/
theorem margin_contract (g g_eff e : ℝ) (error : |g - g_eff| ≤ e)
    (margin : g_eff + e ≤ 0) : g ≤ 0 := by
  have difference : g - g_eff ≤ e := le_trans (le_abs_self _) error
  linarith

#print margin_contract
#print axioms margin_contract

/- This contract uses the particular residual budget derived above from the
   actual detailed site RHS, rather than assuming an arbitrary output bound. -/
theorem robust_rate_upper_bound (N a b c x : ι → ℝ) (rbar limit : ℝ)
    (hN : ∀ i, 0 ≤ N i) (hx0 : ∀ i, 0 ≤ x i) (hx1 : ∀ i, x i ≤ 1)
    (margin : totalSource N a - rbar * totalAmount N x +
      rateResidualBudget N a b c rbar ≤ limit) :
    detailedAmountRate N a b c x ≤ limit := by
  have error := detailed_rate_residual_abs_bound N a b c x rbar hN hx0 hx1
  have cancellation : (detailedAmountRate N a b c x - limit) -
      ((totalSource N a - rbar * totalAmount N x) - limit) =
      detailedAmountRate N a b c x - (totalSource N a - rbar * totalAmount N x) := by ring
  have shifted_error : |(detailedAmountRate N a b c x - limit) -
      ((totalSource N a - rbar * totalAmount N x) - limit)| ≤
      rateResidualBudget N a b c rbar := by
    rw [cancellation]
    exact error
  have shifted_margin : ((totalSource N a - rbar * totalAmount N x) - limit) +
      rateResidualBudget N a b c rbar ≤ 0 := by linarith
  have bound := margin_contract (detailedAmountRate N a b c x - limit)
    ((totalSource N a - rbar * totalAmount N x) - limit)
    (rateResidualBudget N a b c rbar) shifted_error shifted_margin
  linarith

#print robust_rate_upper_bound
#print axioms robust_rate_upper_bound

/- A supplied real per-site ODE solution supplies the aggregate derivative;
   no aggregate derivative or residual bound is an input hypothesis. -/
theorem robust_trajectory_rate_upper_bound (N : ι → ℝ) (x a b c : ℝ → ι → ℝ)
    (rbar : ℝ → ℝ) (t limit : ℝ) (solution : IsSiteTrajectory x a b c)
    (hN : ∀ i, 0 ≤ N i) (hx0 : ∀ i, 0 ≤ x t i) (hx1 : ∀ i, x t i ≤ 1)
    (margin : totalSource N (a t) - rbar t * totalAmount N (x t) +
      rateResidualBudget N (a t) (b t) (c t) (rbar t) ≤ limit) :
    ∃ qdot, HasDerivAt (fun s => totalAmount N (x s)) qdot t ∧ qdot ≤ limit := by
  refine ⟨detailedAmountRate N (a t) (b t) (c t) (x t), ?_, ?_⟩
  · simpa only [totalAmount, detailedAmountRate] using
      (HasDerivAt.sum (u := Finset.univ) (fun i _ => (solution t i).const_mul (N i)))
  · exact robust_rate_upper_bound N (a t) (b t) (c t) (x t) (rbar t) limit
      hN hx0 hx1 margin

#print robust_trajectory_rate_upper_bound
#print axioms robust_trajectory_rate_upper_bound

/- Synthetic exact rational witness. A nominal-only test passes an upper rate
   limit while the detailed RHS violates it; retaining the budget rejects it. -/
def residualWitnessX : Fin 2 → ℝ := fun _ => 1

theorem nominal_only_rate_false_pass :
    totalSource ceN ceA - 5 * totalAmount ceN residualWitnessX = -7 ∧
    detailedAmountRate ceN ceA ceB ceC residualWitnessX = -3 ∧
    rateResidualBudget ceN ceA ceB ceC 5 = 4 ∧
    totalSource ceN ceA - 5 * totalAmount ceN residualWitnessX ≤ -5 ∧
    ¬ detailedAmountRate ceN ceA ceB ceC residualWitnessX ≤ -5 ∧
    ¬ totalSource ceN ceA - 5 * totalAmount ceN residualWitnessX +
        rateResidualBudget ceN ceA ceB ceC 5 ≤ -5 := by
  norm_num [totalSource, totalAmount, detailedAmountRate, siteDerivative,
    rateResidualBudget, residualWitnessX, ceN, ceA, ceB, ceC, Fin.sum_univ_two]

#print nominal_only_rate_false_pass
#print axioms nominal_only_rate_false_pass

end Naheng.Reduction
