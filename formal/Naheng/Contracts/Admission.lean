import Naheng.Contracts.Output

/- Finite operating-distribution contract with declared normalized weights.
   The probability of the joint primitive certification event is an independent
   obligation, never inferred from posterior particles or sampled quantiles.
   No independence assumption is used. Standard margin/union facts are linked
   here to the actual derived exponential-rate voltage budget. -/
set_option pp.proofs false
namespace Naheng.Contracts
open Set Naheng.Reduction
open scoped BigOperators
variable {ι Ω : Type*} [Fintype ι] [Nonempty ι] [Fintype Ω]

noncomputable def finiteEventMass (p : Ω → ℝ) (event : Ω → Prop) : ℝ :=
  by classical exact ∑ w, p w * (if event w then 1 else 0)

theorem voltage_upper_admission_from_primitive_occupation
    (F theta V0 R I : ℝ) (N k bias delta x z : ι → ℝ)
    (scale L U ux uz eta_x eta_z vmax : ℝ)
    (hF : 0 < F) (hth : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i)
    (hz : ∀ i, z i ∈ Icc 0 1) (hd : ∀ i, |x i-z i| ≤ delta i)
    (hux : ux ∈ Icc L U) (huz : uz ∈ Icc L U)
    (hrootx : |fixedCurrentDriveBalance F theta N k bias scale I x ux| ≤ eta_x)
    (hrootz : |fixedCurrentDriveBalance F theta N k bias scale I z uz| ≤ eta_z)
    (hadmit : fixedCurrentVoltage V0 R I uz+
      (primitiveDriveBudget F theta N k bias delta scale L U+eta_x+eta_z) /
      primitiveSlopeFloor F theta N k bias scale L U ≤ vmax) :
    fixedCurrentVoltage V0 R I ux ≤ vmax := by
  have h := voltage_error_from_primitive_occupation F theta V0 R I N k bias delta x z
    scale L U ux uz eta_x eta_z hF hth hscale hN hk hz hd hux huz hrootx hrootz
  have hh := le_abs_self (fixedCurrentVoltage V0 R I ux-fixedCurrentVoltage V0 R I uz)
  linarith only [h,hh,hadmit]

theorem finite_joint_certification_union_bound
    (p : Ω → ℝ) (V Veff : Ω → ℝ) (E : Ω → Prop) (eps vmax delta : ℝ)
    (hp : ∀ w, 0 ≤ p w) (_normalized : ∑ w, p w = 1)
    (herror : ∀ w, E w → |V w-Veff w| ≤ eps)
    (hfailure : finiteEventMass p (fun w => ¬E w) ≤ delta) :
    finiteEventMass p (fun w => vmax < V w) ≤
      finiteEventMass p (fun w => vmax-eps < Veff w)+delta := by
  classical
  have pointwise : ∀ w, p w*(if vmax < V w then 1 else 0) ≤
      p w*(if vmax-eps < Veff w then 1 else 0)+p w*(if ¬E w then 1 else 0) := by
    intro w
    by_cases he : E w
    · by_cases hv : vmax < V w
      · have hb := herror w he
        have hh := le_abs_self (V w-Veff w)
        have hve : vmax-eps < Veff w := by linarith only [hv,hb,hh]
        simp [he,hv,hve]
      · by_cases hve : vmax-eps < Veff w <;> simp [he,hv,hve,hp w]
    · by_cases hv : vmax < V w <;> by_cases hve : vmax-eps < Veff w <;>
        simp [he,hv,hve,hp w]
  have hs := Finset.sum_le_sum (fun w (_ : w ∈ Finset.univ) => pointwise w)
  simp only [Finset.sum_add_distrib] at hs
  have hsum : finiteEventMass p (fun w => vmax < V w) ≤
      finiteEventMass p (fun w => vmax-eps < Veff w)+finiteEventMass p (fun w => ¬E w) := by
    simpa [finiteEventMass] using hs
  exact hsum.trans (add_le_add_left hfailure _)

/- The finite probability lemma is instantiated by the chemically derived
   budget inside E, rather than by assuming the desired readout-error bound. -/
theorem finite_voltage_risk_from_primitive_occupation
    (p : Ω → ℝ) (E : Ω → Prop) (x z : Ω → ι → ℝ) (ux uz : Ω → ℝ)
    (F theta V0 R I : ℝ) (N k bias deltaState : ι → ℝ)
    (scale L U eta_x eta_z vmax deltaRisk : ℝ)
    (hp : ∀ w, 0 ≤ p w) (hnorm : ∑ w, p w=1)
    (hF : 0 < F) (hth : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i)
    (hz : ∀ w, E w → ∀ i, z w i ∈ Icc 0 1)
    (hd : ∀ w, E w → ∀ i, |x w i-z w i| ≤ deltaState i)
    (hux : ∀ w, E w → ux w ∈ Icc L U) (huz : ∀ w, E w → uz w ∈ Icc L U)
    (hrootx : ∀ w, E w → |fixedCurrentDriveBalance F theta N k bias scale I (x w) (ux w)| ≤ eta_x)
    (hrootz : ∀ w, E w → |fixedCurrentDriveBalance F theta N k bias scale I (z w) (uz w)| ≤ eta_z)
    (hfailure : finiteEventMass p (fun w => ¬E w) ≤ deltaRisk) :
    finiteEventMass p (fun w => vmax < fixedCurrentVoltage V0 R I (ux w)) ≤
      finiteEventMass p (fun w => vmax-
        (primitiveDriveBudget F theta N k bias deltaState scale L U+eta_x+eta_z) /
        primitiveSlopeFloor F theta N k bias scale L U < fixedCurrentVoltage V0 R I (uz w))+deltaRisk := by
  apply finite_joint_certification_union_bound p
    (fun w => fixedCurrentVoltage V0 R I (ux w)) (fun w => fixedCurrentVoltage V0 R I (uz w)) E
    ((primitiveDriveBudget F theta N k bias deltaState scale L U+eta_x+eta_z) /
      primitiveSlopeFloor F theta N k bias scale L U) vmax deltaRisk hp hnorm _ hfailure
  intro w he
  exact voltage_error_from_primitive_occupation F theta V0 R I N k bias deltaState (x w) (z w)
    scale L U (ux w) (uz w) eta_x eta_z hF hth hscale hN hk
    (hz w he) (hd w he) (hux w he) (huz w he) (hrootx w he) (hrootz w he)

theorem sampled_event_alone_cannot_certify_operating_mass :
    ∃ (p : Bool → ℝ) (E : Bool → Prop),
      (∀ w, 0 ≤ p w) ∧ (∑ w, p w)=1 ∧ E false ∧
      finiteEventMass p (fun w => ¬E w)=(1/2 : ℝ) := by
  refine ⟨(fun _ => 1/2),(fun w => w=false),?_,?_,?_,?_⟩
  · intro w; norm_num
  · norm_num [Fintype.sum_bool]
  · rfl
  · norm_num [finiteEventMass,Fintype.sum_bool]

/- Generic smooth-readout counterexample: endpoints do not certify intervening
   voltages. It is not asserted to be a fitted SiteModel cell trajectory. -/
theorem endpoint_samples_do_not_certify_voltage_between_samples :
    ∃ V : ℝ → ℝ, V 0=0 ∧ V 1=0 ∧ (1/2 : ℝ)<V (1/2) ∧
      (∀ t, HasDerivAt V (4-8*t) t) := by
  refine ⟨(fun t => 4*t*(1-t)),by norm_num,by norm_num,by norm_num,?_⟩
  intro t
  convert ((hasDerivAt_id t).const_mul 4).mul ((hasDerivAt_const t (1 : ℝ)).sub (hasDerivAt_id t)) using 1 <;> dsimp only [id] <;> ring

/- Exact adapter roots at identical occupation with different currents. State
   equality alone cannot extend a same-input readout theorem to changed-input
   closed loops; actual controller/input mismatch needs a separate bound. -/
theorem different_current_invalidates_zero_state_error_readout_claim :
    ∃ (x : Unit → ℝ) (I2 : ℝ),
      (∀ i, x i∈Icc 0 1) ∧
      fixedCurrentDriveBalance 1 1 (fun _ => 1) (fun _ => 1) (fun _ => 0) 1 0 x 0=0 ∧
      fixedCurrentDriveBalance 1 1 (fun _ => 1) (fun _ => 1) (fun _ => 0) 1 I2 x 1=0 ∧
      fixedCurrentVoltage 0 0 0 0 < fixedCurrentVoltage 0 0 I2 1 := by
  refine ⟨(fun _ => 1/2),(Real.exp (-1)-Real.exp 1)/2,?_,?_,?_,?_⟩
  · intro i; norm_num
  · norm_num [fixedCurrentDriveBalance,driveInsertionCoeff,driveRemovalCoeff]
  · norm_num [fixedCurrentDriveBalance,driveInsertionCoeff,driveRemovalCoeff]
    ring
  · norm_num [fixedCurrentVoltage]

end Naheng.Contracts
#print Naheng.Contracts.voltage_upper_admission_from_primitive_occupation
#print axioms Naheng.Contracts.voltage_upper_admission_from_primitive_occupation
#print Naheng.Contracts.finite_joint_certification_union_bound
#print axioms Naheng.Contracts.finite_joint_certification_union_bound
#print Naheng.Contracts.finite_voltage_risk_from_primitive_occupation
#print axioms Naheng.Contracts.finite_voltage_risk_from_primitive_occupation
#print Naheng.Contracts.sampled_event_alone_cannot_certify_operating_mass
#print axioms Naheng.Contracts.sampled_event_alone_cannot_certify_operating_mass
#print Naheng.Contracts.endpoint_samples_do_not_certify_voltage_between_samples
#print axioms Naheng.Contracts.endpoint_samples_do_not_certify_voltage_between_samples
#print Naheng.Contracts.different_current_invalidates_zero_state_error_readout_claim
#print axioms Naheng.Contracts.different_current_invalidates_zero_state_error_readout_claim
