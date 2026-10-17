import Naheng.Reduction.FixedCurrentReadout
import Mathlib.Analysis.Calculus.MeanValue

/- Exact real counterparts of SiteModel's trapped flux and thermal.py storage
   equation. Shared electrical/thermal parameters and management input are
   explicit. Different-temperature side coefficients require their own raw
   coefficient certificate; no same-coefficient assumption is hidden. -/
set_option pp.proofs false
namespace Naheng.Contracts
open Set
open scoped BigOperators
variable {ι : Type*} [Fintype ι]

noncomputable def trappedFlux (N c x : ι → ℝ) : ℝ := ∑ i, N i * c i * x i
noncomputable def trappingBudget (N c delta : ι → ℝ) : ℝ := ∑ i, |N i * c i| * delta i

theorem trapping_error_from_occupation
    (N c delta x z : ι → ℝ) (hd : ∀ i, |x i - z i| ≤ delta i) :
    |trappedFlux N c x - trappedFlux N c z| ≤ trappingBudget N c delta := by
  have hid : trappedFlux N c x - trappedFlux N c z = ∑ i, N i * c i * (x i-z i) := by
    simp [trappedFlux, mul_sub, Finset.sum_sub_distrib]
  rw [hid]
  calc
    |∑ i, N i * c i * (x i - z i)| ≤ ∑ i, |N i * c i * (x i-z i)| :=
      Finset.abs_sum_le_sum_abs _ Finset.univ
    _ ≤ trappingBudget N c delta := by
      apply Finset.sum_le_sum
      intro i _
      rw [abs_mul]
      exact mul_le_mul_of_nonneg_left (hd i) (abs_nonneg _)

noncomputable def thermalStorage (I R heat G Tamb management T trapping : ℝ) : ℝ :=
  I^2*R + heat*trapping + management - G*(T-Tamb)

theorem thermal_storage_error_from_occupation
    (N c delta x z : ι → ℝ) (I R heat G Tamb management Tx Tz dT : ℝ)
    (hd : ∀ i, |x i - z i| ≤ delta i) (hT : |Tx-Tz| ≤ dT) :
    |thermalStorage I R heat G Tamb management Tx (trappedFlux N c x) -
      thermalStorage I R heat G Tamb management Tz (trappedFlux N c z)| ≤
      |heat| * trappingBudget N c delta + |G| * dT := by
  have hid : thermalStorage I R heat G Tamb management Tx (trappedFlux N c x) -
      thermalStorage I R heat G Tamb management Tz (trappedFlux N c z) =
      heat*(trappedFlux N c x-trappedFlux N c z)-G*(Tx-Tz) := by
    dsimp [thermalStorage]; ring
  rw [hid]
  calc
    |heat*(trappedFlux N c x-trappedFlux N c z)-G*(Tx-Tz)| ≤
        |heat*(trappedFlux N c x-trappedFlux N c z)| + |G*(Tx-Tz)| := abs_sub _ _
    _ = |heat| * |trappedFlux N c x-trappedFlux N c z| + |G| * |Tx-Tz| := by simp only [abs_mul]
    _ ≤ |heat| * trappingBudget N c delta+|G| * dT :=
      add_le_add (mul_le_mul_of_nonneg_left (trapping_error_from_occupation N c delta x z hd) (abs_nonneg _))
        (mul_le_mul_of_nonneg_left hT (abs_nonneg _))

theorem thermal_temperature_derivative_error_from_occupation
    (N c delta x z : ι → ℝ) (I R heat G Tamb management Tx Tz dT C : ℝ)
    (hC : 0 < C) (hd : ∀ i, |x i-z i| ≤ delta i) (hT : |Tx-Tz| ≤ dT) :
    |thermalStorage I R heat G Tamb management Tx (trappedFlux N c x)/C -
      thermalStorage I R heat G Tamb management Tz (trappedFlux N c z)/C| ≤
      (|heat| * trappingBudget N c delta+|G| * dT)/C := by
  rw [← sub_div, abs_div, abs_of_pos hC]
  exact div_le_div_of_nonneg_right
    (thermal_storage_error_from_occupation N c delta x z I R heat G Tamb management Tx Tz dT hd hT) hC.le

/- Whole-time energy is a supplied solution of the electrical port equation
   E'=I(t)*V(t). It is not a rectangle quadrature, ledger interpolation or a
   lifecycle cash/profit theorem. The conclusion is derived from the derivative
   and state-dependent voltage budget, not assumed as an energy-error input. -/
theorem cumulative_electrical_energy_error
    (Ex Ez I Vx Vz : ℝ → ℝ) (T imax eV e0 : ℝ)
    (hT : 0 ≤ T) (hi : 0 ≤ imax) (hev : 0 ≤ eV)
    (hEx : ∀ t ∈ Icc 0 T, HasDerivAt Ex (I t * Vx t) t)
    (hEz : ∀ t ∈ Icc 0 T, HasDerivAt Ez (I t * Vz t) t)
    (hI : ∀ t ∈ Icc 0 T, |I t| ≤ imax)
    (hV : ∀ t ∈ Icc 0 T, |Vx t-Vz t| ≤ eV)
    (h0 : |Ex 0-Ez 0| ≤ e0) :
    |Ex T-Ez T| ≤ e0+imax*eV*T := by
  let D := fun t => Ex t-Ez t
  have hD : ∀ t ∈ Icc 0 T, HasDerivAt D (I t*(Vx t-Vz t)) t := by
    intro t ht
    convert (hEx t ht).sub (hEz t ht) using 1 <;> dsimp [D] <;> ring
  have hbound : ∀ t ∈ Ico 0 T, ‖I t*(Vx t-Vz t)‖ ≤ imax*eV := by
    intro t ht
    rw [Real.norm_eq_abs, abs_mul]
    exact mul_le_mul (hI t (Ico_subset_Icc_self ht)) (hV t (Ico_subset_Icc_self ht))
      (abs_nonneg _) hi
  have hinc := norm_image_sub_le_of_norm_deriv_right_le_segment
    (fun t ht => (hD t ht).continuousAt.continuousWithinAt)
    (fun t ht => (hD t (Ico_subset_Icc_self ht)).hasDerivWithinAt) hbound T ⟨hT,le_refl T⟩
  rw [Real.norm_eq_abs, sub_zero] at hinc
  have htri := abs_add (D T-D 0) (D 0)
  have hid : (D T-D 0)+D 0=D T := by ring
  rw [hid] at htri
  exact htri.trans (by dsimp [D] at *; linarith only [hinc,h0])

theorem missing_temperature_coefficient_bridge_counterexample :
    ∃ (N cx cz x z : Unit → ℝ),
      (∀ i, 0 < N i ∧ 0 ≤ cx i ∧ 0 ≤ cz i ∧ x i=z i ∧ x i∈Icc 0 1) ∧
      trappedFlux N cx x ≠ trappedFlux N cz z := by
  refine ⟨(fun _ => 1),(fun _ => 1),(fun _ => 2),(fun _ => 1/2),(fun _ => 1/2),?_,?_⟩
  · intro i; norm_num
  · norm_num [trappedFlux]

end Naheng.Contracts
#print Naheng.Contracts.trapping_error_from_occupation
#print axioms Naheng.Contracts.trapping_error_from_occupation
#print Naheng.Contracts.thermal_storage_error_from_occupation
#print axioms Naheng.Contracts.thermal_storage_error_from_occupation
#print Naheng.Contracts.thermal_temperature_derivative_error_from_occupation
#print axioms Naheng.Contracts.thermal_temperature_derivative_error_from_occupation
#print Naheng.Contracts.cumulative_electrical_energy_error
#print axioms Naheng.Contracts.cumulative_electrical_energy_error
#print Naheng.Contracts.missing_temperature_coefficient_bridge_counterexample
#print axioms Naheng.Contracts.missing_temperature_coefficient_bridge_counterexample

