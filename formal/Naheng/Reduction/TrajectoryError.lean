import Naheng.Reduction.Residual
import Mathlib.Analysis.Calculus.MeanValue
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Linarith

/- Published partial finite-horizon reduction slice. These are standard scalar
   comparison results applied to the actual finite-site residual. No novelty,
   floating arithmetic, arbitrary readout or physical-cell certificate. -/
namespace Naheng.Reduction
open Set Filter
open scoped BigOperators Topology
set_option pp.proofs false

noncomputable def dampedEnvelope (delta r epsilon t : ℝ) : ℝ :=
  delta * Real.exp (-r * t) + epsilon * (1 - Real.exp (-r * t)) / r

theorem dampedEnvelope_initial (delta r epsilon : ℝ) :
    dampedEnvelope delta r epsilon 0 = delta := by
  simp [dampedEnvelope]

#print dampedEnvelope_initial
#print axioms dampedEnvelope_initial

theorem dampedEnvelope_hasDerivAt (delta r epsilon t : ℝ) (hr : 0 < r) :
    HasDerivAt (dampedEnvelope delta r epsilon)
      (-r * dampedEnvelope delta r epsilon t + epsilon) t := by
  have hexp : HasDerivAt (fun s : ℝ => Real.exp (-r * s))
      (-r * Real.exp (-r * t)) t := by
    simpa only [mul_one, mul_comm] using (((hasDerivAt_id t).const_mul (-r)).exp)
  have h := (hexp.const_mul delta).add
    ((((hasDerivAt_const t (1 : ℝ)).sub hexp).const_mul epsilon).div_const r)
  convert h using 1
  dsimp [dampedEnvelope]
  field_simp [ne_of_gt hr]
  ring

#print dampedEnvelope_hasDerivAt
#print axioms dampedEnvelope_hasDerivAt

/- No trajectory error bound is assumed. The supplied signed perturbation R
   and the actual scalar error equation are used in a strict barrier proof. -/
theorem scalar_damped_upper_bound (e R : ℝ → ℝ) (delta r epsilon T : ℝ)
    (hr : 0 < r) (he : ContinuousOn e (Icc 0 T))
    (hderiv : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt e (R t - r * e t) (Ici t) t)
    (hinitial : e 0 ≤ delta) (hR : ∀ t ∈ Ico 0 T, R t ≤ epsilon) :
    ∀ t ∈ Icc 0 T, e t ≤ dampedEnvelope delta r epsilon t := by
  have perturbed : ∀ t ∈ Icc 0 T, ∀ eta > 0,
      e t ≤ dampedEnvelope delta r epsilon t + eta * (t + 1) := by
    intro t ht eta heta
    apply image_le_of_deriv_right_lt_deriv_boundary he hderiv
      (B := fun s => dampedEnvelope delta r epsilon s + eta * (s + 1))
      (B' := fun s => -r * dampedEnvelope delta r epsilon s + epsilon + eta)
    · rw [dampedEnvelope_initial]
      simp only [zero_add, mul_one]
      linarith
    · intro s
      simpa only [mul_one] using
        (dampedEnvelope_hasDerivAt delta r epsilon s hr).add
          (((hasDerivAt_id s).add_const 1).const_mul eta)
    · intro s hs hboundary
      have hs1 : 0 < s + 1 := by linarith [hs.1]
      have hpositive := mul_pos (mul_pos hr heta) hs1
      have hresidual := hR s hs
      rw [hboundary]
      nlinarith
    · exact ht
  intro t ht
  have hcont : ContinuousWithinAt
      (fun eta : ℝ => dampedEnvelope delta r epsilon t + eta * (t + 1)) (Ioi 0) 0 :=
    continuousWithinAt_const.add (continuousWithinAt_id.mul continuousWithinAt_const)
  convert continuousWithinAt_const.closure_le _ hcont (perturbed t ht) using 1 <;> simp

#print scalar_damped_upper_bound
#print axioms scalar_damped_upper_bound

theorem scalar_damped_error_abs_bound (e R : ℝ → ℝ) (delta r epsilon T : ℝ)
    (hr : 0 < r) (he : ContinuousOn e (Icc 0 T))
    (hderiv : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt e (R t - r * e t) (Ici t) t)
    (hinitial : |e 0| ≤ delta) (hR : ∀ t ∈ Ico 0 T, |R t| ≤ epsilon) :
    ∀ t ∈ Icc 0 T, |e t| ≤ dampedEnvelope delta r epsilon t := by
  have upper := scalar_damped_upper_bound e R delta r epsilon T hr he hderiv
    (le_trans (le_abs_self _) hinitial)
    (fun t ht => le_trans (le_abs_self _) (hR t ht))
  have hneg : ∀ t ∈ Ico 0 T, HasDerivWithinAt (fun s => -e s)
      ((-R t) - r * (-e t)) (Ici t) t := by
    intro t ht
    convert (hderiv t ht).neg using 1 <;> ring
  have lower := scalar_damped_upper_bound (fun s => -e s) (fun s => -R s)
    delta r epsilon T hr he.neg hneg
    (by change -e 0 ≤ delta; have h := (abs_le.mp hinitial).1; linarith)
    (by intro t ht; change -R t ≤ epsilon; have h := (abs_le.mp (hR t ht)).1; linarith)
  intro t ht
  exact abs_le.mpr ⟨by
    have h := lower t ht
    change -e t ≤ dampedEnvelope delta r epsilon t at h
    linarith, upper t ht⟩

#print scalar_damped_error_abs_bound
#print axioms scalar_damped_error_abs_bound

variable {ι : Type*} [Fintype ι]

/- The same time-indexed coefficient functions supply the detailed RHS and
   reduced source A. A state-dependent drive is not silently identified with
   an equal external current. Uniform coefficient budget/domain assumptions
   must be separately certified before using this finite-horizon result. -/
theorem finite_site_reduction_trajectory_error
    (N : ι → ℝ) (x a b c : ℝ → ι → ℝ) (qeff : ℝ → ℝ)
    (r delta epsilon T : ℝ) (_hT : 0 ≤ T) (hr : 0 < r)
    (_hdelta : 0 ≤ delta) (_hepsilon : 0 ≤ epsilon)
    (hN : ∀ i, 0 ≤ N i)
    (hx_cont : ∀ i, ContinuousOn (fun t => x t i) (Icc 0 T))
    (hq_cont : ContinuousOn qeff (Icc 0 T))
    (site_solution : ∀ t ∈ Ico 0 T, ∀ i,
      HasDerivWithinAt (fun s => x s i)
        (siteDerivative (a t i) (b t i) (c t i) (x t i)) (Ici t) t)
    (reduced_solution : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt qeff (totalSource N (a t) - r * qeff t) (Ici t) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T, rateResidualBudget N (a t) (b t) (c t) r ≤ epsilon)
    (initial_error : |totalAmount N (x 0) - qeff 0| ≤ delta) :
    ∀ t ∈ Icc 0 T,
      |totalAmount N (x t) - qeff t| ≤ dampedEnvelope delta r epsilon t := by
  let e : ℝ → ℝ := fun t => totalAmount N (x t) - qeff t
  let R : ℝ → ℝ := fun t => detailedAmountRate N (a t) (b t) (c t) (x t) -
    (totalSource N (a t) - r * totalAmount N (x t))
  have hQcont : ContinuousOn (fun t => totalAmount N (x t)) (Icc 0 T) := by
    simpa only [totalAmount] using
      (continuousOn_finset_sum Finset.univ (fun i _ => continuousOn_const.mul (hx_cont i)))
  have he : ContinuousOn e (Icc 0 T) := hQcont.sub hq_cont
  have hder : ∀ t ∈ Ico 0 T, HasDerivWithinAt e (R t - r * e t) (Ici t) t := by
    intro t ht
    have hQ : HasDerivWithinAt (fun s => totalAmount N (x s))
        (detailedAmountRate N (a t) (b t) (c t) (x t)) (Ici t) t := by
      simpa only [totalAmount, detailedAmountRate] using
        (HasDerivWithinAt.sum (u := Finset.univ)
          (fun i _ => (site_solution t ht i).const_mul (N i)))
    have h := hQ.sub (reduced_solution t ht)
    have identity : detailedAmountRate N (a t) (b t) (c t) (x t) -
        (totalSource N (a t) - r * qeff t) = R t - r * e t := by
      dsimp [R, e]
      ring
    rw [identity] at h
    exact h
  have hR : ∀ t ∈ Ico 0 T, |R t| ≤ epsilon := by
    intro t ht
    have hcc := Ico_subset_Icc_self ht
    exact (detailed_rate_residual_abs_bound N (a t) (b t) (c t) (x t) r
      hN (hx0 t hcc) (hx1 t hcc)).trans (coefficient_budget t hcc)
  exact scalar_damped_error_abs_bound e R delta r epsilon T hr he hder initial_error hR

#print finite_site_reduction_trajectory_error
#print axioms finite_site_reduction_trajectory_error

theorem finite_site_reduction_trajectory_error_at
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
  finite_site_reduction_trajectory_error N x a b c qeff r delta epsilon T hT hr hdelta hepsilon hN
    (fun i t ht => (site_solution t ht i).continuousAt.continuousWithinAt)
    (fun t ht => (reduced_solution t ht).continuousAt.continuousWithinAt)
    (fun t ht i => (site_solution t (Ico_subset_Icc_self ht) i).hasDerivWithinAt)
    (fun t ht => (reduced_solution t (Ico_subset_Icc_self ht)).hasDerivWithinAt)
    hx0 hx1 coefficient_budget initial_error

#print finite_site_reduction_trajectory_error_at
#print axioms finite_site_reduction_trajectory_error_at

/- Explicit nonempty physical coefficient/domain family. Two heterogeneous
   site rates 2 and 4 have a constant half-occupied solution; rbar=3, E=2. -/
noncomputable def equilibriumX : ℝ → Fin 2 → ℝ := fun _ _ => 1 / 2
def equilibriumQ : ℝ → ℝ := fun _ => 1

theorem heterogeneous_nonempty_trajectory_example (T : ℝ) (hT : 0 ≤ T) :
    ∀ t ∈ Icc 0 T, |totalAmount ceN (equilibriumX t) - equilibriumQ t| ≤
      dampedEnvelope 0 3 2 t := by
  have hsite : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => equilibriumX s i)
        (siteDerivative (ceA i) (ceB i) (ceC i) (equilibriumX t i)) t := by
    intro t _ i
    have hzero : siteDerivative (ceA i) (ceB i) (ceC i) (equilibriumX t i) = 0 := by
      dsimp [siteDerivative, ceB, ceC, equilibriumX]
      ring
    rw [hzero]
    exact hasDerivAt_const t (1 / 2 : ℝ)
  have hsource : totalSource ceN ceA = 3 := by
    norm_num [totalSource, ceN, ceA, Fin.sum_univ_two]
  have hq : ∀ t ∈ Icc 0 T,
      HasDerivAt equilibriumQ (totalSource ceN ceA - 3 * equilibriumQ t) t := by
    intro t _
    rw [hsource]
    simpa only [equilibriumQ, mul_one, sub_self] using hasDerivAt_const t (1 : ℝ)
  exact finite_site_reduction_trajectory_error_at ceN equilibriumX
    (fun _ => ceA) (fun _ => ceB) (fun _ => ceC) equilibriumQ 3 0 2 T hT
    (by norm_num) (by norm_num) (by norm_num) (by intro i; norm_num [ceN]) hsite hq
    (by intro t _ i; norm_num [equilibriumX])
    (by intro t _ i; norm_num [equilibriumX])
    (by intro t _; norm_num [rateResidualBudget, ceN, ceA, ceB, ceC, Fin.sum_univ_two])
    (by norm_num [totalAmount, ceN, equilibriumX, equilibriumQ, Fin.sum_univ_two])

#print heterogeneous_nonempty_trajectory_example
#print axioms heterogeneous_nonempty_trajectory_example

/- A distinct exact affine-feedback fixture, not the physical exponential
   voltage adapter: equal external balance and q need not give equal drive.
   Coefficients a_i(u)=u*ceA_i,b_i=ceB_i,c_i=0 use the actual site RHS. -/
def affineFeedbackBalance (u : ℝ) (x : Fin 2 → ℝ) : ℝ :=
  detailedAmountRate ceN (fun i => u * ceA i) ceB ceC x

theorem same_total_same_balance_different_feedback_drive :
    totalAmount ceN ceX = 1 ∧ totalAmount ceN ceZ = 1 ∧
    affineFeedbackBalance (7 / 5) ceX = 0 ∧
    affineFeedbackBalance (5 / 7) ceZ = 0 ∧
    (7 / 5 : ℝ) ≠ (5 / 7 : ℝ) := by
  norm_num [affineFeedbackBalance, totalAmount, detailedAmountRate, siteDerivative,
    ceN, ceA, ceB, ceC, ceX, ceZ, Fin.sum_univ_two]

#print same_total_same_balance_different_feedback_drive
#print axioms same_total_same_balance_different_feedback_drive

end Naheng.Reduction
