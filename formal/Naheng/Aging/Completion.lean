import Naheng.Aging.Film
import Naheng.Aging.CapacityEndpoint
import Mathlib.Topology.Order.IntermediateValue
import Mathlib.Tactic.FieldSimp

/- Conditional T2 additions. No numerical event is asserted to be a certified
   first hit, and no SiteModel voltage/age slope certificate is assumed valid.
   Constants describe one declared reaction/transport and capacity protocol.
   Variable coefficients retain their derivative correction. -/
namespace Naheng.Aging.Completion
open Set

theorem reaction_dominated_rate_error
    (D k F l delta : ℝ) (hD : 0 < D) (hk : 0 < k)
    (hF : 0 ≤ F) (hl : 0 ≤ l) (hsmall : k * l / D ≤ delta) :
    0 ≤ F * k - filmRate D k F 1 l ∧
      F * k - filmRate D k F 1 l ≤ delta * (F * k) := by
  have hden : 0 < 1 / k + l / D := film_denominator_positive D k l hD hk hl
  have hrewrite : filmRate D k F 1 l = F * k / (1 + k * l / D) := by
    dsimp [filmRate]
    field_simp [ne_of_gt hD, ne_of_gt hk, ne_of_gt hden]
    <;> ring
  have hratio : 0 ≤ k * l / D := div_nonneg (mul_nonneg hk.le hl) hD.le
  have hpos : 0 < 1 + k * l / D := by linarith
  rw [hrewrite]
  have hid : F * k - F * k / (1 + k * l / D) =
      (F * k * (k * l / D)) / (1 + k * l / D) := by
    field_simp [ne_of_gt hpos]
    <;> ring
  rw [hid]
  constructor
  · exact div_nonneg (mul_nonneg (mul_nonneg hF hk.le) hratio) hpos.le
  · have hbound : F * k * (k * l / D) ≤ delta * (F * k) := by
      nlinarith [mul_le_mul_of_nonneg_left hsmall (mul_nonneg hF hk.le)]
    have hdiv : (F * k * (k * l / D)) / (1 + k * l / D) ≤ F * k * (k * l / D) := by
      apply (div_le_iff₀ hpos).2
      nlinarith [mul_nonneg (mul_nonneg hF hk.le) (sq_nonneg (k * l / D))]
    exact le_trans hdiv hbound

/- A real variable-coefficient solution on a nonempty interval. D=F=1,
   k(t)=1/(1-t), l(t)=t satisfy the declared ODE, yet the origin-frozen
   primitive at t=1/2 is 5/8, not t=1/2. No numerical sample is used. -/
theorem positive_variable_film_counterexample :
    (∀ t ∈ Icc (0 : ℝ) (1/2), 0 < 1 / (1-t) ∧
      HasDerivAt (fun u : ℝ => u) (filmRate 1 (1/(1-t)) 1 1 t) t) ∧
    filmPrimitive 1 1 (1/2) - filmPrimitive 1 1 0 ≠ (1/2 : ℝ) := by
  constructor
  · intro t ht
    have htpos : 0 < 1-t := by linarith [ht.2]
    constructor
    · exact one_div_pos.mpr htpos
    · have hrate : filmRate 1 (1/(1-t)) 1 1 t = 1 := by
        simp only [filmRate, one_div_one_div, div_one, mul_one]
        have hden : 1 - t + t = 1 := by ring
        rw [hden]
        norm_num
      rw [hrate]
      exact hasDerivAt_id t
  · norm_num [filmPrimitive]

/- Unlike prior endpoint-only results, existence, equality and the strict
   pre-threshold property are derived from continuity, sign bracket and a
   derivative condition. There is no assumed retirement time or RUL bound. -/
theorem first_retirement_from_signs_and_derivative
    (C d : ℝ → ℝ) (theta s T : ℝ) (hs : 0 < s) (hT : 0 ≤ T)
    (hcontinuous : ContinuousOn C (Icc 0 T))
    (hode : ∀ t ∈ Icc 0 T, HasDerivAt C (d t) t)
    (hbound : ∀ t ∈ Icc 0 T, d t ≤ -s)
    (hstart : theta < C 0) (hend : C T ≤ theta) :
    ∃ tau ∈ Icc 0 T, 0 < tau ∧ C tau = theta ∧ RetirementEndpoint C theta tau := by
  obtain ⟨tau, htau, hvalue⟩ := (intermediate_value_Icc' hT hcontinuous) ⟨hend, hstart.le⟩
  have hpositive : 0 < tau := by
    by_contra h
    have hz : tau = 0 := le_antisymm (le_of_not_gt h) htau.1
    rw [hz] at hvalue
    linarith
  refine ⟨tau, htau, hpositive, hvalue, htau.1, hvalue.le, ?_⟩
  intro t ht hlt
  have htmem : t ∈ Icc 0 T := ⟨ht, le_trans hlt.le htau.2⟩
  have hsecant := decreasing_capacity_secant_of_derivative C d s T hode hbound t htmem tau htau hlt.le
  have hgap : 0 < s * (tau - t) := mul_pos hs (sub_pos.mpr hlt)
  rw [hvalue] at hsecant
  linarith

theorem first_voltage_cutoff_from_signs_and_derivative
    (V d : ℝ → ℝ) (cutoff m H : ℝ) (hm : 0 < m) (hH : 0 ≤ H)
    (hcontinuous : ContinuousOn V (Icc 0 H))
    (hode : ∀ t ∈ Icc 0 H, HasDerivAt V (d t) t)
    (hbound : ∀ t ∈ Icc 0 H, d t ≤ -m)
    (hstart : cutoff < V 0) (hend : V H ≤ cutoff) :
    ∃ tau ∈ Icc 0 H, 0 < tau ∧ V tau = cutoff ∧ FirstVoltageCutoff V cutoff tau := by
  simpa only [FirstVoltageCutoff, RetirementEndpoint] using
    first_retirement_from_signs_and_derivative V d cutoff m H hm hH hcontinuous hode hbound hstart hend

/- Capacity is charge integrated at the same I>0 through a successful first
   voltage cutoff, not the occupied sodium inventory. This quantitative bound
   is derived from voltage error and true whole-protocol decay, not assumed as
   an equality between inventory and capacity. -/
theorem actual_protocol_capacity_error_from_voltage_error
    (V Veff d : ℝ → ℝ) (I cutoff tau taueff eps m H : ℝ)
    (hI : 0 < I) (hm : 0 < m)
    (htau : tau ∈ Icc 0 H) (htaueff : taueff ∈ Icc 0 H)
    (hode : ∀ t ∈ Icc 0 H, HasDerivAt V (d t) t)
    (hbound : ∀ t ∈ Icc 0 H, d t ≤ -m)
    (htrue : V tau = cutoff) (heff : Veff taueff = cutoff)
    (herror : |V taueff - Veff taueff| ≤ eps) :
    |I * tau - I * taueff| ≤ I * eps / m := by
  have htime := endpoint_time_error_from_derivative V Veff d cutoff tau taueff eps m H hm htau htaueff hode hbound htrue heff herror
  have hcharge : |I * tau - I * taueff| = I * |tau - taueff| := by
    rw [← mul_sub, abs_mul, abs_of_pos hI]
  rw [hcharge]
  simpa only [mul_div_assoc] using mul_le_mul_of_nonneg_left htime hI.le

theorem successful_protocols_exist_and_capacity_error
    (V Veff d deff : ℝ → ℝ) (I cutoff eps m meff H : ℝ)
    (hI : 0 < I) (hm : 0 < m) (hmeff : 0 < meff) (hH : 0 ≤ H)
    (hcontinuity : ContinuousOn V (Icc 0 H)) (hecontinuity : ContinuousOn Veff (Icc 0 H))
    (hode : ∀ t ∈ Icc 0 H, HasDerivAt V (d t) t)
    (heode : ∀ t ∈ Icc 0 H, HasDerivAt Veff (deff t) t)
    (hbound : ∀ t ∈ Icc 0 H, d t ≤ -m)
    (hebound : ∀ t ∈ Icc 0 H, deff t ≤ -meff)
    (hstart : cutoff < V 0) (heStart : cutoff < Veff 0)
    (hend : V H ≤ cutoff) (heEnd : Veff H ≤ cutoff)
    (herror : ∀ t ∈ Icc 0 H, |V t - Veff t| ≤ eps) :
    ∃ tau ∈ Icc 0 H, ∃ taueff ∈ Icc 0 H,
      FirstVoltageCutoff V cutoff tau ∧ FirstVoltageCutoff Veff cutoff taueff ∧
        |I * tau - I * taueff| ≤ I * eps / m := by
  obtain ⟨tau, htau, _, htrue, hfirst⟩ := first_voltage_cutoff_from_signs_and_derivative V d cutoff m H hm hH hcontinuity hode hbound hstart hend
  obtain ⟨taueff, htaueff, _, heff, hefirst⟩ := first_voltage_cutoff_from_signs_and_derivative Veff deff cutoff meff H hmeff hH hecontinuity heode hebound heStart heEnd
  exact ⟨tau, htau, taueff, htaueff, hfirst, hefirst,
    actual_protocol_capacity_error_from_voltage_error V Veff d I cutoff tau taueff eps m H hI hm htau htaueff hode hbound htrue heff (herror taueff htaueff)⟩

/- The two inverse steps compose only when age-capacity really has a positive
   decay floor and a finite sign bracket. Those are separate model certificates;
   a flat curve or an unobserved crossing cannot satisfy this theorem's gates. -/
theorem actual_first_retirement_error_from_protocol_capacity_error
    (C Ceff d deff : ℝ → ℝ) (theta I eps m s seff A : ℝ)
    (hs : 0 < s) (hseff : 0 < seff) (hA : 0 ≤ A)
    (hcontinuity : ContinuousOn C (Icc 0 A)) (hecontinuity : ContinuousOn Ceff (Icc 0 A))
    (hode : ∀ t ∈ Icc 0 A, HasDerivAt C (d t) t)
    (heode : ∀ t ∈ Icc 0 A, HasDerivAt Ceff (deff t) t)
    (hbound : ∀ t ∈ Icc 0 A, d t ≤ -s)
    (hebound : ∀ t ∈ Icc 0 A, deff t ≤ -seff)
    (hstart : theta < C 0) (heStart : theta < Ceff 0)
    (hend : C A ≤ theta) (heEnd : Ceff A ≤ theta)
    (hprotocolError : ∀ t ∈ Icc 0 A, |C t - Ceff t| ≤ I * eps / m) :
    ∃ tau ∈ Icc 0 A, ∃ taueff ∈ Icc 0 A,
      RetirementEndpoint C theta tau ∧ RetirementEndpoint Ceff theta taueff ∧
        |tau - taueff| ≤ (I * eps / m) / s := by
  obtain ⟨tau, htau, _, htrue, hfirst⟩ := first_retirement_from_signs_and_derivative C d theta s A hs hA hcontinuity hode hbound hstart hend
  obtain ⟨taueff, htaueff, _, heff, hefirst⟩ := first_retirement_from_signs_and_derivative Ceff deff theta seff A hseff hA hecontinuity heode hebound heStart heEnd
  exact ⟨tau, htau, taueff, htaueff, hfirst, hefirst,
    endpoint_time_error_from_derivative C Ceff d theta tau taueff (I * eps / m) s A hs htau htaueff hode hbound htrue heff (hprotocolError taueff htaueff)⟩

end Naheng.Aging.Completion

namespace Naheng.Aging.Completion
open Set

/- This final composition derives the age-capacity error from protocol voltage
   error. It does not take capacity closeness or the desired RUL bound as an
   assumption. The successful first cutoff records are actual protocol facts;
   voltage and age derivative/error certificates are distinct prerequisites. -/
theorem voltage_protocol_to_actual_first_retirement_error
    (V Veff dV : ℝ → ℝ → ℝ) (duration durationEff dC dCeff : ℝ → ℝ)
    (I cutoff theta eps m s seff H A : ℝ)
    (hI : 0 < I) (hm : 0 < m) (hs : 0 < s) (hseff : 0 < seff) (hA : 0 ≤ A)
    (hprotocol : ∀ age ∈ Icc 0 A, duration age ∈ Icc 0 H ∧
      FirstVoltageCutoff (V age) cutoff (duration age) ∧ V age (duration age) = cutoff)
    (heprotocol : ∀ age ∈ Icc 0 A, durationEff age ∈ Icc 0 H ∧
      FirstVoltageCutoff (Veff age) cutoff (durationEff age) ∧ Veff age (durationEff age) = cutoff)
    (hvode : ∀ age ∈ Icc 0 A, ∀ elapsed ∈ Icc 0 H,
      HasDerivAt (V age) (dV age elapsed) elapsed)
    (hvbound : ∀ age ∈ Icc 0 A, ∀ elapsed ∈ Icc 0 H, dV age elapsed ≤ -m)
    (hverror : ∀ age ∈ Icc 0 A, ∀ elapsed ∈ Icc 0 H,
      |V age elapsed - Veff age elapsed| ≤ eps)
    (hcontinuous : ContinuousOn (fun age => I * duration age) (Icc 0 A))
    (hecontinuous : ContinuousOn (fun age => I * durationEff age) (Icc 0 A))
    (hode : ∀ age ∈ Icc 0 A, HasDerivAt (fun a => I * duration a) (dC age) age)
    (heode : ∀ age ∈ Icc 0 A, HasDerivAt (fun a => I * durationEff a) (dCeff age) age)
    (hbound : ∀ age ∈ Icc 0 A, dC age ≤ -s)
    (hebound : ∀ age ∈ Icc 0 A, dCeff age ≤ -seff)
    (hstart : theta < I * duration 0) (heStart : theta < I * durationEff 0)
    (hend : I * duration A ≤ theta) (heEnd : I * durationEff A ≤ theta) :
    ∃ tau ∈ Icc 0 A, ∃ taueff ∈ Icc 0 A,
      RetirementEndpoint (fun age => I * duration age) theta tau ∧
      RetirementEndpoint (fun age => I * durationEff age) theta taueff ∧
      |tau - taueff| ≤ (I * eps / m) / s := by
  have hcapacity : ∀ age ∈ Icc 0 A,
      |I * duration age - I * durationEff age| ≤ I * eps / m := by
    intro age hage
    have actual := hprotocol age hage
    have effective := heprotocol age hage
    exact actual_protocol_capacity_error_from_voltage_error (V age) (Veff age) (dV age)
      I cutoff (duration age) (durationEff age) eps m H hI hm actual.1 effective.1
      (hvode age hage) (hvbound age hage) actual.2.2 effective.2.2
      (hverror age hage (durationEff age) effective.1)
  exact actual_first_retirement_error_from_protocol_capacity_error
    (fun age => I * duration age) (fun age => I * durationEff age) dC dCeff
    theta I eps m s seff A hs hseff hA hcontinuous hecontinuous hode heode hbound hebound
    hstart heStart hend heEnd hcapacity

end Naheng.Aging.Completion
