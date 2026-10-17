import Naheng.Contracts.DerivedReadouts
import Naheng.Reduction.VariableTrajectory

/- Actual T1-to-y connection: the detailed sites and reduced class amounts
   share the same time-indexed source coefficients. The class damping and
   its primitive coefficient residual are independently certified over the
   whole horizon. c must be shared within each class. No total-q to per-site
   delta implication, final inventory error, or floating certificate is used. -/
namespace Naheng.Contracts
open Set Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false

variable {ι κ : Type*} [Fintype ι] [Fintype κ] [DecidableEq κ]

def classMask (N : ι → ℝ) (group : ι → κ) (k : κ) (i : ι) : ℝ :=
  if group i = k then N i else 0

theorem class_mask_amount (N x : ι → ℝ) (group : ι → κ) (k : κ) :
    totalAmount (classMask N group k) x = classAmount N group x k := by
  simp [totalAmount, classMask, classAmount, Finset.sum_filter, ite_mul]

theorem class_mask_source (N a : ι → ℝ) (group : ι → κ) (k : κ) :
    totalSource (classMask N group k) a = classSource N group a k := by
  simp [totalSource, classMask, classSource, Finset.sum_filter, ite_mul]

theorem damped_envelope_uniform_readout_budget (delta r epsilon t : ℝ)
    (hdelta : 0 ≤ delta) (hr : 0 < r) (hepsilon : 0 ≤ epsilon) (ht : 0 ≤ t) :
    dampedEnvelope delta r epsilon t ≤ delta + epsilon / r := by
  have hexp : Real.exp (-r * t) ≤ 1 := Real.exp_le_one_iff.mpr (by nlinarith)
  have hexp0 : 0 ≤ Real.exp (-r * t) := (Real.exp_pos _).le
  have hfirst := mul_le_mul_of_nonneg_left hexp hdelta
  have hsecond := mul_le_mul_of_nonneg_left (sub_le_self 1 hexp0) hepsilon
  have hdiv := div_le_div_of_nonneg_right hsecond hr.le
  simpa only [dampedEnvelope, mul_one] using add_le_add hfirst hdiv

theorem class_trajectory_error_from_site_reduction
    (N : ι → ℝ) (group : ι → κ) (x z a b c : ℝ → ι → ℝ)
    (r : ℝ → κ → ℝ) (rmin delta epsilon : κ → ℝ) (T : ℝ)
    (hT : 0 ≤ T) (hrmin : ∀ k, 0 < rmin k)
    (hdelta : ∀ k, 0 ≤ delta k) (hepsilon : ∀ k, 0 ≤ epsilon k)
    (hN : ∀ i, 0 ≤ N i) (hr : ∀ t ∈ Icc 0 T, ∀ k, rmin k ≤ r t k)
    (site_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => x s i) (siteDerivative (a t i) (b t i) (c t i) (x t i)) t)
    (reduced_solution : ∀ t ∈ Icc 0 T, ∀ k,
      HasDerivAt (fun s => classAmount N group (z s) k)
        (classSource N group (a t) k - r t k * classAmount N group (z t) k) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T, ∀ k,
      rateResidualBudget (classMask N group k) (a t) (b t) (c t) (r t k) ≤ epsilon k)
    (initial_error : ∀ k, |classAmount N group (x 0) k - classAmount N group (z 0) k| ≤ delta k) :
    ∀ t ∈ Icc 0 T, ∀ k,
      |classAmount N group (x t) k - classAmount N group (z t) k| ≤
        dampedEnvelope (delta k) (rmin k) (epsilon k) t := by
  intro t ht k
  have hmask : ∀ i, 0 ≤ classMask N group k i := by
    intro i
    dsimp [classMask]
    split_ifs
    · exact hN i
    · exact le_rfl
  have hred : ∀ s ∈ Icc 0 T,
      HasDerivAt (fun v => classAmount N group (z v) k)
        (totalSource (classMask N group k) (a s) -
          r s k * classAmount N group (z s) k) s := by
    intro s hs
    simpa only [class_mask_source] using reduced_solution s hs k
  have h := finite_site_variable_rate_trajectory_error_at
    (classMask N group k) x a b c (fun s => classAmount N group (z s) k)
    (fun s => r s k) (rmin k) (delta k) (epsilon k) T hT (hrmin k)
    (hdelta k) (hepsilon k) hmask (fun s hs => hr s hs k) site_solution hred
    hx0 hx1 (fun s hs => coefficient_budget s hs k)
    (by simpa only [class_mask_amount] using initial_error k)
  simpa only [class_mask_amount] using h t ht

theorem finite_site_group_trajectory_to_cumulative_trapping
    (N : ι → ℝ) (group : ι → κ) (x z a b c : ℝ → ι → ℝ)
    (r cClass : ℝ → κ → ℝ) (rmin delta epsilon cmax : κ → ℝ)
    (Y Z : ℝ → ℝ) (T e0 : ℝ)
    (hT : 0 ≤ T) (hrmin : ∀ k, 0 < rmin k)
    (hdelta : ∀ k, 0 ≤ delta k) (hepsilon : ∀ k, 0 ≤ epsilon k)
    (hN : ∀ i, 0 ≤ N i)
    (_ha : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ a t i)
    (_hb : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ b t i)
    (_hc : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ c t i)
    (hr : ∀ t ∈ Icc 0 T, ∀ k, rmin k ≤ r t k)
    (shared_c : ∀ t ∈ Icc 0 T, ∀ i, c t i = cClass t (group i))
    (coefficient_ceiling : ∀ t ∈ Icc 0 T, ∀ k, |cClass t k| ≤ cmax k)
    (site_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => x s i) (siteDerivative (a t i) (b t i) (c t i) (x t i)) t)
    (reduced_solution : ∀ t ∈ Icc 0 T, ∀ k,
      HasDerivAt (fun s => classAmount N group (z s) k)
        (classSource N group (a t) k - r t k * classAmount N group (z t) k) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (_hz_domain : ∀ t ∈ Icc 0 T, ∀ i, z t i ∈ Icc 0 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T, ∀ k,
      rateResidualBudget (classMask N group k) (a t) (b t) (c t) (r t k) ≤ epsilon k)
    (initial_state_error : ∀ k,
      |classAmount N group (x 0) k - classAmount N group (z 0) k| ≤ delta k)
    (actual_side_solution : ∀ t ∈ Icc 0 T,
      HasDerivAt Y (trappedRate N (c t) (x t)) t)
    (reduced_side_solution : ∀ t ∈ Icc 0 T,
      HasDerivAt Z (trappedRate N (c t) (z t)) t)
    (initial_inventory_error : |Y 0 - Z 0| ≤ e0) :
    ∀ t ∈ Icc 0 T, |Y t - Z t| ≤
      e0 + (∑ k, cmax k * (delta k + epsilon k / rmin k)) * t := by
  have hstate := class_trajectory_error_from_site_reduction N group x z a b c r
    rmin delta epsilon T hT hrmin hdelta hepsilon hN hr site_solution reduced_solution
    hx0 hx1 coefficient_budget initial_state_error
  have hwhole : ∀ t ∈ Icc 0 T, ∀ k,
      |classAmount N group (x t) k - classAmount N group (z t) k| ≤
        delta k + epsilon k / rmin k := by
    intro t ht k
    exact (hstate t ht k).trans
      (damped_envelope_uniform_readout_budget (delta k) (rmin k) (epsilon k) t
        (hdelta k) (hrmin k) (hepsilon k) ht.1)
  apply cumulative_trapping_error_from_class_amounts N group x z c cClass
    (fun _ k => delta k + epsilon k / rmin k) Y Z T e0
    (∑ k, cmax k * (delta k + epsilon k / rmin k)) shared_c hwhole _
    actual_side_solution reduced_side_solution initial_inventory_error
  intro t ht
  apply Finset.sum_le_sum
  intro k _
  exact mul_le_mul_of_nonneg_right (coefficient_ceiling t ht k)
    (add_nonneg (hdelta k) (div_nonneg (hepsilon k) (hrmin k).le))

end Naheng.Contracts

#print Naheng.Contracts.class_mask_amount
#print axioms Naheng.Contracts.class_mask_amount
#print Naheng.Contracts.class_mask_source
#print axioms Naheng.Contracts.class_mask_source
#print Naheng.Contracts.damped_envelope_uniform_readout_budget
#print axioms Naheng.Contracts.damped_envelope_uniform_readout_budget
#print Naheng.Contracts.class_trajectory_error_from_site_reduction
#print axioms Naheng.Contracts.class_trajectory_error_from_site_reduction
#print Naheng.Contracts.finite_site_group_trajectory_to_cumulative_trapping
#print axioms Naheng.Contracts.finite_site_group_trajectory_to_cumulative_trapping
