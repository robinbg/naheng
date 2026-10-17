import Naheng.Reduction.TrajectoryError
import Mathlib.Analysis.Calculus.MeanValue
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring

/- Unpublished candidate. A variable actual damping coefficient is retained
   in the error ODE. Only its positive lower bound enters the comparison
   envelope. Supplied solutions, whole-horizon occupations and coefficient
   budgets remain independent obligations; no runtime or physical authority. -/
namespace Naheng.Reduction
open Set Filter
open scoped BigOperators Topology

theorem dampedEnvelope_nonnegative (delta rmin epsilon t : ℝ)
    (hdelta : 0 ≤ delta) (hrmin : 0 < rmin) (hepsilon : 0 ≤ epsilon) (ht : 0 ≤ t) :
    0 ≤ dampedEnvelope delta rmin epsilon t := by
  have hproduct : 0 ≤ rmin * t := mul_nonneg (le_of_lt hrmin) ht
  have hexponent : -rmin * t ≤ 0 := by nlinarith
  have hexp : Real.exp (-rmin * t) ≤ 1 := Real.exp_le_one_iff.mpr hexponent
  exact add_nonneg
    (mul_nonneg hdelta (le_of_lt (Real.exp_pos _)))
    (div_nonneg (mul_nonneg hepsilon (sub_nonneg.mpr hexp)) (le_of_lt hrmin))


/- At a positive comparison boundary, r(t)-rmin >= 0 improves damping.
   The supplied derivative remains R(t)-r(t)e(t), never R(t)-rmin e(t).
   No bound on the desired error trajectory is an input hypothesis. -/
theorem scalar_variable_damped_upper_bound (e R r : ℝ → ℝ)
    (delta rmin epsilon T : ℝ) (_hT : 0 ≤ T) (hrmin : 0 < rmin)
    (hdelta : 0 ≤ delta) (hepsilon : 0 ≤ epsilon)
    (he : ContinuousOn e (Icc 0 T))
    (hderiv : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt e (R t - r t * e t) (Ici t) t)
    (hr : ∀ t ∈ Ico 0 T, rmin ≤ r t)
    (hinitial : e 0 ≤ delta) (hR : ∀ t ∈ Ico 0 T, R t ≤ epsilon) :
    ∀ t ∈ Icc 0 T, e t ≤ dampedEnvelope delta rmin epsilon t := by
  have perturbed : ∀ t ∈ Icc 0 T, ∀ eta > 0,
      e t ≤ dampedEnvelope delta rmin epsilon t + eta * (t + 1) := by
    intro t ht eta heta
    apply image_le_of_deriv_right_lt_deriv_boundary he hderiv
      (B := fun s => dampedEnvelope delta rmin epsilon s + eta * (s + 1))
      (B' := fun s => -rmin * dampedEnvelope delta rmin epsilon s + epsilon + eta)
    · rw [dampedEnvelope_initial]
      simp only [zero_add, mul_one]
      linarith
    · intro s
      simpa only [mul_one] using
        (dampedEnvelope_hasDerivAt delta rmin epsilon s hrmin).add
          (((hasDerivAt_id s).add_const 1).const_mul eta)
    · intro s hs hboundary
      have hs1 : 0 < s + 1 := by linarith [hs.1]
      have henv := dampedEnvelope_nonnegative delta rmin epsilon s hdelta hrmin hepsilon hs.1
      have hrate := hr s hs
      have hrate_pos : 0 < r s := lt_of_lt_of_le hrmin hrate
      have hextra : 0 ≤ (r s - rmin) * dampedEnvelope delta rmin epsilon s :=
        mul_nonneg (sub_nonneg.mpr hrate) henv
      have hpositive := mul_pos (mul_pos hrate_pos heta) hs1
      have hresidual := hR s hs
      rw [hboundary]
      nlinarith
    · exact ht
  intro t ht
  have hcont : ContinuousWithinAt
      (fun eta : ℝ => dampedEnvelope delta rmin epsilon t + eta * (t + 1)) (Ioi 0) 0 :=
    continuousWithinAt_const.add (continuousWithinAt_id.mul continuousWithinAt_const)
  convert continuousWithinAt_const.closure_le _ hcont (perturbed t ht) using 1 <;> simp


theorem scalar_variable_damped_error_abs_bound (e R r : ℝ → ℝ)
    (delta rmin epsilon T : ℝ) (hT : 0 ≤ T) (hrmin : 0 < rmin)
    (hdelta : 0 ≤ delta) (hepsilon : 0 ≤ epsilon)
    (he : ContinuousOn e (Icc 0 T))
    (hderiv : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt e (R t - r t * e t) (Ici t) t)
    (hr : ∀ t ∈ Ico 0 T, rmin ≤ r t)
    (hinitial : |e 0| ≤ delta) (hR : ∀ t ∈ Ico 0 T, |R t| ≤ epsilon) :
    ∀ t ∈ Icc 0 T, |e t| ≤ dampedEnvelope delta rmin epsilon t := by
  have upper := scalar_variable_damped_upper_bound e R r delta rmin epsilon T
    hT hrmin hdelta hepsilon he hderiv hr (le_trans (le_abs_self _) hinitial)
    (fun t ht => le_trans (le_abs_self _) (hR t ht))
  have hneg : ∀ t ∈ Ico 0 T, HasDerivWithinAt (fun s => -e s)
      ((-R t) - r t * (-e t)) (Ici t) t := by
    intro t ht
    convert (hderiv t ht).neg using 1 <;> ring
  have lower := scalar_variable_damped_upper_bound (fun s => -e s) (fun s => -R s) r
    delta rmin epsilon T hT hrmin hdelta hepsilon he.neg hneg hr
    (by change -e 0 ≤ delta; have h := (abs_le.mp hinitial).1; linarith)
    (by intro t ht; change -R t ≤ epsilon; have h := (abs_le.mp (hR t ht)).1; linarith)
  intro t ht
  exact abs_le.mpr ⟨by
    have h := lower t ht
    change -e t ≤ dampedEnvelope delta rmin epsilon t at h
    linarith, upper t ht⟩


variable {ι : Type*} [Fintype ι]

/- Actual finite-site connection: same time-indexed source A, actual r(t)
   in both reduced ODE and the coefficient budget, constant rmin only in
   the final comparison envelope. Feedback equivalence is not inferred. -/
theorem finite_site_variable_rate_trajectory_error
    (N : ι → ℝ) (x a b c : ℝ → ι → ℝ) (qeff r : ℝ → ℝ)
    (rmin delta epsilon T : ℝ) (hT : 0 ≤ T) (hrmin : 0 < rmin)
    (hdelta : 0 ≤ delta) (hepsilon : 0 ≤ epsilon) (hN : ∀ i, 0 ≤ N i)
    (hr : ∀ t ∈ Icc 0 T, rmin ≤ r t)
    (hx_cont : ∀ i, ContinuousOn (fun t => x t i) (Icc 0 T))
    (hq_cont : ContinuousOn qeff (Icc 0 T))
    (site_solution : ∀ t ∈ Ico 0 T, ∀ i,
      HasDerivWithinAt (fun s => x s i)
        (siteDerivative (a t i) (b t i) (c t i) (x t i)) (Ici t) t)
    (reduced_solution : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt qeff (totalSource N (a t) - r t * qeff t) (Ici t) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T,
      rateResidualBudget N (a t) (b t) (c t) (r t) ≤ epsilon)
    (initial_error : |totalAmount N (x 0) - qeff 0| ≤ delta) :
    ∀ t ∈ Icc 0 T,
      |totalAmount N (x t) - qeff t| ≤ dampedEnvelope delta rmin epsilon t := by
  let e : ℝ → ℝ := fun t => totalAmount N (x t) - qeff t
  let R : ℝ → ℝ := fun t => detailedAmountRate N (a t) (b t) (c t) (x t) -
    (totalSource N (a t) - r t * totalAmount N (x t))
  have hQcont : ContinuousOn (fun t => totalAmount N (x t)) (Icc 0 T) := by
    simpa only [totalAmount] using
      (continuousOn_finset_sum Finset.univ (fun i _ => continuousOn_const.mul (hx_cont i)))
  have he : ContinuousOn e (Icc 0 T) := hQcont.sub hq_cont
  have hder : ∀ t ∈ Ico 0 T, HasDerivWithinAt e (R t - r t * e t) (Ici t) t := by
    intro t ht
    have hQ : HasDerivWithinAt (fun s => totalAmount N (x s))
        (detailedAmountRate N (a t) (b t) (c t) (x t)) (Ici t) t := by
      simpa only [totalAmount, detailedAmountRate] using
        (HasDerivWithinAt.sum (u := Finset.univ)
          (fun i _ => (site_solution t ht i).const_mul (N i)))
    have h := hQ.sub (reduced_solution t ht)
    have identity : detailedAmountRate N (a t) (b t) (c t) (x t) -
        (totalSource N (a t) - r t * qeff t) = R t - r t * e t := by
      dsimp [R, e]
      ring
    rw [identity] at h
    exact h
  have hR : ∀ t ∈ Ico 0 T, |R t| ≤ epsilon := by
    intro t ht
    have hcc := Ico_subset_Icc_self ht
    exact (detailed_rate_residual_abs_bound N (a t) (b t) (c t) (x t) (r t)
      hN (hx0 t hcc) (hx1 t hcc)).trans (coefficient_budget t hcc)
  exact scalar_variable_damped_error_abs_bound e R r delta rmin epsilon T hT hrmin
    hdelta hepsilon he hder (fun t ht => hr t (Ico_subset_Icc_self ht)) initial_error hR


theorem finite_site_variable_rate_trajectory_error_at
    (N : ι → ℝ) (x a b c : ℝ → ι → ℝ) (qeff r : ℝ → ℝ)
    (rmin delta epsilon T : ℝ) (hT : 0 ≤ T) (hrmin : 0 < rmin)
    (hdelta : 0 ≤ delta) (hepsilon : 0 ≤ epsilon) (hN : ∀ i, 0 ≤ N i)
    (hr : ∀ t ∈ Icc 0 T, rmin ≤ r t)
    (site_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => x s i)
        (siteDerivative (a t i) (b t i) (c t i) (x t i)) t)
    (reduced_solution : ∀ t ∈ Icc 0 T,
      HasDerivAt qeff (totalSource N (a t) - r t * qeff t) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T,
      rateResidualBudget N (a t) (b t) (c t) (r t) ≤ epsilon)
    (initial_error : |totalAmount N (x 0) - qeff 0| ≤ delta) :
    ∀ t ∈ Icc 0 T,
      |totalAmount N (x t) - qeff t| ≤ dampedEnvelope delta rmin epsilon t :=
  finite_site_variable_rate_trajectory_error N x a b c qeff r rmin delta epsilon T hT hrmin
    hdelta hepsilon hN hr
    (fun i t ht => (site_solution t ht i).continuousAt.continuousWithinAt)
    (fun t ht => (reduced_solution t ht).continuousAt.continuousWithinAt)
    (fun t ht i => (site_solution t (Ico_subset_Icc_self ht) i).hasDerivWithinAt)
    (fun t ht => (reduced_solution t (Ico_subset_Icc_self ht)).hasDerivWithinAt)
    hx0 hx1 coefficient_budget initial_error


/- Constant-case regression uses exactly the existing constant envelope;
   the already published constant declarations are unchanged. -/
theorem finite_site_variable_rate_constant_regression
    (N : ι → ℝ) (x a b c : ℝ → ι → ℝ) (qeff : ℝ → ℝ)
    (r delta epsilon T : ℝ) (hT : 0 ≤ T) (hr : 0 < r)
    (hdelta : 0 ≤ delta) (hepsilon : 0 ≤ epsilon) (hN : ∀ i, 0 ≤ N i)
    (site_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => x s i)
        (siteDerivative (a t i) (b t i) (c t i) (x t i)) t)
    (reduced_solution : ∀ t ∈ Icc 0 T,
      HasDerivAt qeff (totalSource N (a t) - r * qeff t) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T, rateResidualBudget N (a t) (b t) (c t) r ≤ epsilon)
    (initial_error : |totalAmount N (x 0) - qeff 0| ≤ delta) :
    ∀ t ∈ Icc 0 T,
      |totalAmount N (x t) - qeff t| ≤ dampedEnvelope delta r epsilon t :=
  finite_site_variable_rate_trajectory_error_at N x a b c qeff (fun _ => r) r delta epsilon T
    hT hr hdelta hepsilon hN (fun _ _ => le_refl r) site_solution reduced_solution
    hx0 hx1 coefficient_budget initial_error


/- Nonempty variable-rate family, not a fitted cell or a dynamic degradation
   experiment. Time here is a numerical second divided by a declared 1 s
   scale, so the affine factor is dimensionless. r(t)=3+t is genuinely
   nonconstant; one positive-capacity site stays at half occupancy and its
   reduced source uses the same time-dependent coefficients. -/
def variableOneSiteN : Fin 1 → ℝ := fun _ => 1
def variableOneSiteR (t : ℝ) : ℝ := 3 + t
noncomputable def variableOneSiteA (t : ℝ) : Fin 1 → ℝ := fun _ => (3 + t) / 2
noncomputable def variableOneSiteB (t : ℝ) : Fin 1 → ℝ := variableOneSiteA t
def variableOneSiteC : ℝ → Fin 1 → ℝ := fun _ _ => 0
noncomputable def variableOneSiteX : ℝ → Fin 1 → ℝ := fun _ _ => 1 / 2
noncomputable def variableOneSiteQ : ℝ → ℝ := fun _ => 1 / 2

theorem variable_coefficient_nonempty_trajectory_example (T : ℝ) (hT : 0 ≤ T) :
    ∀ t ∈ Icc 0 T,
      |totalAmount variableOneSiteN (variableOneSiteX t) - variableOneSiteQ t| ≤
        dampedEnvelope 0 3 0 t := by
  have hsite : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => variableOneSiteX s i)
        (siteDerivative (variableOneSiteA t i) (variableOneSiteB t i)
          (variableOneSiteC t i) (variableOneSiteX t i)) t := by
    intro t _ i
    have hzero : siteDerivative (variableOneSiteA t i) (variableOneSiteB t i)
        (variableOneSiteC t i) (variableOneSiteX t i) = 0 := by
      dsimp [siteDerivative, variableOneSiteA, variableOneSiteB, variableOneSiteC, variableOneSiteX]
      ring
    rw [hzero]
    exact hasDerivAt_const t (1 / 2 : ℝ)
  have hsource : ∀ t, totalSource variableOneSiteN (variableOneSiteA t) = (3 + t) / 2 := by
    intro t
    simp [totalSource, variableOneSiteN, variableOneSiteA, Fin.sum_univ_one]
  have hq : ∀ t ∈ Icc 0 T,
      HasDerivAt variableOneSiteQ
        (totalSource variableOneSiteN (variableOneSiteA t) - variableOneSiteR t * variableOneSiteQ t) t := by
    intro t _
    have hzero : totalSource variableOneSiteN (variableOneSiteA t) -
        variableOneSiteR t * variableOneSiteQ t = 0 := by
      rw [hsource]
      dsimp [variableOneSiteR, variableOneSiteQ]
      ring
    rw [hzero]
    exact hasDerivAt_const t (1 / 2 : ℝ)
  have hbudget : ∀ t, rateResidualBudget variableOneSiteN
      (variableOneSiteA t) (variableOneSiteB t) (variableOneSiteC t) (variableOneSiteR t) = 0 := by
    intro t
    have hcoef : ∀ i, variableOneSiteA t i + variableOneSiteB t i + variableOneSiteC t i = variableOneSiteR t := by
      intro i
      dsimp [variableOneSiteA, variableOneSiteB, variableOneSiteC, variableOneSiteR]
      ring
    simp [rateResidualBudget, hcoef]
  exact finite_site_variable_rate_trajectory_error_at variableOneSiteN variableOneSiteX
    variableOneSiteA variableOneSiteB variableOneSiteC variableOneSiteQ variableOneSiteR 3 0 0 T hT
    (by norm_num) (by norm_num) (by norm_num) (by intro i; norm_num [variableOneSiteN])
    (by intro t ht; dsimp [variableOneSiteR]; linarith [ht.1]) hsite hq
    (by intro t _ i; norm_num [variableOneSiteX])
    (by intro t _ i; norm_num [variableOneSiteX])
    (by intro t _; simpa only [hbudget] using (le_refl (0 : ℝ)))
    (by norm_num [totalAmount, variableOneSiteN, variableOneSiteX, variableOneSiteQ, Fin.sum_univ_one])


theorem positive_nonconstant_comparison_rate_example :
    variableOneSiteR 0 = 3 ∧ variableOneSiteR 1 = 4 ∧
    (∀ t, 0 ≤ t → 0 < variableOneSiteR t) := by
  refine ⟨by norm_num [variableOneSiteR], by norm_num [variableOneSiteR], ?_⟩
  intro t ht
  dsimp [variableOneSiteR]
  linarith

end Naheng.Reduction
