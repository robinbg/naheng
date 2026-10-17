import Mathlib.Analysis.SpecialFunctions.Log.Deriv
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring

/- Isothermal ideal reversible site, with fixed positive rate constants and
   energy scale. This is a chemical-potential port supply inequality, not a
   certificate for SiteModel's side reactions or nonisothermal thermal RHS.
   The ODE solution and its strict interior domain are explicit conditions;
   neither differentiability nor the dissipation conclusion is postulated.
   Standard local-detailed-balance formalization, no natural-law novelty. -/
namespace Naheng.Chemistry.Thermodynamics
set_option pp.proofs false

noncomputable def freeEnergy (theta a b x : ℝ) : ℝ :=
  theta * (x * Real.log x + (1 - x) * Real.log (1 - x) + x * Real.log (b / a))

noncomputable def chemicalPotential (theta a b x : ℝ) : ℝ :=
  theta * (Real.log x - Real.log (1 - x) + Real.log (b / a))

def insertionFlux (a x : ℝ) : ℝ := a * (1 - x)
def removalFlux (b x : ℝ) : ℝ := b * x
def reversibleRate (a b x : ℝ) : ℝ := insertionFlux a x - removalFlux b x

theorem positive_site_fluxes (a b x : ℝ) (ha : 0 < a) (hb : 0 < b)
    (hx : 0 < x) (hx1 : x < 1) :
    0 < insertionFlux a x ∧ 0 < removalFlux b x := by
  constructor
  · exact mul_pos ha (sub_pos.mpr hx1)
  · exact mul_pos hb hx

theorem freeEnergy_hasDerivAt (theta a b x : ℝ)
    (hx : 0 < x) (hx1 : x < 1) :
    HasDerivAt (freeEnergy theta a b) (chemicalPotential theta a b x) x := by
  have hxne : x ≠ 0 := ne_of_gt hx
  have h1ne : 1 - x ≠ 0 := ne_of_gt (sub_pos.mpr hx1)
  have hid := hasDerivAt_id x
  have hminus : HasDerivAt (fun y : ℝ => 1 - y) (-1) x := by
    simpa using (hasDerivAt_const x (1 : ℝ)).sub hid
  have hleft := hid.mul (Real.hasDerivAt_log hxne)
  have hright := hminus.mul (hminus.log h1ne)
  have hlinear := hid.mul_const (Real.log (b / a))
  have h := ((hleft.add hright).add hlinear).const_mul theta
  convert h using 1
  dsimp [freeEnergy, chemicalPotential]
  field_simp [hxne, h1ne]
  <;> ring

theorem chemicalPotential_local_detailed_balance (theta a b x : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hx : 0 < x) (hx1 : x < 1) :
    chemicalPotential theta a b x =
      theta * (Real.log (removalFlux b x) - Real.log (insertionFlux a x)) := by
  have h1 : 0 < 1 - x := sub_pos.mpr hx1
  dsimp [chemicalPotential, insertionFlux, removalFlux]
  rw [Real.log_div (ne_of_gt hb) (ne_of_gt ha),
    Real.log_mul (ne_of_gt hb) (ne_of_gt hx),
    Real.log_mul (ne_of_gt ha) (ne_of_gt h1)]
  ring

theorem chemicalPotential_log_flux_ratio (theta a b x : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hx : 0 < x) (hx1 : x < 1) :
    chemicalPotential theta a b x =
      theta * Real.log (removalFlux b x / insertionFlux a x) := by
  have hflux := positive_site_fluxes a b x ha hb hx hx1
  rw [chemicalPotential_local_detailed_balance theta a b x ha hb hx hx1,
    Real.log_div (ne_of_gt hflux.2) (ne_of_gt hflux.1)]

/- The sign is derived solely from strict monotonicity of log on positive
   fluxes. In particular, it is not supplied as an assumed force condition. -/
theorem positive_flux_log_dissipation (A B : ℝ) (hA : 0 < A) (hB : 0 < B) :
    (A - B) * (Real.log B - Real.log A) ≤ 0 := by
  rcases le_total A B with h | h
  · apply mul_nonpos_of_nonpos_of_nonneg (sub_nonpos.mpr h)
    exact sub_nonneg.mpr ((Real.log_le_log_iff hA hB).mpr h)
  · apply mul_nonpos_of_nonneg_of_nonpos (sub_nonneg.mpr h)
    exact sub_nonpos.mpr ((Real.log_le_log_iff hB hA).mpr h)

theorem positive_flux_strict_log_dissipation (A B : ℝ)
    (hA : 0 < A) (hB : 0 < B) (hne : A ≠ B) :
    (A - B) * (Real.log B - Real.log A) < 0 := by
  rcases lt_or_gt_of_ne hne with h | h
  · apply mul_neg_of_neg_of_pos (sub_neg.mpr h)
    exact sub_pos.mpr (Real.log_lt_log hA h)
  · apply mul_neg_of_pos_of_neg (sub_pos.mpr h)
    exact sub_neg.mpr (Real.log_lt_log hB h)

theorem freeEnergy_open_port_dissipation (theta a b x p : ℝ)
    (htheta : 0 < theta) (ha : 0 < a) (hb : 0 < b)
    (hx : 0 < x) (hx1 : x < 1) :
    chemicalPotential theta a b x * (reversibleRate a b x + p) -
      chemicalPotential theta a b x * p ≤ 0 := by
  have hflux := positive_site_fluxes a b x ha hb hx hx1
  have h := mul_nonpos_of_nonneg_of_nonpos (le_of_lt htheta)
    (positive_flux_log_dissipation _ _ hflux.1 hflux.2)
  rw [chemicalPotential_local_detailed_balance theta a b x ha hb hx hx1]
  convert h using 1 <;> dsimp [reversibleRate] <;> ring

theorem freeEnergy_closed_strict_dissipation (theta a b x : ℝ)
    (htheta : 0 < theta) (ha : 0 < a) (hb : 0 < b)
    (hx : 0 < x) (hx1 : x < 1)
    (hne : insertionFlux a x ≠ removalFlux b x) :
    chemicalPotential theta a b x * reversibleRate a b x < 0 := by
  have hflux := positive_site_fluxes a b x ha hb hx hx1
  have h := mul_neg_of_pos_of_neg htheta
    (positive_flux_strict_log_dissipation _ _ hflux.1 hflux.2 hne)
  rw [chemicalPotential_local_detailed_balance theta a b x ha hb hx hx1]
  convert h using 1 <;> dsimp [reversibleRate] <;> ring

theorem reversible_equilibrium_iff (a b x : ℝ) (ha : 0 < a) (hb : 0 < b) :
    reversibleRate a b x = 0 ↔ x = a / (a + b) := by
  have hab : a + b ≠ 0 := ne_of_gt (add_pos ha hb)
  dsimp [reversibleRate, insertionFlux, removalFlux]
  rw [eq_div_iff hab]
  constructor <;> intro h <;> nlinarith

theorem freeEnergy_along_solution_hasDerivAt (theta a b : ℝ)
    (x p : ℝ → ℝ) (t : ℝ) (hx : 0 < x t) (hx1 : x t < 1)
    (hode : HasDerivAt x (reversibleRate a b (x t) + p t) t) :
    HasDerivAt (fun s => freeEnergy theta a b (x s))
      (chemicalPotential theta a b (x t) * (reversibleRate a b (x t) + p t)) t := by
  exact (freeEnergy_hasDerivAt theta a b (x t) hx hx1).comp t hode

theorem freeEnergy_along_solution_open_dissipation (theta a b : ℝ)
    (x p : ℝ → ℝ) (t : ℝ) (htheta : 0 < theta) (ha : 0 < a) (hb : 0 < b)
    (hx : 0 < x t) (hx1 : x t < 1)
    (hode : HasDerivAt x (reversibleRate a b (x t) + p t) t) :
    deriv (fun s => freeEnergy theta a b (x s)) t -
      chemicalPotential theta a b (x t) * p t ≤ 0 := by
  rw [(freeEnergy_along_solution_hasDerivAt theta a b x p t hx hx1 hode).deriv]
  exact freeEnergy_open_port_dissipation theta a b (x t) (p t) htheta ha hb hx hx1

/- A genuine smooth ODE trajectory, not just a state with a hand-picked
   negative derivative. Strict interior and strict decay hold for all t>=0. -/
noncomputable def relaxingSite (t : ℝ) : ℝ := 1 / 2 - Real.exp (-2 * t) / 4

theorem relaxingSite_hasDerivAt (t : ℝ) :
    HasDerivAt relaxingSite (reversibleRate 1 1 (relaxingSite t)) t := by
  have he := (((hasDerivAt_id t).const_mul (-2)).exp).div_const 4
  have h := (hasDerivAt_const t (1 / 2 : ℝ)).sub he
  convert h using 1 <;> dsimp [relaxingSite, reversibleRate, insertionFlux, removalFlux] <;> ring

theorem relaxingSite_strict_domain (t : ℝ) (ht : 0 ≤ t) :
    0 < relaxingSite t ∧ relaxingSite t < 1 := by
  have hp := Real.exp_pos (-2 * t)
  have he : Real.exp (-2 * t) ≤ 1 := by
    rw [← Real.exp_zero]
    exact Real.exp_le_exp.mpr (by linarith)
  dsimp [relaxingSite]
  constructor <;> linarith

theorem relaxingSite_actual_strict_freeEnergy_decay (t : ℝ) (ht : 0 ≤ t) :
    deriv (fun s => freeEnergy 1 1 1 (relaxingSite s)) t < 0 := by
  have hx := relaxingSite_strict_domain t ht
  have hp := Real.exp_pos (-2 * t)
  have hne : insertionFlux 1 (relaxingSite t) ≠ removalFlux 1 (relaxingSite t) := by
    dsimp [insertionFlux, removalFlux, relaxingSite]
    intro heq
    linarith
  change deriv (freeEnergy 1 1 1 ∘ relaxingSite) t < 0
  rw [((freeEnergy_hasDerivAt 1 1 1 (relaxingSite t) hx.1 hx.2).comp t
    (relaxingSite_hasDerivAt t)).deriv]
  exact freeEnergy_closed_strict_dissipation 1 1 1 _ (by norm_num) (by norm_num)
    (by norm_num) hx.1 hx.2 hne

/- Open positive insertion port, starting at x=3/4. The following smooth
   trajectory solves x'=1-2x+1 and stays strict for every finite t>=0.
   Its free energy initially increases: closed-system decay cannot be used
   for a charging/material-input trajectory. -/
noncomputable def chargingSite (t : ℝ) : ℝ := 1 - Real.exp (-2 * t) / 4

theorem chargingSite_hasDerivAt (t : ℝ) :
    HasDerivAt chargingSite (reversibleRate 1 1 (chargingSite t) + 1) t := by
  have he := (((hasDerivAt_id t).const_mul (-2)).exp).div_const 4
  have h := (hasDerivAt_const t (1 : ℝ)).sub he
  convert h using 1 <;> dsimp [chargingSite, reversibleRate, insertionFlux, removalFlux] <;> ring

theorem chargingSite_strict_domain (t : ℝ) (ht : 0 ≤ t) :
    0 < chargingSite t ∧ chargingSite t < 1 := by
  have hp := Real.exp_pos (-2 * t)
  have he : Real.exp (-2 * t) ≤ 1 := by
    rw [← Real.exp_zero]
    exact Real.exp_le_exp.mpr (by linarith)
  dsimp [chargingSite]
  constructor <;> linarith

theorem chargingSite_initial_freeEnergy_increase :
    0 < deriv (fun s => freeEnergy 1 1 1 (chargingSite s)) 0 := by
  have hx := chargingSite_strict_domain 0 (by norm_num)
  change 0 < deriv (freeEnergy 1 1 1 ∘ chargingSite) 0
  rw [((freeEnergy_hasDerivAt 1 1 1 (chargingSite 0) hx.1 hx.2).comp 0
    (chargingSite_hasDerivAt 0)).deriv]
  have hlog : 0 < Real.log (3 : ℝ) := Real.log_pos (by norm_num)
  have hmu : chemicalPotential 1 1 1 (chargingSite 0) = Real.log 3 := by
    rw [chemicalPotential_log_flux_ratio 1 1 1 _ (by norm_num) (by norm_num) hx.1 hx.2]
    norm_num [chargingSite, insertionFlux, removalFlux]
  rw [hmu]
  norm_num [chargingSite, reversibleRate, insertionFlux, removalFlux]
  positivity

theorem chargingSite_open_port_supply_inequality (t : ℝ) (ht : 0 ≤ t) :
    deriv (fun s => freeEnergy 1 1 1 (chargingSite s)) t -
      chemicalPotential 1 1 1 (chargingSite t) ≤ 0 := by
  have hx := chargingSite_strict_domain t ht
  simpa using freeEnergy_along_solution_open_dissipation 1 1 1 chargingSite
    (fun _ => 1) t (by norm_num) (by norm_num) (by norm_num) hx.1 hx.2
      (chargingSite_hasDerivAt t)

end Naheng.Chemistry.Thermodynamics

#print axioms Naheng.Chemistry.Thermodynamics.positive_site_fluxes
#print axioms Naheng.Chemistry.Thermodynamics.freeEnergy_hasDerivAt
#print axioms Naheng.Chemistry.Thermodynamics.chemicalPotential_local_detailed_balance
#print axioms Naheng.Chemistry.Thermodynamics.chemicalPotential_log_flux_ratio
#print axioms Naheng.Chemistry.Thermodynamics.positive_flux_log_dissipation
#print axioms Naheng.Chemistry.Thermodynamics.positive_flux_strict_log_dissipation
#print axioms Naheng.Chemistry.Thermodynamics.freeEnergy_open_port_dissipation
#print axioms Naheng.Chemistry.Thermodynamics.freeEnergy_closed_strict_dissipation
#print axioms Naheng.Chemistry.Thermodynamics.reversible_equilibrium_iff
#print axioms Naheng.Chemistry.Thermodynamics.freeEnergy_along_solution_hasDerivAt
#print axioms Naheng.Chemistry.Thermodynamics.freeEnergy_along_solution_open_dissipation
#print axioms Naheng.Chemistry.Thermodynamics.relaxingSite_hasDerivAt
#print axioms Naheng.Chemistry.Thermodynamics.relaxingSite_strict_domain
#print axioms Naheng.Chemistry.Thermodynamics.relaxingSite_actual_strict_freeEnergy_decay
#print axioms Naheng.Chemistry.Thermodynamics.chargingSite_hasDerivAt
#print axioms Naheng.Chemistry.Thermodynamics.chargingSite_strict_domain
#print axioms Naheng.Chemistry.Thermodynamics.chargingSite_initial_freeEnergy_increase
#print axioms Naheng.Chemistry.Thermodynamics.chargingSite_open_port_supply_inequality
