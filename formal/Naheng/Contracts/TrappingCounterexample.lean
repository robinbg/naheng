import Naheng.Reduction.Exact
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Tactic.FinCases
import Mathlib.Tactic.Linarith

/- An actual two-site, positive-rate, same-input trajectory witness.
   The total damping rate is 2 at both sites, yet c differs. Equal total
   amount for every time and equal initial y do not determine cumulative y.
   This is a declared synthetic affine site model, not a fitted cell. -/
namespace Naheng.Contracts
open Set Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false

def trappingExampleN : Fin 2 → ℝ := fun _ => 1
def trappingExampleA : Fin 2 → ℝ := fun _ => 1
noncomputable def trappingExampleC : Fin 2 → ℝ := fun i => if i = 0 then 1/4 else 3/4
noncomputable def trappingExampleB : Fin 2 → ℝ := fun i => 1 - trappingExampleC i
noncomputable def trappingExampleX (t : ℝ) : Fin 2 → ℝ :=
  fun i => if i = 0 then (2 - Real.exp (-2*t))/4 else (2 + Real.exp (-2*t))/4
noncomputable def trappingExampleZ (t : ℝ) : Fin 2 → ℝ :=
  fun i => if i = 0 then (2 + Real.exp (-2*t))/4 else (2 - Real.exp (-2*t))/4
noncomputable def trappingExampleY (t : ℝ) : ℝ := t/2 + (1 - Real.exp (-2*t))/16
noncomputable def trappingExampleW (t : ℝ) : ℝ := t/2 - (1 - Real.exp (-2*t))/16

theorem positive_shared_rate_different_trapping_coefficients :
    (∀ i, 0 < trappingExampleN i ∧ 0 < trappingExampleA i ∧
      0 < trappingExampleB i ∧ 0 < trappingExampleC i ∧
      trappingExampleA i + trappingExampleB i + trappingExampleC i = 2) ∧
    trappingExampleC 0 ≠ trappingExampleC 1 := by
  constructor
  · intro i
    fin_cases i <;> norm_num [trappingExampleN, trappingExampleA, trappingExampleB, trappingExampleC]
  · norm_num [trappingExampleC]

theorem equal_total_trapping_example_actual_site_solutions (t : ℝ) (i : Fin 2) :
    HasDerivAt (fun s => trappingExampleX s i)
      (siteDerivative (trappingExampleA i) (trappingExampleB i)
        (trappingExampleC i) (trappingExampleX t i)) t ∧
    HasDerivAt (fun s => trappingExampleZ s i)
      (siteDerivative (trappingExampleA i) (trappingExampleB i)
        (trappingExampleC i) (trappingExampleZ t i)) t := by
  have he : HasDerivAt (fun s : ℝ => Real.exp (-2*s)) (-2*Real.exp (-2*t)) t := by
    simpa only [id, mul_one, one_mul, mul_comm] using (((hasDerivAt_id t).const_mul (-2)).exp)
  have hlo := ((hasDerivAt_const t (2 : ℝ)).sub he).div_const 4
  have hhi := ((hasDerivAt_const t (2 : ℝ)).add he).div_const 4
  fin_cases i
  · constructor
    · convert hlo using 1 <;> norm_num [trappingExampleX, trappingExampleA,
        trappingExampleB, trappingExampleC, siteDerivative] <;> ring
    · convert hhi using 1 <;> norm_num [trappingExampleZ, trappingExampleA,
        trappingExampleB, trappingExampleC, siteDerivative] <;> ring
  · constructor
    · convert hhi using 1 <;> norm_num [trappingExampleX, trappingExampleA,
        trappingExampleB, trappingExampleC, siteDerivative] <;> ring
    · convert hlo using 1 <;> norm_num [trappingExampleZ, trappingExampleA,
        trappingExampleB, trappingExampleC, siteDerivative] <;> ring

theorem equal_total_trapping_example_actual_inventory_solutions (t : ℝ) :
    HasDerivAt trappingExampleY
      (trappedRate trappingExampleN trappingExampleC (trappingExampleX t)) t ∧
    HasDerivAt trappingExampleW
      (trappedRate trappingExampleN trappingExampleC (trappingExampleZ t)) t := by
  have he : HasDerivAt (fun s : ℝ => Real.exp (-2*s)) (-2*Real.exp (-2*t)) t := by
    simpa only [id, mul_one, one_mul, mul_comm] using (((hasDerivAt_id t).const_mul (-2)).exp)
  have base := (hasDerivAt_id t).div_const 2
  have side := ((hasDerivAt_const t (1 : ℝ)).sub he).div_const 16
  constructor
  · convert base.add side using 1 <;> norm_num [trappingExampleY, trappingExampleN,
      trappingExampleC, trappingExampleX, trappedRate, Fin.sum_univ_two] <;> ring
  · convert base.sub side using 1 <;> norm_num [trappingExampleW, trappingExampleN,
      trappingExampleC, trappingExampleZ, trappedRate, Fin.sum_univ_two] <;> ring

theorem equal_total_trapping_example_strict_domain (t : ℝ) (ht : 0 ≤ t) :
    ∀ i, trappingExampleX t i ∈ Ioo 0 1 ∧ trappingExampleZ t i ∈ Ioo 0 1 := by
  have hp : 0 < Real.exp (-(2*t)) := Real.exp_pos _
  have he : Real.exp (-(2*t)) ≤ 1 := Real.exp_le_one_iff.mpr (by linarith)
  intro i
  fin_cases i <;> constructor <;> constructor <;>
    norm_num [trappingExampleX, trappingExampleZ] <;> linarith only [hp, he]

theorem equal_total_all_time_does_not_determine_cumulative_trapping :
    (∀ t, totalAmount trappingExampleN (trappingExampleX t) = 1 ∧
      totalAmount trappingExampleN (trappingExampleZ t) = 1) ∧
    trappingExampleY 0 = 0 ∧ trappingExampleW 0 = 0 ∧
    (∀ t, 0 < t → trappingExampleW t < trappingExampleY t) := by
  constructor
  · intro t
    constructor <;> norm_num [totalAmount, trappingExampleN, trappingExampleX,
      trappingExampleZ, Fin.sum_univ_two] <;> ring
  · refine ⟨by norm_num [trappingExampleY], by norm_num [trappingExampleW], ?_⟩
    intro t ht
    have he : Real.exp (-2*t) < 1 := Real.exp_lt_one_iff.mpr (by linarith)
    dsimp [trappingExampleW, trappingExampleY]
    linarith only [he]

end Naheng.Contracts

set_option pp.proofs false

#print Naheng.Contracts.positive_shared_rate_different_trapping_coefficients
#print axioms Naheng.Contracts.positive_shared_rate_different_trapping_coefficients
#print Naheng.Contracts.equal_total_trapping_example_actual_site_solutions
#print axioms Naheng.Contracts.equal_total_trapping_example_actual_site_solutions
#print Naheng.Contracts.equal_total_trapping_example_actual_inventory_solutions
#print axioms Naheng.Contracts.equal_total_trapping_example_actual_inventory_solutions
#print Naheng.Contracts.equal_total_trapping_example_strict_domain
#print axioms Naheng.Contracts.equal_total_trapping_example_strict_domain
#print Naheng.Contracts.equal_total_all_time_does_not_determine_cumulative_trapping
#print axioms Naheng.Contracts.equal_total_all_time_does_not_determine_cumulative_trapping
