import Mathlib.Analysis.Calculus.MeanValue
import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Analysis.Calculus.Deriv.Mul
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring

open Set
open scoped BigOperators

namespace Naheng.Aging


/- Standard conditional facts, not new sodium-cell laws. The finite trapping
   flux matches SiteModel.rhs and trapped_sodium_rate_mol_per_s. Supplied ODE
   solutions are explicit: existence, numerical accuracy and physical validity
   are not asserted. The accessibility map below is the runtime's declared,
   uncalibrated trapped_accessibility_v1 initialization, not measured capacity. -/
noncomputable def trappingRate {n : ℕ} (N c x : Fin n → ℝ) : ℝ :=
  ∑ i, N i * c i * x i

theorem trappingRate_nonneg {n : ℕ} (N c x : Fin n → ℝ)
    (hN : ∀ i, 0 ≤ N i) (hc : ∀ i, 0 ≤ c i) (hx : ∀ i, 0 ≤ x i) :
    0 ≤ trappingRate N c x := by
  apply Finset.sum_nonneg
  intro i _
  exact mul_nonneg (mul_nonneg (hN i) (hc i)) (hx i)



theorem trapped_inventory_monotone {n : ℕ} (N : Fin n → ℝ)
    (c x : ℝ → Fin n → ℝ) (y : ℝ → ℝ) (T : ℝ)
    (hN : ∀ i, 0 ≤ N i)
    (hc : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ c t i)
    (hx : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hode : ∀ t ∈ Icc 0 T, HasDerivAt y (trappingRate N (c t) (x t)) t) :
    MonotoneOn y (Icc 0 T) := by
  intro a ha b hb hab
  have hmem : ∀ t ∈ Icc a b, t ∈ Icc 0 T := by
    intro t ht
    exact ⟨le_trans ha.1 ht.1, le_trans ht.2 hb.2⟩
  have hneg : -y b ≤ -y a := by
    apply image_le_of_deriv_right_le_deriv_boundary
      (fun t ht => (hode t (hmem t ht)).neg.continuousAt.continuousWithinAt)
      (fun t ht => (hode t (hmem t (Ico_subset_Icc_self ht))).neg.hasDerivWithinAt)
      (B := fun _ => -y a) (B' := fun _ => 0) (le_refl _) continuousOn_const
      (fun t _ => (hasDerivAt_const t (-y a)).hasDerivWithinAt)
    · intro t ht
      have hnonneg := trappingRate_nonneg N (c t) (x t) hN
        (hc t (hmem t (Ico_subset_Icc_self ht)))
        (hx t (hmem t (Ico_subset_Icc_self ht)))
      linarith
    · exact ⟨hab, le_refl b⟩
  linarith



noncomputable def accessibleFraction (N y : ℝ) : ℝ := max 0 (1 - y / N)

theorem accessible_fraction_antitone (N y₁ y₂ : ℝ) (hN : 0 < N) (hy : y₁ ≤ y₂) :
    accessibleFraction N y₂ ≤ accessibleFraction N y₁ := by
  apply max_le_max (le_refl 0)
  have hdiv : y₁ / N ≤ y₂ / N := div_le_div_of_nonneg_right hy (le_of_lt hN)
  linarith



theorem initialized_occupancy_antitone (N theta y₁ y₂ : ℝ)
    (hN : 0 < N) (htheta : 0 ≤ theta) (hy : y₁ ≤ y₂) :
    theta * accessibleFraction N y₂ ≤ theta * accessibleFraction N y₁ :=
  mul_le_mul_of_nonneg_left (accessible_fraction_antitone N y₁ y₂ hN hy) htheta

/- Capacity is I times an actual first voltage-cutoff elapsed time, matching
   constant-current protocol_capacity. The missing bridge is deliberately
   explicit: initialization order does not by itself prove voltage trace order.
   A successful measured cutoff must be distinguished from horizon censoring
   or an earlier operational/thermal/reservoir exit. -/


def FirstVoltageCutoff (V : ℝ → ℝ) (cutoff tau : ℝ) : Prop :=
  0 ≤ tau ∧ V tau ≤ cutoff ∧ ∀ t, 0 ≤ t → t < tau → cutoff < V t

theorem first_cutoff_time_order (Vaged Vfresh : ℝ → ℝ) (cutoff taged tfresh : ℝ)
    (haged : FirstVoltageCutoff Vaged cutoff taged)
    (hfresh : FirstVoltageCutoff Vfresh cutoff tfresh)
    (hV : ∀ t ∈ Icc 0 tfresh, Vaged t ≤ Vfresh t) :
    taged ≤ tfresh := by
  by_contra h
  have hlt : tfresh < taged := lt_of_not_ge h
  have hat : cutoff < Vaged tfresh := haged.2.2 tfresh hfresh.1 hlt
  have horder := hV tfresh ⟨hfresh.1, le_refl tfresh⟩
  linarith [hfresh.2.1]



theorem constant_current_capacity_order (Vaged Vfresh : ℝ → ℝ)
    (I cutoff taged tfresh : ℝ) (hI : 0 ≤ I)
    (haged : FirstVoltageCutoff Vaged cutoff taged)
    (hfresh : FirstVoltageCutoff Vfresh cutoff tfresh)
    (hV : ∀ t ∈ Icc 0 tfresh, Vaged t ≤ Vfresh t) :
    I * taged ≤ I * tfresh :=
  mul_le_mul_of_nonneg_left
    (first_cutoff_time_order Vaged Vfresh cutoff taged tfresh haged hfresh hV) hI



theorem protocol_right_censor_lower_bound (V : ℝ → ℝ) (I cutoff H tau : ℝ)
    (hI : 0 < I) (hH : 0 ≤ H)
    (hnotcutoff : ∀ t ∈ Icc 0 H, cutoff < V t)
    (hend : FirstVoltageCutoff V cutoff tau) :
    H < tau ∧ I * H < I * tau := by
  have ht : H < tau := by
    by_contra h
    have hlow := hnotcutoff tau ⟨hend.1, le_of_not_gt h⟩
    linarith [hend.2.1]
  exact ⟨ht, mul_lt_mul_of_pos_left ht hI⟩

/- A generic declared protocol counterexample, not a counterexample to the
   specific runtime SiteModel: higher trapped inventory plus two valid voltage
   cutoff traces does not imply smaller measured capacity without the missing
   readout/trajectory comparison. -/


theorem trapped_order_alone_not_capacity_order :
    ∃ (yf ya : ℝ) (Vf Va : ℝ → ℝ) (tf ta : ℝ),
      yf < ya ∧ FirstVoltageCutoff Vf 0 tf ∧ FirstVoltageCutoff Va 0 ta ∧ tf < ta := by
  refine ⟨0, 1, (fun t => 1 - t), (fun t => 2 - t), 1, 2, ?_⟩
  constructor
  · norm_num
  constructor
  · refine ⟨by norm_num, by norm_num, ?_⟩
    intro t _ ht
    dsimp
    linarith
  constructor
  · refine ⟨by norm_num, by norm_num, ?_⟩
    intro t _ ht
    dsimp
    linarith
  · norm_num

/- Lifetime capacity is a function of age measured under one fixed, successful
   initialization/temperature/current/cutoff protocol. A negative derivative
   bound is a substantive additional condition on that measured-capacity
   curve, not a consequence of trapping alone. By shifting C(t)+s*t we derive
   the secant slope; endpoint equality plus an actual output error then gives
   an inverse-time bound. Standard mean-value/inverse-condition-number facts. -/


theorem decreasing_capacity_secant_of_derivative (C d : ℝ → ℝ) (s T : ℝ)
    (hode : ∀ t ∈ Icc 0 T, HasDerivAt C (d t) t)
    (hbound : ∀ t ∈ Icc 0 T, d t ≤ -s) :
    ∀ a ∈ Icc 0 T, ∀ b ∈ Icc 0 T, a ≤ b → s * (b - a) ≤ C a - C b := by
  intro a ha b hb hab
  have hmem : ∀ t ∈ Icc a b, t ∈ Icc 0 T := by
    intro t ht
    exact ⟨le_trans ha.1 ht.1, le_trans ht.2 hb.2⟩
  have h : C b ≤ C a - s * (b - a) := by
    apply image_le_of_deriv_right_le_deriv_boundary
      (fun t ht => (hode t (hmem t ht)).continuousAt.continuousWithinAt)
      (fun t ht => (hode t (hmem t (Ico_subset_Icc_self ht))).hasDerivWithinAt)
      (B := fun t => C a - s * (t - a)) (B' := fun _ => -s)
    · simp
    · exact continuousOn_const.sub (continuousOn_const.mul (continuousOn_id.sub continuousOn_const))
    · intro t _
      convert ((hasDerivAt_const t (C a)).sub
        (((hasDerivAt_id t).sub_const a).const_mul s)).hasDerivWithinAt using 1 <;> simp
    · intro t ht
      exact hbound t (hmem t (Ico_subset_Icc_self ht))
    · exact ⟨hab, le_refl b⟩
  nlinarith



theorem endpoint_time_error_of_capacity_error
    (C Ceff : ℝ → ℝ) (theta tau taueff eps s T : ℝ)
    (hs : 0 < s) (htau : tau ∈ Icc 0 T) (htaueff : taueff ∈ Icc 0 T)
    (hslope : ∀ a ∈ Icc 0 T, ∀ b ∈ Icc 0 T, a ≤ b → s * (b - a) ≤ C a - C b)
    (htrue : C tau = theta) (heff : Ceff taueff = theta)
    (herror : |C taueff - Ceff taueff| ≤ eps) :
    |tau - taueff| ≤ eps / s := by
  rw [heff] at herror
  have herr := abs_le.mp herror
  apply (le_div_iff₀ hs).2
  rcases le_total tau taueff with hle | hle
  · rw [abs_of_nonpos (sub_nonpos.mpr hle)]
    have h := hslope tau htau taueff htaueff hle
    rw [htrue] at h
    nlinarith [herr.1]
  · rw [abs_of_nonneg (sub_nonneg.mpr hle)]
    have h := hslope taueff htaueff tau htau hle
    rw [htrue] at h
    nlinarith [herr.2]



theorem endpoint_time_error_from_derivative
    (C Ceff d : ℝ → ℝ) (theta tau taueff eps s T : ℝ)
    (hs : 0 < s) (htau : tau ∈ Icc 0 T) (htaueff : taueff ∈ Icc 0 T)
    (hode : ∀ t ∈ Icc 0 T, HasDerivAt C (d t) t)
    (hbound : ∀ t ∈ Icc 0 T, d t ≤ -s)
    (htrue : C tau = theta) (heff : Ceff taueff = theta)
    (herror : |C taueff - Ceff taueff| ≤ eps) :
    |tau - taueff| ≤ eps / s :=
  endpoint_time_error_of_capacity_error C Ceff theta tau taueff eps s T hs htau htaueff
    (decreasing_capacity_secant_of_derivative C d s T hode hbound) htrue heff herror



def RetirementEndpoint (C : ℝ → ℝ) (theta tau : ℝ) : Prop :=
  0 ≤ tau ∧ C tau ≤ theta ∧ ∀ t, 0 ≤ t → t < tau → theta < C t

theorem flat_above_threshold_no_endpoint (theta gap : ℝ) (hgap : 0 < gap) :
    ¬ ∃ tau, RetirementEndpoint (fun _ => theta + gap) theta tau := by
  rintro ⟨tau, htau⟩
  have h := htau.2.1
  dsimp at h
  linarith



theorem flat_at_threshold_no_positive_slope (theta s : ℝ) (hs : 0 < s) :
    ¬ (∀ a ∈ Icc (0 : ℝ) 1, ∀ b ∈ Icc (0 : ℝ) 1,
      a ≤ b → s * (b - a) ≤ (fun _ => theta) a - (fun _ => theta) b) := by
  intro h
  have hh := h 0 (by norm_num) 1 (by norm_num) (by norm_num)
  dsimp at hh
  nlinarith



theorem flat_small_capacity_error_does_not_ensure_endpoint (theta eps : ℝ) (heps : 0 < eps) :
    ∃ C Ceff : ℝ → ℝ,
      (∀ t, |C t - Ceff t| ≤ eps) ∧
      RetirementEndpoint Ceff theta 0 ∧ ¬ ∃ tau, RetirementEndpoint C theta tau := by
  refine ⟨(fun _ => theta + eps / 2), (fun _ => theta - eps / 2), ?_, ?_, ?_⟩
  · intro t
    dsimp
    rw [abs_of_nonneg (by linarith)]
    linarith
  · refine ⟨le_refl 0, ?_, ?_⟩
    · dsimp
      linarith
    · intro t ht hlt
      linarith
  · exact flat_above_threshold_no_endpoint theta (eps / 2) (by linarith)



end Naheng.Aging
