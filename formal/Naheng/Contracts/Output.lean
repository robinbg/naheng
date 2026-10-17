import Naheng.Reduction.FixedCurrentReadout
import Mathlib.Tactic.FieldSimp

/- Conditional same-current, same-temperature real contracts for SiteModel's
   actual exponential rates. Bounds below start at primitive occupation errors
   and fixed positive parameters. Root residuals are independent certification
   obligations; no Float, sampled-support or closed-loop certificate is implied. -/
set_option pp.proofs false
namespace Naheng.Contracts
open Set
open scoped BigOperators
open Naheng.Reduction
variable {ι : Type*} [Fintype ι]

noncomputable def intervalRateFloor (k bias : ι → ℝ) (s L U : ℝ) (i : ι) : ℝ :=
  k i * min (Real.exp ((L - bias i) / s)) (Real.exp ((bias i - U) / s))

noncomputable def intervalRateCeiling (k bias : ι → ℝ) (s L U : ℝ) (i : ι) : ℝ :=
  k i * (Real.exp ((U - bias i) / s) + Real.exp ((bias i - L) / s))

noncomputable def primitiveSlopeFloor (F theta : ℝ) (N k bias : ι → ℝ)
    (s L U : ℝ) : ℝ := F * theta / s * ∑ i, N i * intervalRateFloor k bias s L U i

noncomputable def primitiveDriveBudget (F theta : ℝ) (N k bias delta : ι → ℝ)
    (s L U : ℝ) : ℝ := F * theta * ∑ i, N i * intervalRateCeiling k bias s L U i * delta i

theorem interval_exp_rate_bounds (k bias : ι → ℝ) (s L U u : ℝ)
    (hs : 0 < s) (hk : ∀ i, 0 ≤ k i) (hu : u ∈ Icc L U) (i : ι) :
    intervalRateFloor k bias s L U i ≤ driveInsertionCoeff k bias s u i ∧
    intervalRateFloor k bias s L U i ≤ driveRemovalCoeff k bias s u i ∧
    driveInsertionCoeff k bias s u i + driveRemovalCoeff k bias s u i ≤
      intervalRateCeiling k bias s L U i := by
  have hAlo : Real.exp ((L - bias i) / s) ≤ Real.exp ((u - bias i) / s) :=
    Real.exp_le_exp.mpr (div_le_div_of_nonneg_right (by linarith [hu.1]) hs.le)
  have hBlo : Real.exp ((bias i - U) / s) ≤ Real.exp ((bias i - u) / s) :=
    Real.exp_le_exp.mpr (div_le_div_of_nonneg_right (by linarith [hu.2]) hs.le)
  have hAhi : Real.exp ((u - bias i) / s) ≤ Real.exp ((U - bias i) / s) :=
    Real.exp_le_exp.mpr (div_le_div_of_nonneg_right (by linarith [hu.2]) hs.le)
  have hBhi : Real.exp ((bias i - u) / s) ≤ Real.exp ((bias i - L) / s) :=
    Real.exp_le_exp.mpr (div_le_div_of_nonneg_right (by linarith [hu.1]) hs.le)
  have hneg : -(u - bias i) / s = (bias i - u) / s := by ring
  dsimp [intervalRateFloor, intervalRateCeiling, driveInsertionCoeff, driveRemovalCoeff]
  rw [hneg]
  exact ⟨mul_le_mul_of_nonneg_left ((min_le_left _ _).trans hAlo) (hk i),
    mul_le_mul_of_nonneg_left ((min_le_right _ _).trans hBlo) (hk i), by
    rw [mul_add]
    exact add_le_add (mul_le_mul_of_nonneg_left hAhi (hk i))
      (mul_le_mul_of_nonneg_left hBhi (hk i))⟩

theorem primitive_slope_floor_positive [Nonempty ι]
    (F theta : ℝ) (N k bias : ι → ℝ) (s L U : ℝ)
    (hF : 0 < F) (hth : 0 < theta) (hs : 0 < s)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i) :
    0 < primitiveSlopeFloor F theta N k bias s L U := by
  apply mul_pos (div_pos (mul_pos hF hth) hs)
  exact Finset.sum_pos (fun i _ => mul_pos (hN i)
    (mul_pos (hk i) (lt_min (Real.exp_pos _) (Real.exp_pos _)))) Finset.univ_nonempty

theorem primitive_uniform_slope_floor
    (F theta : ℝ) (N k bias z : ι → ℝ) (s L U : ℝ)
    (hF : 0 ≤ F) (hth : 0 ≤ theta) (hs : 0 < s)
    (hN : ∀ i, 0 ≤ N i) (hk : ∀ i, 0 ≤ k i)
    (hz : ∀ i, z i ∈ Icc 0 1) :
    ∀ u ∈ Icc L U, primitiveSlopeFloor F theta N k bias s L U ≤
      driveSlopeMagnitude F theta N k bias s z u := by
  intro u hu
  apply mul_le_mul_of_nonneg_left _ (div_nonneg (mul_nonneg hF hth) hs.le)
  apply Finset.sum_le_sum
  intro i _
  apply mul_le_mul_of_nonneg_left _ (hN i)
  have hb := interval_exp_rate_bounds k bias s L U u hs hk hu i
  have ha := mul_le_mul_of_nonneg_right hb.1 (sub_nonneg.mpr (hz i).2)
  have hc := mul_le_mul_of_nonneg_right hb.2.1 (hz i).1
  calc
    intervalRateFloor k bias s L U i = intervalRateFloor k bias s L U i * z i +
        intervalRateFloor k bias s L U i * (1 - z i) := by ring
    _ ≤ driveRemovalCoeff k bias s u i * z i +
        driveInsertionCoeff k bias s u i * (1 - z i) := add_le_add hc ha

theorem primitive_occupation_budget
    (F theta : ℝ) (N k bias delta x z : ι → ℝ) (s L U u : ℝ)
    (hF : 0 ≤ F) (hth : 0 ≤ theta) (hs : 0 < s)
    (hN : ∀ i, 0 ≤ N i) (hk : ∀ i, 0 ≤ k i)
    (hd : ∀ i, |x i - z i| ≤ delta i) (hu : u ∈ Icc L U) :
    occupationDriveBudget F theta N k bias s x z u ≤
      primitiveDriveBudget F theta N k bias delta s L U := by
  dsimp [occupationDriveBudget, primitiveDriveBudget]
  rw [abs_of_nonneg (mul_nonneg hF hth)]
  apply mul_le_mul_of_nonneg_left _ (mul_nonneg hF hth)
  apply Finset.sum_le_sum
  intro i _
  have hA : 0 ≤ driveInsertionCoeff k bias s u i := mul_nonneg (hk i) (Real.exp_pos _).le
  have hB : 0 ≤ driveRemovalCoeff k bias s u i := mul_nonneg (hk i) (Real.exp_pos _).le
  rw [abs_of_nonneg (hN i), abs_of_nonneg (add_nonneg hA hB)]
  exact mul_le_mul
    (mul_le_mul_of_nonneg_left (interval_exp_rate_bounds k bias s L U u hs hk hu i).2.2 (hN i))
    (hd i) (abs_nonneg _) (mul_nonneg (hN i) (by
      dsimp [intervalRateCeiling]
      exact mul_nonneg (hk i) (add_nonneg (Real.exp_pos _).le (Real.exp_pos _).le)))

theorem voltage_error_from_primitive_occupation [Nonempty ι]
    (F theta V0 R I : ℝ) (N k bias delta x z : ι → ℝ)
    (s L U ux uz eta_x eta_z : ℝ)
    (hF : 0 < F) (hth : 0 < theta) (hs : 0 < s)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i)
    (hz : ∀ i, z i ∈ Icc 0 1) (hd : ∀ i, |x i - z i| ≤ delta i)
    (hux : ux ∈ Icc L U) (huz : uz ∈ Icc L U)
    (hxroot : |fixedCurrentDriveBalance F theta N k bias s I x ux| ≤ eta_x)
    (hzroot : |fixedCurrentDriveBalance F theta N k bias s I z uz| ≤ eta_z) :
    |fixedCurrentVoltage V0 R I ux - fixedCurrentVoltage V0 R I uz| ≤
      (primitiveDriveBudget F theta N k bias delta s L U + eta_x + eta_z) /
        primitiveSlopeFloor F theta N k bias s L U := by
  have hm := primitive_slope_floor_positive F theta N k bias s L U hF hth hs hN hk
  have h := fixed_current_drive_error_with_residuals F theta N k bias s I x z L U
    (primitiveSlopeFloor F theta N k bias s L U) ux uz eta_x eta_z hs hm hux huz
    (primitive_uniform_slope_floor F theta N k bias z s L U hF.le hth.le hs
      (fun i => (hN i).le) (fun i => (hk i).le) hz) hxroot hzroot
  have budget := primitive_occupation_budget F theta N k bias delta x z s L U ux
    hF.le hth.le hs (fun i => (hN i).le) (fun i => (hk i).le) hd hux
  have hid : fixedCurrentVoltage V0 R I ux - fixedCurrentVoltage V0 R I uz = ux - uz := by
    dsimp [fixedCurrentVoltage]; ring
  rw [hid]
  exact h.trans (div_le_div_of_nonneg_right
    (add_le_add_right (add_le_add_right budget eta_x) eta_z) hm.le)

/- A nonempty positive one-site model with two distinct physical states and
   different exact same-current drives. This is a real algebraic witness, not
   a run of the numerical solver. -/
theorem positive_same_current_distinct_states_witness :
    ∃ (x z : Unit → ℝ) (ux uz : ℝ),
      (∀ i, x i ∈ Icc 0 1 ∧ z i ∈ Icc 0 1) ∧ x ≠ z ∧
      fixedCurrentDriveBalance 1 1 (fun _ => 1) (fun _ => 1) (fun _ => 0) 1 0 x ux = 0 ∧
      fixedCurrentDriveBalance 1 1 (fun _ => 1) (fun _ => 1) (fun _ => 0) 1 0 z uz = 0 ∧
      fixedCurrentVoltage 0 0 0 uz < fixedCurrentVoltage 0 0 0 ux := by
  have hp : 0 < Real.exp 1 + Real.exp (-1) := add_pos (Real.exp_pos _) (Real.exp_pos _)
  have hlt : Real.exp (-1) < Real.exp 1 := Real.exp_lt_exp.mpr (by norm_num)
  have hxlo : 0 ≤ Real.exp 1 / (Real.exp 1 + Real.exp (-1)) := div_nonneg (Real.exp_pos _).le hp.le
  have hxhi : Real.exp 1 / (Real.exp 1 + Real.exp (-1)) ≤ 1 :=
    (div_le_iff₀ hp).mpr (by linarith only [(Real.exp_pos (-1)).le])
  have hxhalf : (1/2 : ℝ) < Real.exp 1 / (Real.exp 1 + Real.exp (-1)) :=
    (lt_div_iff₀ hp).mpr (by linarith only [hlt])
  refine ⟨(fun _ => Real.exp 1 / (Real.exp 1 + Real.exp (-1))), (fun _ => 1/2), 1, 0, ?_, ?_, ?_, ?_, ?_⟩
  · intro i; exact ⟨⟨hxlo,hxhi⟩,by norm_num⟩
  · intro h
    have hh := congrFun h ()
    change Real.exp 1 / (Real.exp 1 + Real.exp (-1)) = (1/2 : ℝ) at hh
    linarith only [hxhalf,hh]
  · norm_num [fixedCurrentDriveBalance, driveInsertionCoeff, driveRemovalCoeff]
    field_simp
    ring
  · norm_num [fixedCurrentDriveBalance, driveInsertionCoeff, driveRemovalCoeff]
  · norm_num [fixedCurrentVoltage]

end Naheng.Contracts

#print Naheng.Contracts.interval_exp_rate_bounds
#print axioms Naheng.Contracts.interval_exp_rate_bounds
#print Naheng.Contracts.primitive_slope_floor_positive
#print axioms Naheng.Contracts.primitive_slope_floor_positive
#print Naheng.Contracts.primitive_uniform_slope_floor
#print axioms Naheng.Contracts.primitive_uniform_slope_floor
#print Naheng.Contracts.primitive_occupation_budget
#print axioms Naheng.Contracts.primitive_occupation_budget
#print Naheng.Contracts.voltage_error_from_primitive_occupation
#print axioms Naheng.Contracts.voltage_error_from_primitive_occupation
#print Naheng.Contracts.positive_same_current_distinct_states_witness
#print axioms Naheng.Contracts.positive_same_current_distinct_states_witness
