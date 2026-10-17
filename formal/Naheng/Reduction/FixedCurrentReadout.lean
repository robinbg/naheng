import Mathlib.Analysis.Calculus.Deriv.MeanValue
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Algebra.BigOperators.Fin
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring

/- Uncompiled conditional readout candidate, mapped to SiteModel.rates,
   solve_drive and observe. F, theta, N, k, bias, scale, I, V0 and resistance
   are the SAME fixed parameters/current/temperature factor for both states.
   Side rate c is absent from the actual current-adapter balance. Real exp,
   finite sums and independently certified root residuals are explicit;
   Float/Brent tolerances do not establish the residual hypotheses below. -/
namespace Naheng.Reduction
open Set
open scoped BigOperators
set_option pp.proofs false

variable {ι : Type*} [Fintype ι]

noncomputable def driveInsertionCoeff (k bias : ι → ℝ) (scale u : ℝ) : ι → ℝ :=
  fun i => k i * Real.exp ((u - bias i) / scale)
noncomputable def driveRemovalCoeff (k bias : ι → ℝ) (scale u : ℝ) : ι → ℝ :=
  fun i => k i * Real.exp (-(u - bias i) / scale)
noncomputable def fixedCurrentDriveBalance (F theta : ℝ) (N k bias : ι → ℝ)
    (scale I : ℝ) (x : ι → ℝ) (u : ℝ) : ℝ :=
  F * theta * (∑ i, N i * (driveRemovalCoeff k bias scale u i * x i -
    driveInsertionCoeff k bias scale u i * (1 - x i))) - I
noncomputable def factoredCurrentDriveBalance (F theta : ℝ) (N k bias : ι → ℝ)
    (scale I : ℝ) (x : ι → ℝ) (u : ℝ) : ℝ :=
  (F * theta * ∑ i, N i * k i * Real.exp (bias i / scale) * x i) * Real.exp (-u / scale) -
  (F * theta * ∑ i, N i * k i * Real.exp (-bias i / scale) * (1 - x i)) * Real.exp (u / scale) - I
noncomputable def occupationDriveBudget (F theta : ℝ) (N k bias : ι → ℝ)
    (scale : ℝ) (x z : ι → ℝ) (u : ℝ) : ℝ :=
  |F * theta| * ∑ i, |N i| * |driveInsertionCoeff k bias scale u i +
    driveRemovalCoeff k bias scale u i| * |x i - z i|
noncomputable def driveSlopeMagnitude (F theta : ℝ) (N k bias : ι → ℝ)
    (scale : ℝ) (z : ι → ℝ) (u : ℝ) : ℝ :=
  F * theta / scale * ∑ i, N i * (driveRemovalCoeff k bias scale u i * z i +
    driveInsertionCoeff k bias scale u i * (1 - z i))
def fixedCurrentVoltage (V0 resistance I u : ℝ) : ℝ := V0 + u - I * resistance

/- Exact real algebra matches solve_drive's scalar removal/insertion form. -/
theorem fixed_current_balance_matches_factored_solver
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (x : ι → ℝ) (u : ℝ) :
    fixedCurrentDriveBalance F theta N k bias scale I x u =
      factoredCurrentDriveBalance F theta N k bias scale I x u := by
  have hA : ∀ i, driveInsertionCoeff k bias scale u i =
      k i * Real.exp (-bias i / scale) * Real.exp (u / scale) := by
    intro i
    have harg : (u - bias i) / scale = -bias i / scale + u / scale := by ring
    dsimp [driveInsertionCoeff]
    rw [harg, Real.exp_add]
    ring
  have hB : ∀ i, driveRemovalCoeff k bias scale u i =
      k i * Real.exp (bias i / scale) * Real.exp (-u / scale) := by
    intro i
    have harg : -(u - bias i) / scale = bias i / scale + -u / scale := by ring
    dsimp [driveRemovalCoeff]
    rw [harg, Real.exp_add]
    ring
  have hsum : (∑ i, N i * (driveRemovalCoeff k bias scale u i * x i -
      driveInsertionCoeff k bias scale u i * (1 - x i))) =
      (∑ i, N i * k i * Real.exp (bias i / scale) * x i) * Real.exp (-u / scale) -
      (∑ i, N i * k i * Real.exp (-bias i / scale) * (1 - x i)) * Real.exp (u / scale) := by
    rw [Finset.sum_mul, Finset.sum_mul, ← Finset.sum_sub_distrib]
    apply Finset.sum_congr rfl
    intro i _
    rw [hA i, hB i]
    ring
  dsimp [fixedCurrentDriveBalance, factoredCurrentDriveBalance]
  rw [hsum]
  ring

#print fixed_current_balance_matches_factored_solver
#print axioms fixed_current_balance_matches_factored_solver

/- Same current cancels. Composition, not total inventory alone, determines
   this finite linear residual at a given drive. No output-error hypothesis. -/
theorem fixed_current_occupation_residual_identity
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (x z : ι → ℝ) (u : ℝ) :
    fixedCurrentDriveBalance F theta N k bias scale I x u -
      fixedCurrentDriveBalance F theta N k bias scale I z u =
      F * theta * ∑ i, N i * (driveInsertionCoeff k bias scale u i +
        driveRemovalCoeff k bias scale u i) * (x i - z i) := by
  have hsum : (∑ i, N i * (driveRemovalCoeff k bias scale u i * x i -
      driveInsertionCoeff k bias scale u i * (1 - x i))) -
      (∑ i, N i * (driveRemovalCoeff k bias scale u i * z i -
      driveInsertionCoeff k bias scale u i * (1 - z i))) =
      ∑ i, N i * (driveInsertionCoeff k bias scale u i +
        driveRemovalCoeff k bias scale u i) * (x i - z i) := by
    rw [← Finset.sum_sub_distrib]
    apply Finset.sum_congr rfl
    intro i _
    ring
  rw [← hsum]
  dsimp [fixedCurrentDriveBalance]
  ring

#print fixed_current_occupation_residual_identity
#print axioms fixed_current_occupation_residual_identity

theorem fixed_current_occupation_residual_abs_bound
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (x z : ι → ℝ) (u : ℝ) :
    |fixedCurrentDriveBalance F theta N k bias scale I x u -
      fixedCurrentDriveBalance F theta N k bias scale I z u| ≤
      occupationDriveBudget F theta N k bias scale x z u := by
  rw [fixed_current_occupation_residual_identity, abs_mul]
  dsimp only [occupationDriveBudget]
  apply mul_le_mul_of_nonneg_left _ (abs_nonneg (F * theta))
  calc
    |∑ i, N i * (driveInsertionCoeff k bias scale u i +
        driveRemovalCoeff k bias scale u i) * (x i - z i)| ≤
        ∑ i, |N i * (driveInsertionCoeff k bias scale u i +
          driveRemovalCoeff k bias scale u i) * (x i - z i)| :=
      Finset.abs_sum_le_sum_abs _ Finset.univ
    _ = ∑ i, |N i| * |driveInsertionCoeff k bias scale u i +
        driveRemovalCoeff k bias scale u i| * |x i - z i| := by
      simp only [abs_mul]

#print fixed_current_occupation_residual_abs_bound
#print axioms fixed_current_occupation_residual_abs_bound

/- The actual real exponential coefficients give the derivative. The separate
   uniform slope-floor premise below must be established on the entire drive
   interval; strict point monotonicity or sample slopes cannot supply it. -/
theorem fixed_current_balance_hasDerivAt
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (z : ι → ℝ) (u : ℝ)
    (_hscale : 0 < scale) :
    HasDerivAt (fixedCurrentDriveBalance F theta N k bias scale I z)
      (-driveSlopeMagnitude F theta N k bias scale z u) u := by
  have hA : ∀ i, HasDerivAt (fun v => driveInsertionCoeff k bias scale v i)
      (driveInsertionCoeff k bias scale u i / scale) u := by
    intro i
    have hlinear := ((hasDerivAt_id u).sub_const (bias i)).div_const scale
    convert hlinear.exp.const_mul (k i)
      using 1 <;> dsimp [driveInsertionCoeff] <;> ring
  have hB : ∀ i, HasDerivAt (fun v => driveRemovalCoeff k bias scale v i)
      (-driveRemovalCoeff k bias scale u i / scale) u := by
    intro i
    have hlinear := (((hasDerivAt_id u).sub_const (bias i)).neg).div_const scale
    convert hlinear.exp.const_mul (k i)
      using 1 <;> dsimp [driveRemovalCoeff] <;> ring
  have h : HasDerivAt (fixedCurrentDriveBalance F theta N k bias scale I z)
      (F * theta * ∑ i, N i * ((-driveRemovalCoeff k bias scale u i / scale) * z i -
        (driveInsertionCoeff k bias scale u i / scale) * (1 - z i))) u := by
    simpa only [fixedCurrentDriveBalance] using
      ((HasDerivAt.sum (u := Finset.univ) (fun i _ =>
        (((hB i).mul_const (z i)).sub ((hA i).mul_const (1 - z i))).const_mul (N i))).const_mul
          (F * theta)).sub_const I
  convert h using 1
  dsimp [driveSlopeMagnitude]
  simp only [Finset.mul_sum, ← Finset.sum_neg_distrib]
  apply Finset.sum_congr rfl
  intro i _
  ring

#print fixed_current_balance_hasDerivAt
#print axioms fixed_current_balance_hasDerivAt

theorem fixed_current_strict_drive_secant_from_coefficients
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (z : ι → ℝ)
    (L U m : ℝ) (hscale : 0 < scale) (_hm : 0 < m)
    (slope_floor : ∀ u ∈ Icc L U, m ≤ driveSlopeMagnitude F theta N k bias scale z u) :
    ∀ a ∈ Icc L U, ∀ b ∈ Icc L U, a ≤ b →
      m * (b - a) ≤ fixedCurrentDriveBalance F theta N k bias scale I z a -
        fixedCurrentDriveBalance F theta N k bias scale I z b := by
  have hode := fixed_current_balance_hasDerivAt F theta N k bias scale I z
  intro a ha b hb hab
  have h := (convex_Icc L U).image_sub_le_mul_sub_of_deriv_le
    (fun u _ => (hode u hscale).continuousAt.continuousWithinAt)
    (fun u _ => (hode u hscale).differentiableAt.differentiableWithinAt)
    (C := -m) (fun u hu => by
      rw [(hode u hscale).deriv]
      have hh := slope_floor u (interior_subset hu)
      linarith) a ha b hb hab
  nlinarith

#print fixed_current_strict_drive_secant_from_coefficients
#print axioms fixed_current_strict_drive_secant_from_coefficients

/- eta_x and eta_z are independent bounds on the actual real balance at the
   returned numerical drives. They include root/evaluation certification needs;
   neither returned drive is silently assumed to be an exact root. -/
theorem fixed_current_drive_error_with_residuals
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (x z : ι → ℝ)
    (L U m ux uz eta_x eta_z : ℝ) (hscale : 0 < scale) (hm : 0 < m)
    (hux : ux ∈ Icc L U) (huz : uz ∈ Icc L U)
    (slope_floor : ∀ u ∈ Icc L U, m ≤ driveSlopeMagnitude F theta N k bias scale z u)
    (root_residual_x : |fixedCurrentDriveBalance F theta N k bias scale I x ux| ≤ eta_x)
    (root_residual_z : |fixedCurrentDriveBalance F theta N k bias scale I z uz| ≤ eta_z) :
    |ux - uz| ≤ (occupationDriveBudget F theta N k bias scale x z ux + eta_x + eta_z) / m := by
  let Bx := fixedCurrentDriveBalance F theta N k bias scale I x
  let Bz := fixedCurrentDriveBalance F theta N k bias scale I z
  have hsec := fixed_current_strict_drive_secant_from_coefficients F theta N k bias scale I z
    L U m hscale hm slope_floor
  have hinverse : m * |ux - uz| ≤ |Bz ux - Bz uz| := by
    rcases le_total ux uz with hle | hle
    · rw [abs_of_nonpos (sub_nonpos.mpr hle)]
      have hh := hsec ux hux uz huz hle
      change m * (uz - ux) ≤ Bz ux - Bz uz at hh
      have hhabs := le_abs_self (Bz ux - Bz uz)
      nlinarith only [hh, hhabs]
    · rw [abs_of_nonneg (sub_nonneg.mpr hle)]
      have hh := hsec uz huz ux hux hle
      change m * (ux - uz) ≤ Bz uz - Bz ux at hh
      have hhabs : Bz uz - Bz ux ≤ |Bz ux - Bz uz| := by
        simpa only [abs_sub_comm] using le_abs_self (Bz uz - Bz ux)
      nlinarith only [hh, hhabs]
  have hstate : |Bz ux - Bx ux| ≤ occupationDriveBudget F theta N k bias scale x z ux := by
    simpa only [abs_sub_comm] using
      fixed_current_occupation_residual_abs_bound F theta N k bias scale I x z ux
  have htriangle : |Bz ux - Bz uz| ≤ |Bz ux - Bx ux| + |Bx ux| + |Bz uz| := by
    have hh1 := abs_add (Bz ux - Bx ux) (Bx ux)
    have hh2 := abs_sub ((Bz ux - Bx ux) + Bx ux) (Bz uz)
    have hid : (Bz ux - Bx ux) + Bx ux = Bz ux := by ring
    rw [hid] at hh1 hh2
    linarith
  have hrootx : |Bx ux| ≤ eta_x := root_residual_x
  have hrootz : |Bz uz| ≤ eta_z := root_residual_z
  have hbound : |Bz ux - Bz uz| ≤ occupationDriveBudget F theta N k bias scale x z ux + eta_x + eta_z :=
    htriangle.trans (by linarith only [hstate, hrootx, hrootz])
  apply (le_div_iff₀ hm).2
  simpa only [mul_comm] using hinverse.trans hbound

#print fixed_current_drive_error_with_residuals
#print axioms fixed_current_drive_error_with_residuals

theorem fixed_current_voltage_error_with_residuals
    (F theta V0 resistance : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (x z : ι → ℝ)
    (_hF : 0 < F) (_htheta : 0 < theta) (_hresistance : 0 ≤ resistance)
    (_hN : ∀ i, 0 < N i) (_hk : ∀ i, 0 ≤ k i)
    (_hx : ∀ i, 0 ≤ x i ∧ x i ≤ 1) (_hz : ∀ i, 0 ≤ z i ∧ z i ≤ 1)
    (L U m ux uz eta_x eta_z : ℝ) (hscale : 0 < scale) (hm : 0 < m)
    (_hinterval : L ≤ U)
    (hux : ux ∈ Icc L U) (huz : uz ∈ Icc L U)
    (slope_floor : ∀ u ∈ Icc L U, m ≤ driveSlopeMagnitude F theta N k bias scale z u)
    (root_residual_x : |fixedCurrentDriveBalance F theta N k bias scale I x ux| ≤ eta_x)
    (root_residual_z : |fixedCurrentDriveBalance F theta N k bias scale I z uz| ≤ eta_z) :
    |fixedCurrentVoltage V0 resistance I ux - fixedCurrentVoltage V0 resistance I uz| ≤
      (occupationDriveBudget F theta N k bias scale x z ux + eta_x + eta_z) / m := by
  have hid : fixedCurrentVoltage V0 resistance I ux - fixedCurrentVoltage V0 resistance I uz = ux - uz := by
    dsimp [fixedCurrentVoltage]
    ring
  rw [hid]
  exact fixed_current_drive_error_with_residuals F theta N k bias scale I x z L U m ux uz eta_x eta_z
    hscale hm hux huz slope_floor root_residual_x root_residual_z

#print fixed_current_voltage_error_with_residuals
#print axioms fixed_current_voltage_error_with_residuals

def readoutDemoN : Fin 1 → ℝ := fun _ => 1
def readoutDemoK : Fin 1 → ℝ := fun _ => 1
def readoutDemoBias : Fin 1 → ℝ := fun _ => 0
noncomputable def readoutDemoZ : Fin 1 → ℝ := fun _ => 1 / 2

/- A positive slope floor on a genuine interval for a nonempty positive-site
   model. This supplies an applicability witness, not a calibrated cell or a
   runtime certificate. The floor is derived from the actual exp coefficients. -/
theorem nonempty_fixed_current_slope_floor_example :
    0 < Real.exp (-1) ∧
    (∀ u ∈ Icc (-1 : ℝ) 1, Real.exp (-1) ≤
      driveSlopeMagnitude 1 1 readoutDemoN readoutDemoK readoutDemoBias 1 readoutDemoZ u) := by
  refine ⟨Real.exp_pos _, ?_⟩
  intro u hu
  have hA : Real.exp (-1) ≤ Real.exp u := Real.exp_le_exp.mpr hu.1
  have hB : Real.exp (-1) ≤ Real.exp (-u) := Real.exp_le_exp.mpr (by linarith [hu.2])
  norm_num [driveSlopeMagnitude, driveInsertionCoeff, driveRemovalCoeff,
    readoutDemoN, readoutDemoK, readoutDemoBias, readoutDemoZ, Fin.sum_univ_one]
  linarith

#print nonempty_fixed_current_slope_floor_example
#print axioms nonempty_fixed_current_slope_floor_example
end Naheng.Reduction
