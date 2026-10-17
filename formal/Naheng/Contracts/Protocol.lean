import Naheng.Contracts.Output
import Naheng.Aging.Completion

/- Compose primitive occupation/rate/root obligations with the successful
   constant-current protocol and actual age-capacity first-retirement theorem.
   No desired voltage, capacity or lifetime error is assumed. Whole protocol
   derivative floors and age-capacity decay/sign brackets remain substantive
   prerequisites; competing stops/censoring do not establish successful probes. -/
set_option pp.proofs false
namespace Naheng.Contracts
open Set Naheng.Reduction Naheng.Aging Naheng.Aging.Completion
variable {ι : Type*} [Fintype ι] [Nonempty ι]

theorem primitive_state_to_actual_first_retirement_contract
    (F theta V0 R I : ℝ) (N k bias delta : ι → ℝ)
    (x z : ℝ → ℝ → ι → ℝ) (ux uz dV : ℝ → ℝ → ℝ)
    (duration durationEff dC dCeff : ℝ → ℝ)
    (scale L U eta_x eta_z cutoff retirement m s seff H A : ℝ)
    (hF : 0 < F) (hth : 0 < theta) (hscale : 0 < scale)
    (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i)
    (hI : 0 < I) (hm : 0 < m) (hs : 0 < s) (hseff : 0 < seff) (hA : 0 ≤ A)
    (hz : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H, ∀ i, z age t i ∈ Icc 0 1)
    (hd : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H, ∀ i, |x age t i-z age t i| ≤ delta i)
    (hux : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H, ux age t ∈ Icc L U)
    (huz : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H, uz age t ∈ Icc L U)
    (hrootx : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H,
      |fixedCurrentDriveBalance F theta N k bias scale I (x age t) (ux age t)| ≤ eta_x)
    (hrootz : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H,
      |fixedCurrentDriveBalance F theta N k bias scale I (z age t) (uz age t)| ≤ eta_z)
    (hprotocol : ∀ age ∈ Icc 0 A, duration age ∈ Icc 0 H ∧
      FirstVoltageCutoff (fun t => fixedCurrentVoltage V0 R I (ux age t)) cutoff (duration age) ∧
      fixedCurrentVoltage V0 R I (ux age (duration age)) = cutoff)
    (heprotocol : ∀ age ∈ Icc 0 A, durationEff age ∈ Icc 0 H ∧
      FirstVoltageCutoff (fun t => fixedCurrentVoltage V0 R I (uz age t)) cutoff (durationEff age) ∧
      fixedCurrentVoltage V0 R I (uz age (durationEff age)) = cutoff)
    (hvode : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H, HasDerivAt (ux age) (dV age t) t)
    (hvbound : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H, dV age t ≤ -m)
    (hc : ContinuousOn (fun age => I*duration age) (Icc 0 A))
    (hec : ContinuousOn (fun age => I*durationEff age) (Icc 0 A))
    (hcde : ∀ age ∈ Icc 0 A, HasDerivAt (fun a => I*duration a) (dC age) age)
    (hecde : ∀ age ∈ Icc 0 A, HasDerivAt (fun a => I*durationEff a) (dCeff age) age)
    (hcdecay : ∀ age ∈ Icc 0 A, dC age ≤ -s)
    (hecdecay : ∀ age ∈ Icc 0 A, dCeff age ≤ -seff)
    (hcstart : retirement < I*duration 0) (hecstart : retirement < I*durationEff 0)
    (hcend : I*duration A ≤ retirement) (hecend : I*durationEff A ≤ retirement) :
    ∃ tau ∈ Icc 0 A, ∃ taueff ∈ Icc 0 A,
      RetirementEndpoint (fun age => I*duration age) retirement tau ∧
      RetirementEndpoint (fun age => I*durationEff age) retirement taueff ∧
      |tau-taueff| ≤
        (I*((primitiveDriveBudget F theta N k bias delta scale L U+eta_x+eta_z) /
          primitiveSlopeFloor F theta N k bias scale L U)/m)/s := by
  let eps := (primitiveDriveBudget F theta N k bias delta scale L U+eta_x+eta_z) /
    primitiveSlopeFloor F theta N k bias scale L U
  have hVerror : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H,
      |fixedCurrentVoltage V0 R I (ux age t)-fixedCurrentVoltage V0 R I (uz age t)| ≤ eps := by
    intro age ha t ht
    exact voltage_error_from_primitive_occupation F theta V0 R I N k bias delta (x age t) (z age t)
      scale L U (ux age t) (uz age t) eta_x eta_z hF hth hscale hN hk
      (hz age ha t ht) (hd age ha t ht) (hux age ha t ht) (huz age ha t ht)
      (hrootx age ha t ht) (hrootz age ha t ht)
  have hVoltageODE : ∀ age ∈ Icc 0 A, ∀ t ∈ Icc 0 H,
      HasDerivAt (fun v => fixedCurrentVoltage V0 R I (ux age v)) (dV age t) t := by
    intro age ha t ht
    simpa only [fixedCurrentVoltage] using ((hvode age ha t ht).const_add V0).sub_const (I*R)
  exact voltage_protocol_to_actual_first_retirement_error
    (fun age t => fixedCurrentVoltage V0 R I (ux age t))
    (fun age t => fixedCurrentVoltage V0 R I (uz age t)) dV duration durationEff dC dCeff
    I cutoff retirement eps m s seff H A hI hm hs hseff hA hprotocol heprotocol
    hVoltageODE hvbound hVerror hc hec hcde hecde hcdecay hecdecay hcstart hecstart hcend hecend

end Naheng.Contracts
#print Naheng.Contracts.primitive_state_to_actual_first_retirement_contract
#print axioms Naheng.Contracts.primitive_state_to_actual_first_retirement_contract
