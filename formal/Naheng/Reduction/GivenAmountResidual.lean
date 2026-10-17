import Naheng.Reduction.Residual

/- Real finite-site residuals conditioned on stored amount, rather than the
   old full-capacity radius budget. The weighted mean is calculated from
   coefficients; no desired residual/error is assumed as a hypothesis. -/
namespace Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false
variable {ι : Type*} [Fintype ι]

def siteCapacityTotal (N : ι → ℝ) : ℝ := ∑ i, N i
noncomputable def capacityWeightedDecayMean (N a b c : ι → ℝ) : ℝ :=
  totalSource N (fun i => a i + b i + c i) / siteCapacityTotal N

theorem deviation_sum_bound_by_occupied_amount (N d x : ι → ℝ) (radius : ℝ)
    (hN : ∀ i, 0 ≤ N i) (hx : ∀ i, 0 ≤ x i)
    (deviation_radius : ∀ i, |d i| ≤ radius) :
    |∑ i, N i * d i * x i| ≤ radius * totalAmount N x := by
  calc
    |∑ i, N i * d i * x i| ≤ ∑ i, |N i * d i * x i| :=
      Finset.abs_sum_le_sum_abs _ _
    _ ≤ radius * totalAmount N x := by
      rw [totalAmount, Finset.mul_sum]
      apply Finset.sum_le_sum
      intro i _
      rw [abs_mul, abs_mul, abs_of_nonneg (hN i), abs_of_nonneg (hx i)]
      have h := mul_le_mul_of_nonneg_right (deviation_radius i) (mul_nonneg (hN i) (hx i))
      convert h using 1 <;> ring

theorem detailed_residual_bound_by_occupied_amount (N a b c x : ι → ℝ) (rbar radius : ℝ)
    (hN : ∀ i, 0 ≤ N i) (hx : ∀ i, 0 ≤ x i)
    (deviation_radius : ∀ i, |a i + b i + c i - rbar| ≤ radius) :
    |detailedAmountRate N a b c x - (totalSource N a - rbar * totalAmount N x)| ≤
      radius * totalAmount N x := by
  rw [detailed_rate_residual_identity, abs_neg]
  exact deviation_sum_bound_by_occupied_amount N _ x radius hN hx deviation_radius

theorem capacity_weighted_mean_centers_coefficients (N a b c : ι → ℝ)
    (positive_total : siteCapacityTotal N ≠ 0) :
    (∑ i, N i * (a i + b i + c i - capacityWeightedDecayMean N a b c)) = 0 := by
  calc
    (∑ i, N i * (a i + b i + c i - capacityWeightedDecayMean N a b c)) =
        totalSource N (fun i => a i + b i + c i) -
          capacityWeightedDecayMean N a b c * siteCapacityTotal N := by
      simp [mul_sub, Finset.sum_sub_distrib, totalSource, siteCapacityTotal,
        Finset.mul_sum, Finset.sum_mul, mul_comm]
    _ = 0 := by
      rw [capacityWeightedDecayMean, div_mul_cancel₀ _ positive_total, sub_self]

theorem centered_residual_is_unoccupied_deviation (N a b c x : ι → ℝ) (rbar : ℝ)
    (coefficient_centering : (∑ i, N i * (a i + b i + c i - rbar)) = 0) :
    detailedAmountRate N a b c x - (totalSource N a - rbar * totalAmount N x) =
      ∑ i, N i * (a i + b i + c i - rbar) * (1 - x i) := by
  rw [detailed_rate_residual_identity]
  have identity : (∑ i, N i * (a i + b i + c i - rbar) * (1 - x i)) =
      (∑ i, N i * (a i + b i + c i - rbar)) -
        (∑ i, N i * (a i + b i + c i - rbar) * x i) := by
    simp [mul_sub, Finset.sum_sub_distrib]
  rw [identity, coefficient_centering, zero_sub]

theorem detailed_residual_bound_by_unoccupied_amount (N a b c x : ι → ℝ) (rbar radius : ℝ)
    (hN : ∀ i, 0 ≤ N i) (hx : ∀ i, x i ≤ 1)
    (coefficient_centering : (∑ i, N i * (a i + b i + c i - rbar)) = 0)
    (deviation_radius : ∀ i, |a i + b i + c i - rbar| ≤ radius) :
    |detailedAmountRate N a b c x - (totalSource N a - rbar * totalAmount N x)| ≤
      radius * (siteCapacityTotal N - totalAmount N x) := by
  rw [centered_residual_is_unoccupied_deviation N a b c x rbar coefficient_centering]
  have h := deviation_sum_bound_by_occupied_amount N
    (fun i => a i + b i + c i - rbar) (fun i => 1 - x i) radius hN
    (fun i => sub_nonneg.mpr (hx i)) deviation_radius
  have identity : totalAmount N (fun i => 1 - x i) = siteCapacityTotal N - totalAmount N x := by
    simp [totalAmount, siteCapacityTotal, mul_sub, Finset.sum_sub_distrib]
  rw [identity] at h
  exact h

/- New conditioned budget for the coefficient mean used by the actual
   posterior rate implementation. Requires source-derived radius, physical
   occupation, and nonzero total capacity. Real exact arithmetic only. -/
theorem capacity_weighted_mean_given_amount_residual_bound (N a b c x : ι → ℝ) (radius : ℝ)
    (hN : ∀ i, 0 ≤ N i) (positive_total : siteCapacityTotal N ≠ 0)
    (hx0 : ∀ i, 0 ≤ x i) (hx1 : ∀ i, x i ≤ 1)
    (deviation_radius : ∀ i,
      |a i + b i + c i - capacityWeightedDecayMean N a b c| ≤ radius) :
    |detailedAmountRate N a b c x -
      (totalSource N a - capacityWeightedDecayMean N a b c * totalAmount N x)| ≤
      min (radius * totalAmount N x) (radius * (siteCapacityTotal N - totalAmount N x)) := by
  exact le_min
    (detailed_residual_bound_by_occupied_amount N a b c x _ radius hN hx0 deviation_radius)
    (detailed_residual_bound_by_unoccupied_amount N a b c x _ radius hN hx1
      (capacity_weighted_mean_centers_coefficients N a b c positive_total) deviation_radius)

/- The sharp physical rational witness has q=1/2 out of capacity2. It
   attains the new budget1/2; the earlier full-capacity budget is2. -/
noncomputable def amountResidualWitness : Fin 2 → ℝ := fun i => if i = 0 then 1/2 else 0
theorem given_amount_bound_tight_and_strictly_smaller_example :
    capacityWeightedDecayMean ceN ceA ceB ceC = 3 ∧
    (∀ i, 0 ≤ amountResidualWitness i ∧ amountResidualWitness i ≤ 1) ∧
    (∀ i, |ceA i + ceB i + ceC i - capacityWeightedDecayMean ceN ceA ceB ceC| ≤ 1) ∧
    |detailedAmountRate ceN ceA ceB ceC amountResidualWitness -
      (totalSource ceN ceA - 3 * totalAmount ceN amountResidualWitness)| = (1/2 : ℝ) ∧
    min (1 * totalAmount ceN amountResidualWitness)
      (1 * (siteCapacityTotal ceN - totalAmount ceN amountResidualWitness)) = (1/2 : ℝ) ∧
    rateResidualBudget ceN ceA ceB ceC 3 = 2 ∧ (1/2 : ℝ) < 2 := by
  norm_num [capacityWeightedDecayMean, siteCapacityTotal, totalAmount, totalSource,
    detailedAmountRate, siteDerivative, rateResidualBudget, amountResidualWitness,
    ceN, ceA, ceB, ceC, Fin.sum_univ_two]
  constructor
  · intro i
    by_cases h : i = 0 <;> norm_num [amountResidualWitness, h]
  · intro i
    by_cases h : i = 0 <;> norm_num [ceA, ceB, ceC, h]

end Naheng.Reduction
set_option pp.proofs false
#print Naheng.Reduction.deviation_sum_bound_by_occupied_amount
#print axioms Naheng.Reduction.deviation_sum_bound_by_occupied_amount
#print Naheng.Reduction.detailed_residual_bound_by_occupied_amount
#print axioms Naheng.Reduction.detailed_residual_bound_by_occupied_amount
#print Naheng.Reduction.capacity_weighted_mean_centers_coefficients
#print axioms Naheng.Reduction.capacity_weighted_mean_centers_coefficients
#print Naheng.Reduction.centered_residual_is_unoccupied_deviation
#print axioms Naheng.Reduction.centered_residual_is_unoccupied_deviation
#print Naheng.Reduction.detailed_residual_bound_by_unoccupied_amount
#print axioms Naheng.Reduction.detailed_residual_bound_by_unoccupied_amount
#print Naheng.Reduction.capacity_weighted_mean_given_amount_residual_bound
#print axioms Naheng.Reduction.capacity_weighted_mean_given_amount_residual_bound
#print Naheng.Reduction.given_amount_bound_tight_and_strictly_smaller_example
#print axioms Naheng.Reduction.given_amount_bound_tight_and_strictly_smaller_example
