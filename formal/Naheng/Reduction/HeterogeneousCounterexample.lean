import Naheng.Reduction.Exact
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring

/- Conditional synthetic formalization. Reuses the published actual finite-site
   definitions and ceN. Fixed externally supplied rates are considered here;
   state-dependent current feedback, arbitrary readouts, experiments and a
   runtime state-selection certificate are outside this statement family. -/
namespace Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false

def twoSiteImbalance (x : Fin 2 → ℝ) : ℝ := x 0 - x 1
def strictTwoSiteDomain (x : Fin 2 → ℝ) : Prop := ∀ i, 0 < x i ∧ x i < 1
def symmetricPairRate (k0 k1 : ℝ) : Fin 2 → ℝ := fun i => if i = 0 then k0 else k1
def swappedPairState (u v : ℝ) : Fin 2 → ℝ := fun i => if i = 0 then u else v
noncomputable def symmetricPairTrajectory (k0 k1 u v t : ℝ) : Fin 2 → ℝ :=
  fun i => (1 / 2 : ℝ) + (swappedPairState u v i - 1 / 2) *
    Real.exp ((-2 * symmetricPairRate k0 k1 i) * t)

/- The missing internal composition has a concrete coefficient in the actual
   weighted RHS. This identity has no physical or target-error assumptions. -/
theorem two_site_amount_rate_with_imbalance (a b c x : Fin 2 → ℝ) :
    detailedAmountRate ceN a b c x = totalSource ceN a -
      ((a 0 + b 0 + c 0 + (a 1 + b 1 + c 1)) / 2) * totalAmount ceN x -
      ((a 0 + b 0 + c 0 - (a 1 + b 1 + c 1)) / 2) * twoSiteImbalance x := by
  simp only [detailedAmountRate, totalSource, totalAmount, siteDerivative,
    ceN, twoSiteImbalance, Fin.sum_univ_two]
  ring


theorem two_site_imbalance_rate_identity (a b c x : Fin 2 → ℝ) :
    siteDerivative (a 0) (b 0) (c 0) (x 0) -
      siteDerivative (a 1) (b 1) (c 1) (x 1) = a 0 - a 1 -
      ((a 0 + b 0 + c 0 - (a 1 + b 1 + c 1)) / 2) * totalAmount ceN x -
      ((a 0 + b 0 + c 0 + (a 1 + b 1 + c 1)) / 2) * twoSiteImbalance x := by
  simp only [siteDerivative, totalAmount, ceN, twoSiteImbalance, Fin.sum_univ_two]
  ring


/- q and d determine both occupations for these two unit-capacity sites.
   This is an invertible change of coordinates, not dimension reduction. -/
theorem two_site_total_imbalance_reconstruction (x : Fin 2 → ℝ) :
    x 0 = (totalAmount ceN x + twoSiteImbalance x) / 2 ∧
    x 1 = (totalAmount ceN x - twoSiteImbalance x) / 2 := by
  simp only [totalAmount, ceN, twoSiteImbalance, Fin.sum_univ_two]
  constructor <;> ring


/- Derivatives are obtained from the supplied per-site ODE, not from assumed
   aggregate closure. Both q and the necessary composition coordinate evolve. -/
theorem two_site_total_imbalance_hasDerivAt
    (x a b c : ℝ → Fin 2 → ℝ) (solution : IsSiteTrajectory x a b c) (t : ℝ) :
    HasDerivAt (fun s => totalAmount ceN (x s))
      (totalSource ceN (a t) -
        ((a t 0 + b t 0 + c t 0 + (a t 1 + b t 1 + c t 1)) / 2) * totalAmount ceN (x t) -
        ((a t 0 + b t 0 + c t 0 - (a t 1 + b t 1 + c t 1)) / 2) * twoSiteImbalance (x t)) t ∧
    HasDerivAt (fun s => twoSiteImbalance (x s))
      (a t 0 - a t 1 -
        ((a t 0 + b t 0 + c t 0 - (a t 1 + b t 1 + c t 1)) / 2) * totalAmount ceN (x t) -
        ((a t 0 + b t 0 + c t 0 + (a t 1 + b t 1 + c t 1)) / 2) * twoSiteImbalance (x t)) t := by
  have hQ : HasDerivAt (fun s => totalAmount ceN (x s))
      (detailedAmountRate ceN (a t) (b t) (c t) (x t)) t := by
    simpa only [totalAmount, detailedAmountRate] using
      (HasDerivAt.sum (u := Finset.univ) (fun i _ => (solution t i).const_mul (ceN i)))
  have hD : HasDerivAt (fun s => twoSiteImbalance (x s))
      (siteDerivative (a t 0) (b t 0) (c t 0) (x t 0) -
        siteDerivative (a t 1) (b t 1) (c t 1) (x t 1)) t :=
    (solution t 0).sub (solution t 1)
  rw [two_site_amount_rate_with_imbalance] at hQ
  rw [two_site_imbalance_rate_identity] at hD
  exact ⟨hQ, hD⟩


/- A parameter family, not only one hard-coded rational answer. The positive
   forward/reverse coefficients are a=b=k_i, c=0, hence total rates 2*k_i.
   States are strictly inside the domain and differ in composition. -/
theorem positive_heterogeneous_swapped_states
    (k0 k1 u v : ℝ) (hk0 : 0 < k0) (hk : k0 < k1)
    (hu : 0 < u) (huv : u < v) (hv : v < 1) :
    (∀ i, 0 < symmetricPairRate k0 k1 i) ∧
    strictTwoSiteDomain (swappedPairState u v) ∧
    strictTwoSiteDomain (swappedPairState v u) ∧
    totalAmount ceN (swappedPairState u v) = u + v ∧
    totalAmount ceN (swappedPairState v u) = u + v ∧
    detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState u v) -
      detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState v u) =
      2 * (k1 - k0) * (u - v) ∧
    detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState u v) <
      detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState v u) := by
  have hpositive : ∀ i, 0 < symmetricPairRate k0 k1 i := by
    intro i
    by_cases hi : i = 0
    · simpa [symmetricPairRate, hi] using hk0
    · simpa [symmetricPairRate, hi] using lt_trans hk0 hk
  have hX : strictTwoSiteDomain (swappedPairState u v) := by
    intro i
    by_cases hi : i = 0
    · simpa [swappedPairState, hi] using And.intro hu (lt_trans huv hv)
    · simpa [swappedPairState, hi] using And.intro (lt_trans hu huv) hv
  have hZ : strictTwoSiteDomain (swappedPairState v u) := by
    intro i
    by_cases hi : i = 0
    · simpa [swappedPairState, hi] using And.intro (lt_trans hu huv) hv
    · simpa [swappedPairState, hi] using And.intro hu (lt_trans huv hv)
  have hQX : totalAmount ceN (swappedPairState u v) = u + v := by
    norm_num [totalAmount, ceN, swappedPairState, Fin.sum_univ_two]
  have hQZ : totalAmount ceN (swappedPairState v u) = u + v := by
    norm_num [totalAmount, ceN, swappedPairState, Fin.sum_univ_two] <;> ring
  have hdiff : detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState u v) -
      detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState v u) =
      2 * (k1 - k0) * (u - v) := by
    norm_num [detailedAmountRate, siteDerivative, ceN, symmetricPairRate, ceC, swappedPairState, Fin.sum_univ_two] <;> ring
  have hprod : 0 < 2 * (k1 - k0) * (v - u) :=
    mul_pos (mul_pos (by norm_num) (sub_pos.mpr hk)) (sub_pos.mpr huv)
  refine ⟨hpositive, hX, hZ, hQX, hQZ, hdiff, ?_⟩
  nlinarith


/- This negation is proved from independently constructed internal states.
   It rejects every deterministic total-only RHS on the entire strict domain,
   including nonlinear f, for this fixed positive unequal-rate family. -/
theorem heterogeneous_total_only_closure_impossible
    (k0 k1 : ℝ) (hk0 : 0 < k0) (hk : k0 < k1) :
    ¬ ∃ f : ℝ → ℝ, ∀ x : Fin 2 → ℝ, strictTwoSiteDomain x →
      detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC x =
        f (totalAmount ceN x) := by
  rcases positive_heterogeneous_swapped_states k0 k1 (1 / 4) (3 / 4) hk0 hk
      (by norm_num) (by norm_num) (by norm_num) with
    ⟨_, hX, hZ, hQX, hQZ, _, hlt⟩
  rintro ⟨f, hf⟩
  have hRX := hf (swappedPairState (1 / 4) (3 / 4)) hX
  have hRZ := hf (swappedPairState (3 / 4) (1 / 4)) hZ
  rw [hQX] at hRX
  rw [hQZ] at hRZ
  exact (ne_of_lt hlt) (hRX.trans hRZ.symm)


/- Explicit nonconstant states solve the actual per-site ODE. No ODE
   existence axiom and no supplied aggregate derivative is used here. -/
theorem symmetric_pair_exp_is_actual_solution (k0 k1 u v : ℝ) :
    IsSiteTrajectory (symmetricPairTrajectory k0 k1 u v)
      (fun _ => symmetricPairRate k0 k1) (fun _ => symmetricPairRate k0 k1) (fun _ => ceC) := by
  intro t i
  let k := symmetricPairRate k0 k1 i
  let w := swappedPairState u v i
  have h := ((((hasDerivAt_id t).const_mul (-2 * k)).exp).const_mul (w - 1 / 2)).const_add (1 / 2)
  convert h using 1 <;> dsimp [symmetricPairTrajectory, siteDerivative, ceC, k, w] <;> ring


/- Two genuine forward physical trajectories start at equal total amount and
   have unequal aggregate derivatives at zero. The full n-site family and
   arbitrary feedback/runtime selection still require separate results. -/
theorem positive_heterogeneous_two_solution_counterexample
    (k0 k1 u v : ℝ) (hk0 : 0 < k0) (hk : k0 < k1)
    (hu : 0 < u) (huv : u < v) (hv : v < 1) :
    (∀ t, 0 ≤ t → strictTwoSiteDomain (symmetricPairTrajectory k0 k1 u v t) ∧
      strictTwoSiteDomain (symmetricPairTrajectory k0 k1 v u t)) ∧
    totalAmount ceN (symmetricPairTrajectory k0 k1 u v 0) = u + v ∧
    totalAmount ceN (symmetricPairTrajectory k0 k1 v u 0) = u + v ∧
    HasDerivAt (fun t => totalAmount ceN (symmetricPairTrajectory k0 k1 u v t))
      (detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState u v)) 0 ∧
    HasDerivAt (fun t => totalAmount ceN (symmetricPairTrajectory k0 k1 v u t))
      (detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState v u)) 0 ∧
    detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState u v) <
      detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC (swappedPairState v u) ∧
    (∀ t, 0 < t → totalAmount ceN (symmetricPairTrajectory k0 k1 u v t) <
      totalAmount ceN (symmetricPairTrajectory k0 k1 v u t)) := by
  rcases positive_heterogeneous_swapped_states k0 k1 u v hk0 hk hu huv hv with
    ⟨hpositive, hX, hZ, hQX, hQZ, _, hlt⟩
  have hzeroX : symmetricPairTrajectory k0 k1 u v 0 = swappedPairState u v := by
    funext i
    norm_num [symmetricPairTrajectory] <;> ring
  have hzeroZ : symmetricPairTrajectory k0 k1 v u 0 = swappedPairState v u := by
    funext i
    norm_num [symmetricPairTrajectory] <;> ring
  have hbounded (w k t : ℝ) (hw0 : 0 < w) (hw1 : w < 1) (hkpos : 0 < k) (ht : 0 ≤ t) :
      0 < (1 / 2 : ℝ) + (w - 1 / 2) * Real.exp ((-2 * k) * t) ∧
      (1 / 2 : ℝ) + (w - 1 / 2) * Real.exp ((-2 * k) * t) < 1 := by
    have hepos := Real.exp_pos ((-2 * k) * t)
    have heone : Real.exp ((-2 * k) * t) ≤ 1 := Real.exp_le_one_iff.mpr
      (mul_nonpos_of_nonpos_of_nonneg (by nlinarith) ht)
    have hleft : 0 ≤ (1 - Real.exp ((-2 * k) * t)) / 2 :=
      div_nonneg (sub_nonneg.mpr heone) (by norm_num)
    have hright := mul_pos hw0 hepos
    have hupper := mul_pos (sub_pos.mpr hw1) hepos
    constructor <;> nlinarith
  have hdomain : ∀ t, 0 ≤ t → strictTwoSiteDomain (symmetricPairTrajectory k0 k1 u v t) ∧
      strictTwoSiteDomain (symmetricPairTrajectory k0 k1 v u t) := by
    intro t ht
    constructor
    · intro i
      exact hbounded (swappedPairState u v i) (symmetricPairRate k0 k1 i) t
        (hX i).1 (hX i).2 (hpositive i) ht
    · intro i
      exact hbounded (swappedPairState v u i) (symmetricPairRate k0 k1 i) t
        (hZ i).1 (hZ i).2 (hpositive i) ht
  have hderX : HasDerivAt (fun t => totalAmount ceN (symmetricPairTrajectory k0 k1 u v t))
      (detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC
        (symmetricPairTrajectory k0 k1 u v 0)) 0 := by
    simpa only [totalAmount, detailedAmountRate] using
      (HasDerivAt.sum (u := Finset.univ) (fun i _ =>
        ((symmetric_pair_exp_is_actual_solution k0 k1 u v) 0 i).const_mul (ceN i)))
  have hderZ : HasDerivAt (fun t => totalAmount ceN (symmetricPairTrajectory k0 k1 v u t))
      (detailedAmountRate ceN (symmetricPairRate k0 k1) (symmetricPairRate k0 k1) ceC
        (symmetricPairTrajectory k0 k1 v u 0)) 0 := by
    simpa only [totalAmount, detailedAmountRate] using
      (HasDerivAt.sum (u := Finset.univ) (fun i _ =>
        ((symmetric_pair_exp_is_actual_solution k0 k1 v u) 0 i).const_mul (ceN i)))
  rw [hzeroX] at hderX
  rw [hzeroZ] at hderZ
  have hfuture : ∀ t, 0 < t → totalAmount ceN (symmetricPairTrajectory k0 k1 u v t) <
      totalAmount ceN (symmetricPairTrajectory k0 k1 v u t) := by
    intro t ht
    have hrategap := mul_pos (sub_pos.mpr hk) ht
    have hexp : Real.exp ((-2 * k1) * t) < Real.exp ((-2 * k0) * t) :=
      Real.exp_lt_exp.mpr (by nlinarith)
    have hprod := mul_pos (sub_pos.mpr huv) (sub_pos.mpr hexp)
    simp only [neg_mul] at hprod
    norm_num [totalAmount, ceN, symmetricPairTrajectory, swappedPairState, symmetricPairRate, Fin.sum_univ_two]
    nlinarith
  exact ⟨hdomain, by rw [hzeroX]; exact hQX, by rw [hzeroZ]; exact hQZ,
    hderX, hderZ, hlt, hfuture⟩

end Naheng.Reduction
