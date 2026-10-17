import Naheng.Reduction.Exact
import Mathlib.Analysis.Calculus.MeanValue
import Mathlib.Tactic.Linarith

/- Conditional real readout bridge. The two accumulated inventories obey
   their actual full-horizon port equations. Initial inventory error and
   shared, time-indexed coefficients are explicit. A total-q certificate is
   usable only when c is common, or after grouping sites by shared c. -/
namespace Naheng.Contracts
open Set Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false

variable {ι κ : Type*} [Fintype ι] [Fintype κ] [DecidableEq κ]

theorem class_trapping_flux_error_from_class_amounts
    (N c x z : ι → ℝ) (group : ι → κ) (cClass delta : κ → ℝ)
    (shared : ∀ i, c i = cClass (group i))
    (hdelta : ∀ k, |classAmount N group x k - classAmount N group z k| ≤ delta k) :
    |trappedRate N c x - trappedRate N c z| ≤ ∑ k, |cClass k| * delta k := by
  rw [class_shared_trapping_output N c x group cClass shared,
    class_shared_trapping_output N c z group cClass shared]
  have hid : (∑ k, cClass k * classAmount N group x k) -
      (∑ k, cClass k * classAmount N group z k) =
      ∑ k, cClass k * (classAmount N group x k - classAmount N group z k) := by
    simp only [mul_sub, Finset.sum_sub_distrib]
  rw [hid]
  calc
    |∑ k, cClass k * (classAmount N group x k - classAmount N group z k)| ≤
        ∑ k, |cClass k * (classAmount N group x k - classAmount N group z k)| :=
      Finset.abs_sum_le_sum_abs _ Finset.univ
    _ ≤ ∑ k, |cClass k| * delta k := by
      apply Finset.sum_le_sum
      intro k _
      rw [abs_mul]
      exact mul_le_mul_of_nonneg_left (hdelta k) (abs_nonneg _)

/- A supplied derivative difference is bounded throughout the interval.
   The terminal inventory error is proved by the mean-value increment bound,
   rather than assumed or obtained from endpoints alone. -/
theorem cumulative_scalar_error_from_derivative_bound
    (Y Z dY dZ : ℝ → ℝ) (T e0 B : ℝ)
    (hY : ∀ t ∈ Icc 0 T, HasDerivAt Y (dY t) t)
    (hZ : ∀ t ∈ Icc 0 T, HasDerivAt Z (dZ t) t)
    (hrate : ∀ t ∈ Icc 0 T, |dY t - dZ t| ≤ B)
    (hinitial : |Y 0 - Z 0| ≤ e0) :
    ∀ t ∈ Icc 0 T, |Y t - Z t| ≤ e0 + B * t := by
  have hD : ∀ t ∈ Icc 0 T,
      HasDerivAt (fun s => Y s - Z s) (dY t - dZ t) t := by
    intro t ht
    exact (hY t ht).sub (hZ t ht)
  have hbound : ∀ t ∈ Ico 0 T, ‖dY t - dZ t‖ ≤ B := by
    intro t ht
    rw [Real.norm_eq_abs]
    exact hrate t (Ico_subset_Icc_self ht)
  intro t ht
  have hinc := norm_image_sub_le_of_norm_deriv_right_le_segment
    (fun s hs => (hD s hs).continuousAt.continuousWithinAt)
    (fun s hs => (hD s (Ico_subset_Icc_self hs)).hasDerivWithinAt)
    hbound t ht
  rw [Real.norm_eq_abs, sub_zero] at hinc
  have htri := abs_add ((Y t - Z t) - (Y 0 - Z 0)) (Y 0 - Z 0)
  have hid : ((Y t - Z t) - (Y 0 - Z 0)) + (Y 0 - Z 0) = Y t - Z t := by ring
  rw [hid] at htri
  exact htri.trans (by linarith only [hinc, hinitial])

theorem cumulative_trapping_error_from_class_amounts
    (N : ι → ℝ) (group : ι → κ)
    (x z c : ℝ → ι → ℝ) (cClass delta : ℝ → κ → ℝ)
    (Y Z : ℝ → ℝ) (T e0 B : ℝ)
    (shared : ∀ t ∈ Icc 0 T, ∀ i, c t i = cClass t (group i))
    (hdelta : ∀ t ∈ Icc 0 T, ∀ k,
      |classAmount N group (x t) k - classAmount N group (z t) k| ≤ delta t k)
    (hbudget : ∀ t ∈ Icc 0 T, ∑ k, |cClass t k| * delta t k ≤ B)
    (hY : ∀ t ∈ Icc 0 T, HasDerivAt Y (trappedRate N (c t) (x t)) t)
    (hZ : ∀ t ∈ Icc 0 T, HasDerivAt Z (trappedRate N (c t) (z t)) t)
    (hinitial : |Y 0 - Z 0| ≤ e0) :
    ∀ t ∈ Icc 0 T, |Y t - Z t| ≤ e0 + B * t := by
  apply cumulative_scalar_error_from_derivative_bound Y Z
    (fun t => trappedRate N (c t) (x t)) (fun t => trappedRate N (c t) (z t))
    T e0 B hY hZ _ hinitial
  intro t ht
  exact (class_trapping_flux_error_from_class_amounts N (c t) (x t) (z t) group
    (cClass t) (delta t) (shared t ht) (hdelta t ht)).trans (hbudget t ht)

end Naheng.Contracts

#print Naheng.Contracts.class_trapping_flux_error_from_class_amounts
#print axioms Naheng.Contracts.class_trapping_flux_error_from_class_amounts
#print Naheng.Contracts.cumulative_scalar_error_from_derivative_bound
#print axioms Naheng.Contracts.cumulative_scalar_error_from_derivative_bound
#print Naheng.Contracts.cumulative_trapping_error_from_class_amounts
#print axioms Naheng.Contracts.cumulative_trapping_error_from_class_amounts
