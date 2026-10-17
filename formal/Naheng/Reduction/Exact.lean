import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Analysis.Calculus.Deriv.Mul
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Algebra.BigOperators.Group.Finset.Sigma
import Mathlib.Algebra.BigOperators.Fin
import Mathlib.Tactic.Ring
import Mathlib.Tactic.NormNum

namespace Naheng.Reduction
open scoped BigOperators

variable {ι κ : Type*} [Fintype ι]

def siteDerivative (a b c x : ℝ) : ℝ := a - (a + b + c) * x

def totalAmount (N x : ι → ℝ) : ℝ := ∑ i, N i * x i

def totalSource (N a : ι → ℝ) : ℝ := ∑ i, N i * a i

def detailedAmountRate (N a b c x : ι → ℝ) : ℝ :=
  ∑ i, N i * siteDerivative (a i) (b i) (c i) (x i)

def trappedRate (N c x : ι → ℝ) : ℝ := ∑ i, N i * c i * x i

def IsSiteTrajectory (x a b c : ℝ → ι → ℝ) : Prop :=
  ∀ t i, HasDerivAt (fun s => x s i) (siteDerivative (a t i) (b t i) (c t i) (x t i)) t

theorem shared_total_rate_exact (N a b c x : ι → ℝ) (r : ℝ)
    (shared : ∀ i, a i + b i + c i = r) :
    detailedAmountRate N a b c x = totalSource N a - r * totalAmount N x := by
  simp only [detailedAmountRate, siteDerivative, totalSource, totalAmount, mul_sub,
    Finset.sum_sub_distrib, Finset.mul_sum]
  congr 1
  apply Finset.sum_congr rfl
  intro i _
  rw [shared i]
  ring

/- Real trajectory theorem. The hypothesis is per-site ODE compliance; it
   does not assume the desired aggregate derivative. Positive capacities and
   nonnegative rates are explicit physical conditions, although the algebraic
   identity itself holds over all real coefficients. Same external input is
   represented by the common time argument, not an unstated current feedback. -/
theorem shared_total_rate_hasDerivAt (N : ι → ℝ) (_hN : ∀ i, 0 < N i)
    (x a b c : ℝ → ι → ℝ) (r : ℝ → ℝ)
    (_ha : ∀ t i, 0 ≤ a t i) (_hb : ∀ t i, 0 ≤ b t i) (_hc : ∀ t i, 0 ≤ c t i)
    (shared : ∀ t i, a t i + b t i + c t i = r t)
    (solution : IsSiteTrajectory x a b c) (t : ℝ) :
    HasDerivAt (fun s => totalAmount N (x s))
      (totalSource N (a t) - r t * totalAmount N (x t)) t := by
  have derivative : HasDerivAt (fun s => totalAmount N (x s))
      (detailedAmountRate N (a t) (b t) (c t) (x t)) t := by
    simpa only [totalAmount, detailedAmountRate] using
      (HasDerivAt.sum (u := Finset.univ) (fun i _ => (solution t i).const_mul (N i)))
  rw [shared_total_rate_exact N (a t) (b t) (c t) (x t) (r t) (shared t)] at derivative
  exact derivative

section Groups
variable [Fintype κ] [DecidableEq κ]

def classAmount (N : ι → ℝ) (group : ι → κ) (x : ι → ℝ) (k : κ) : ℝ :=
  ∑ i ∈ Finset.univ.filter (fun i => group i = k), N i * x i

def classSource (N : ι → ℝ) (group : ι → κ) (a : ι → ℝ) (k : κ) : ℝ :=
  ∑ i ∈ Finset.univ.filter (fun i => group i = k), N i * a i

theorem class_shared_total_rate_hasDerivAt
    (N : ι → ℝ) (_hN : ∀ i, 0 < N i) (group : ι → κ)
    (x a b c : ℝ → ι → ℝ) (r : ℝ → κ → ℝ)
    (shared : ∀ t i, a t i + b t i + c t i = r t (group i))
    (solution : IsSiteTrajectory x a b c) (t : ℝ) (k : κ) :
    HasDerivAt (fun s => classAmount N group (x s) k)
      (classSource N group (a t) k - r t k * classAmount N group (x t) k) t := by
  have derivative : HasDerivAt (fun s => classAmount N group (x s) k)
      (∑ i ∈ Finset.univ.filter (fun i => group i = k),
        N i * siteDerivative (a t i) (b t i) (c t i) (x t i)) t := by
    simpa only [classAmount] using
      (HasDerivAt.sum (u := Finset.univ.filter (fun i => group i = k))
        (fun i _ => (solution t i).const_mul (N i)))
  have identity : (∑ i ∈ Finset.univ.filter (fun i => group i = k),
      N i * siteDerivative (a t i) (b t i) (c t i) (x t i)) =
      classSource N group (a t) k - r t k * classAmount N group (x t) k := by
    simp only [classSource, classAmount, siteDerivative, mul_sub,
      Finset.sum_sub_distrib, Finset.mul_sum]
    congr 1
    apply Finset.sum_congr rfl
    intro i hi
    have hgroup := (Finset.mem_filter.mp hi).2
    rw [shared t i, hgroup]
    ring
  rw [identity] at derivative
  exact derivative

theorem class_shared_trapping_output (N c x : ι → ℝ) (group : ι → κ)
    (cClass : κ → ℝ) (shared : ∀ i, c i = cClass (group i)) :
    trappedRate N c x = ∑ k, cClass k * classAmount N group x k := by
  classical
  calc
    trappedRate N c x = ∑ i, cClass (group i) * (N i * x i) := by
      apply Finset.sum_congr rfl
      intro i _
      rw [shared i]
      ring
    _ = ∑ k, cClass k * classAmount N group x k := by
      symm
      simp only [classAmount, Finset.mul_sum, Finset.sum_filter, mul_ite, mul_zero]
      rw [Finset.sum_comm]
      simp

theorem class_shared_trapping_hasDerivAt (N : ι → ℝ) (group : ι → κ)
    (c x : ℝ → ι → ℝ) (cClass : ℝ → κ → ℝ) (y : ℝ → ℝ)
    (shared : ∀ t i, c t i = cClass t (group i))
    (side_solution : ∀ t, HasDerivAt y (trappedRate N (c t) (x t)) t) (t : ℝ) :
    HasDerivAt y (∑ k, cClass t k * classAmount N group (x t) k) t := by
  have derivative := side_solution t
  rw [class_shared_trapping_output N (c t) (x t) group (cClass t) (shared t)] at derivative
  exact derivative

end Groups

/- Exact rational regression witnesses, not measurements or new discoveries.
   Equal total amount does not determine the detailed aggregate derivative. -/
def ceN : Fin 2 → ℝ := fun _ => 1
def ceA : Fin 2 → ℝ := fun i => if i = 0 then 1 else 2
def ceB : Fin 2 → ℝ := ceA
def ceC : Fin 2 → ℝ := fun _ => 0
noncomputable def ceX : Fin 2 → ℝ := fun i => if i = 0 then 1 / 4 else 3 / 4
noncomputable def ceZ : Fin 2 → ℝ := fun i => if i = 0 then 3 / 4 else 1 / 4

theorem equal_total_different_rate_counterexample :
    totalAmount ceN ceX = 1 ∧ totalAmount ceN ceZ = 1 ∧
    detailedAmountRate ceN ceA ceB ceC ceX = -(1 / 2 : ℝ) ∧
    detailedAmountRate ceN ceA ceB ceC ceZ = (1 / 2 : ℝ) := by
  norm_num [totalAmount, detailedAmountRate, siteDerivative, ceN, ceA, ceB, ceC,
    ceX, ceZ, Fin.sum_univ_two]

/- Even when r is common and q dynamics closes, different c destroys
   side-output sufficiency. Both states have q=1 and q'=0, but y' differs. -/
def sideA : Fin 2 → ℝ := fun _ => 1
def sideB : Fin 2 → ℝ := fun i => if i = 0 then 1 else 0
def sideC : Fin 2 → ℝ := fun i => if i = 0 then 0 else 1

theorem common_total_rate_different_trapping_counterexample :
    (∀ i, sideA i + sideB i + sideC i = 2) ∧
    totalAmount ceN ceX = 1 ∧ totalAmount ceN ceZ = 1 ∧
    detailedAmountRate ceN sideA sideB sideC ceX = 0 ∧
    detailedAmountRate ceN sideA sideB sideC ceZ = 0 ∧
    trappedRate ceN sideC ceX = (3 / 4 : ℝ) ∧
    trappedRate ceN sideC ceZ = (1 / 4 : ℝ) := by
  constructor
  · intro i
    by_cases h : i = 0 <;> norm_num [sideA, sideB, sideC, h]
  · norm_num [totalAmount, detailedAmountRate, trappedRate, siteDerivative,
      ceN, sideA, sideB, sideC, ceX, ceZ, Fin.sum_univ_two]

end Naheng.Reduction

