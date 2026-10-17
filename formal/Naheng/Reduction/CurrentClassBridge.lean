import Naheng.Reduction.ClassSufficiency
import Naheng.Reduction.FixedCurrentReadout

/- Same-current pointwise chemical bridge for the actual exp drive balance.
   Retain class amounts and common temperature/parameters. Coalescing requires
   k, bias and side coefficients to share; total q alone is not substituted.
   Exact roots are premises, not inferred from Float/Brent tolerances. -/
set_option pp.proofs false
namespace Naheng.Reduction
open scoped BigOperators
variable {ι κ : Type*} [Fintype ι] [DecidableEq ι] [Fintype κ] [DecidableEq κ]

theorem same_class_state_preserves_fixed_current_balance
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ)
    (group : ι → κ) (kClass biasClass : κ → ℝ)
    (shared_k : ∀ i, k i = kClass (group i))
    (shared_bias : ∀ i, bias i = biasClass (group i))
    (x z : ι → ℝ) (hx : PhysicalOccupation x) (hz : PhysicalOccupation z)
    (same_class_amounts : ∀ j, classAmount N group x j = classAmount N group z j)
    (u : ℝ) :
    fixedCurrentDriveBalance F theta N k bias scale I x u =
      fixedCurrentDriveBalance F theta N k bias scale I z u := by
  let w : ι → ℝ := fun i => driveInsertionCoeff k bias scale u i + driveRemovalCoeff k bias scale u i
  have shared_w : ∀ i j, group i = group j → w i = w j := by
    intro i j hg
    dsimp [w, driveInsertionCoeff, driveRemovalCoeff]
    rw [shared_k i, shared_k j, shared_bias i, shared_bias j, hg]
  have equal_readout := class_readout_sufficient_of_shared_coefficients N group w shared_w
    x z hx hz same_class_amounts
  have zero_difference : (∑ i, N i * w i * (x i - z i)) = 0 := by
    have identity : (∑ i, N i * w i * (x i - z i)) =
        weightedReadout N w x - weightedReadout N w z := by
      simp [weightedReadout, mul_sub, Finset.sum_sub_distrib]
    rw [identity, equal_readout, sub_self]
  apply sub_eq_zero.mp
  rw [fixed_current_occupation_residual_identity]
  change F * theta * (∑ i, N i * w i * (x i - z i)) = 0
  rw [zero_difference, mul_zero]

section PositiveDrive
variable [Nonempty ι]

/- The needed drive monotonicity is derived from actual coefficients and
   occupations everywhere, rather than assumed as a slope-floor certificate. -/
theorem positive_physical_drive_slope
    (F theta : ℝ) (N k bias : ι → ℝ) (scale : ℝ) (z : ι → ℝ)
    (hF : 0 < F) (htheta : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i) (hz : PhysicalOccupation z) (u : ℝ) :
    0 < driveSlopeMagnitude F theta N k bias scale z u := by
  have hterm : ∀ i, 0 < N i * (driveRemovalCoeff k bias scale u i * z i +
      driveInsertionCoeff k bias scale u i * (1 - z i)) := by
    intro i
    have hA : 0 < driveInsertionCoeff k bias scale u i := mul_pos (hk i) (Real.exp_pos _)
    have hB : 0 < driveRemovalCoeff k bias scale u i := mul_pos (hk i) (Real.exp_pos _)
    apply mul_pos (hN i)
    by_cases zero_occupation : z i = 0
    · simpa [zero_occupation] using hA
    · have hzpos : 0 < z i := lt_of_le_of_ne (hz i).1 (Ne.symm zero_occupation)
      exact add_pos_of_pos_of_nonneg (mul_pos hB hzpos)
        (mul_nonneg (le_of_lt hA) (sub_nonneg.mpr (hz i).2))
  exact mul_pos (div_pos (mul_pos hF htheta) hscale)
    (Finset.sum_pos (fun i _ => hterm i) Finset.univ_nonempty)

theorem positive_fixed_current_balance_strictAnti
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ) (z : ι → ℝ)
    (hF : 0 < F) (htheta : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i) (hz : PhysicalOccupation z) :
    StrictAnti (fixedCurrentDriveBalance F theta N k bias scale I z) := by
  exact strictAnti_of_hasDerivAt_neg
    (fun u => fixed_current_balance_hasDerivAt F theta N k bias scale I z u hscale)
    (fun u => neg_neg_of_pos (positive_physical_drive_slope F theta N k bias scale z
      hF htheta hscale hN hk hz u))

theorem same_class_state_exact_current_roots_equal
    (F theta : ℝ) (N k bias : ι → ℝ) (scale I : ℝ)
    (group : ι → κ) (kClass biasClass : κ → ℝ)
    (shared_k : ∀ i, k i = kClass (group i))
    (shared_bias : ∀ i, bias i = biasClass (group i))
    (x z : ι → ℝ) (hx : PhysicalOccupation x) (hz : PhysicalOccupation z)
    (same_class_amounts : ∀ j, classAmount N group x j = classAmount N group z j)
    (hF : 0 < F) (htheta : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i) (ux uz : ℝ)
    (root_x : fixedCurrentDriveBalance F theta N k bias scale I x ux = 0)
    (root_z : fixedCurrentDriveBalance F theta N k bias scale I z uz = 0) : ux = uz := by
  have same_balance := same_class_state_preserves_fixed_current_balance F theta N k bias scale I
    group kClass biasClass shared_k shared_bias x z hx hz same_class_amounts ux
  apply (positive_fixed_current_balance_strictAnti F theta N k bias scale I z
    hF htheta hscale hN hk hz).injective
  exact same_balance.symm.trans (root_x.trans root_z.symm)

theorem same_class_state_preserves_exact_current_chemical_outputs
    (F theta V0 resistance : ℝ) (N k bias cBase : ι → ℝ) (scale I : ℝ)
    (group : ι → κ) (kClass biasClass cClass : κ → ℝ)
    (shared_k : ∀ i, k i = kClass (group i))
    (shared_bias : ∀ i, bias i = biasClass (group i))
    (shared_c : ∀ i, cBase i = cClass (group i))
    (x z : ι → ℝ) (hx : PhysicalOccupation x) (hz : PhysicalOccupation z)
    (same_class_amounts : ∀ j, classAmount N group x j = classAmount N group z j)
    (hF : 0 < F) (htheta : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i) (_hc : ∀ i, 0 ≤ cBase i)
    (ux uz : ℝ)
    (root_x : fixedCurrentDriveBalance F theta N k bias scale I x ux = 0)
    (root_z : fixedCurrentDriveBalance F theta N k bias scale I z uz = 0) :
    fixedCurrentVoltage V0 resistance I ux = fixedCurrentVoltage V0 resistance I uz ∧
    detailedAmountRate N (fun i => theta * driveInsertionCoeff k bias scale ux i)
      (fun i => theta * driveRemovalCoeff k bias scale ux i) (fun i => theta * cBase i) x =
    detailedAmountRate N (fun i => theta * driveInsertionCoeff k bias scale uz i)
      (fun i => theta * driveRemovalCoeff k bias scale uz i) (fun i => theta * cBase i) z ∧
    trappedRate N (fun i => theta * cBase i) x = trappedRate N (fun i => theta * cBase i) z := by
  have drives_equal := same_class_state_exact_current_roots_equal F theta N k bias scale I
    group kClass biasClass shared_k shared_bias x z hx hz same_class_amounts
    hF htheta hscale hN hk ux uz root_x root_z
  subst uz
  refine ⟨rfl, ?_⟩
  have shared : ∀ i j, group i = group j →
      (theta * driveInsertionCoeff k bias scale ux i + theta * driveRemovalCoeff k bias scale ux i + theta * cBase i =
        theta * driveInsertionCoeff k bias scale ux j + theta * driveRemovalCoeff k bias scale ux j + theta * cBase j) ∧
      theta * cBase i = theta * cBase j := by
    intro i j hg
    simp [driveInsertionCoeff, driveRemovalCoeff, shared_k, shared_bias, shared_c, hg]
  exact ((class_rhs_trapping_sufficient_iff N hN group _ _ _).2 shared)
    x z hx hz same_class_amounts

end PositiveDrive

/- Dropping strict positive reaction capability leaves a flat balance. This
   is an exact degenerate theory counterexample, not a permitted cell action. -/
theorem zero_reversible_rates_destroy_drive_uniqueness :
    (∀ u : ℝ, fixedCurrentDriveBalance 1 1 (fun _ : Fin 1 => 1)
      (fun _ => 0) (fun _ => 0) 1 0 (fun _ => (1/2 : ℝ)) u = 0) ∧
    fixedCurrentVoltage 0 0 0 (-1) ≠ fixedCurrentVoltage 0 0 0 1 := by
  constructor
  · intro u
    simp [fixedCurrentDriveBalance, driveInsertionCoeff, driveRemovalCoeff]
  · norm_num [fixedCurrentVoltage]

end Naheng.Reduction
#print Naheng.Reduction.same_class_state_preserves_fixed_current_balance
#print axioms Naheng.Reduction.same_class_state_preserves_fixed_current_balance
#print Naheng.Reduction.positive_physical_drive_slope
#print axioms Naheng.Reduction.positive_physical_drive_slope
#print Naheng.Reduction.positive_fixed_current_balance_strictAnti
#print axioms Naheng.Reduction.positive_fixed_current_balance_strictAnti
#print Naheng.Reduction.same_class_state_exact_current_roots_equal
#print axioms Naheng.Reduction.same_class_state_exact_current_roots_equal
#print Naheng.Reduction.same_class_state_preserves_exact_current_chemical_outputs
#print axioms Naheng.Reduction.same_class_state_preserves_exact_current_chemical_outputs
#print Naheng.Reduction.zero_reversible_rates_destroy_drive_uniqueness
#print axioms Naheng.Reduction.zero_reversible_rates_destroy_drive_uniqueness
