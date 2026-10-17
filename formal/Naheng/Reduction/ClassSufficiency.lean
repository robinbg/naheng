import Naheng.Reduction.Exact
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.FinCases

/- A new finite-n necessary-and-sufficient classification for the original
   affine site RHS and the actual linear trapping output. Classical lumping,
   not a new natural law. Positive capacities and the full physical cube are
   explicit; no target equality, closure, or reduced ODE is an assumption. -/
namespace Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false

variable {ι κ : Type*} [Fintype ι] [DecidableEq ι]

def weightedReadout (N w x : ι → ℝ) : ℝ := ∑ i, N i * w i * x i
def PhysicalOccupation (x : ι → ℝ) : Prop := ∀ i, 0 ≤ x i ∧ x i ≤ 1
def singleSiteOccupation (i : ι) (v : ℝ) : ι → ℝ := fun j => if j = i then v else 0

theorem weighted_readout_single_site (N w : ι → ℝ) (i : ι) (v : ℝ) :
    weightedReadout N w (singleSiteOccupation i v) = N i * w i * v := by
  classical
  simp [weightedReadout, singleSiteOccupation, mul_ite]

theorem single_site_physical (i : ι) (v : ℝ) (hv0 : 0 ≤ v) (hv1 : v ≤ 1) :
    PhysicalOccupation (singleSiteOccupation i v) := by
  intro j
  by_cases h : j = i
  · simp [singleSiteOccupation, h, hv0, hv1]
  · simp [singleSiteOccupation, h]

section Classes
variable [Fintype κ] [DecidableEq κ]

def ClassReadoutSufficient (N : ι → ℝ) (group : ι → κ) (w : ι → ℝ) : Prop :=
  ∀ x z, PhysicalOccupation x → PhysicalOccupation z →
    (∀ k, classAmount N group x k = classAmount N group z k) →
    weightedReadout N w x = weightedReadout N w z

theorem class_amount_single_site (N : ι → ℝ) (group : ι → κ) (i : ι) (v : ℝ) (k : κ) :
    classAmount N group (singleSiteOccupation i v) k =
      if group i = k then N i * v else 0 := by
  classical
  simp [classAmount, singleSiteOccupation, mul_ite]

/- Necessity uses two genuine occupations in the physical cube, carrying
   equal positive mass in one class. Positive N prevents invisible sites. -/
theorem class_readout_sufficient_coefficients_necessary
    (N : ι → ℝ) (hN : ∀ i, 0 < N i) (group : ι → κ) (w : ι → ℝ)
    (sufficient : ClassReadoutSufficient N group w) :
    ∀ i j, group i = group j → w i = w j := by
  intro i j hgroup
  let s := N i + N j
  have hs : 0 < s := add_pos (hN i) (hN j)
  have hi0 : 0 ≤ N j / s := le_of_lt (div_pos (hN j) hs)
  have hj0 : 0 ≤ N i / s := le_of_lt (div_pos (hN i) hs)
  have hi1 : N j / s ≤ 1 := (div_le_one hs).2 (by dsimp [s]; linarith [hN i])
  have hj1 : N i / s ≤ 1 := (div_le_one hs).2 (by dsimp [s]; linarith [hN j])
  have same_class : ∀ k,
      classAmount N group (singleSiteOccupation i (N j / s)) k =
        classAmount N group (singleSiteOccupation j (N i / s)) k := by
    intro k
    rw [class_amount_single_site, class_amount_single_site, hgroup]
    split_ifs <;> ring
  have same_output := sufficient _ _ (single_site_physical i _ hi0 hi1)
    (single_site_physical j _ hj0 hj1) same_class
  rw [weighted_readout_single_site, weighted_readout_single_site] at same_output
  let mass := N i * N j / s
  have hmass : 0 < mass := div_pos (mul_pos (hN i) (hN j)) hs
  have product_equal : mass * w i = mass * w j := by
    calc
      mass * w i = N i * w i * (N j / s) := by dsimp [mass]; ring
      _ = N j * w j * (N i / s) := same_output
      _ = mass * w j := by dsimp [mass]; ring
  exact mul_left_cancel₀ (ne_of_gt hmass) product_equal

/- Sufficiency chooses a representative coefficient for each nonempty class
   and reuses the previously proved finite-site output factorization. -/
theorem class_readout_sufficient_of_shared_coefficients
    (N : ι → ℝ) (group : ι → κ) (w : ι → ℝ)
    (shared : ∀ i j, group i = group j → w i = w j) :
    ClassReadoutSufficient N group w := by
  classical
  let W : κ → ℝ := fun k => if h : ∃ i, group i = k then w (Classical.choose h) else 0
  have hw : ∀ i, w i = W (group i) := by
    intro i
    have he : ∃ j, group j = group i := ⟨i, rfl⟩
    dsimp [W]
    rw [dif_pos he]
    exact shared i (Classical.choose he) (Classical.choose_spec he).symm
  intro x z _ _ hq
  change trappedRate N w x = trappedRate N w z
  rw [class_shared_trapping_output N w x group W hw,
    class_shared_trapping_output N w z group W hw]
  apply Finset.sum_congr rfl
  intro k _
  rw [hq k]

theorem class_readout_sufficient_iff_shared_coefficients
    (N : ι → ℝ) (hN : ∀ i, 0 < N i) (group : ι → κ) (w : ι → ℝ) :
    ClassReadoutSufficient N group w ↔
      ∀ i j, group i = group j → w i = w j :=
  ⟨class_readout_sufficient_coefficients_necessary N hN group w,
    class_readout_sufficient_of_shared_coefficients N group w⟩

theorem detailed_rate_is_source_minus_weighted_readout (N a b c x : ι → ℝ) :
    detailedAmountRate N a b c x = totalSource N a -
      weightedReadout N (fun i => a i + b i + c i) x := by
  simp [detailedAmountRate, siteDerivative, totalSource, weightedReadout,
    mul_sub, mul_assoc, Finset.sum_sub_distrib]

def ClassRHSTrappingSufficient (N : ι → ℝ) (group : ι → κ) (a b c : ι → ℝ) : Prop :=
  ∀ x z, PhysicalOccupation x → PhysicalOccupation z →
    (∀ k, classAmount N group x k = classAmount N group z k) →
    detailedAmountRate N a b c x = detailedAmountRate N a b c z ∧
      trappedRate N c x = trappedRate N c z

/- Complete finite-n classification for the two requested instantaneous
   chemical outputs. a may remain heterogeneous; only r and c must share. -/
theorem class_rhs_trapping_sufficient_iff
    (N : ι → ℝ) (hN : ∀ i, 0 < N i) (group : ι → κ) (a b c : ι → ℝ) :
    ClassRHSTrappingSufficient N group a b c ↔
      ∀ i j, group i = group j →
        (a i + b i + c i = a j + b j + c j) ∧ c i = c j := by
  constructor
  · intro h
    have hr : ClassReadoutSufficient N group (fun i => a i + b i + c i) := by
      intro x z hx hz hq
      have hd := (h x z hx hz hq).1
      rw [detailed_rate_is_source_minus_weighted_readout,
        detailed_rate_is_source_minus_weighted_readout] at hd
      linarith only [hd]
    have hc : ClassReadoutSufficient N group c := by
      intro x z hx hz hq
      exact (h x z hx hz hq).2
    intro i j hg
    exact ⟨class_readout_sufficient_coefficients_necessary N hN group _ hr i j hg,
      class_readout_sufficient_coefficients_necessary N hN group c hc i j hg⟩
  · intro h
    have hr := class_readout_sufficient_of_shared_coefficients N group
      (fun i => a i + b i + c i) (fun i j hg => (h i j hg).1)
    have hc := class_readout_sufficient_of_shared_coefficients N group c
      (fun i j hg => (h i j hg).2)
    intro x z hx hz hq
    constructor
    · rw [detailed_rate_is_source_minus_weighted_readout,
        detailed_rate_is_source_minus_weighted_readout, hr x z hx hz hq]
    · exact hc x z hx hz hq

/- Constructive non-sufficiency: a differing within-class coefficient cannot
   be masked by total/class-state equality on the physical cube. -/
theorem differing_class_coefficient_has_physical_witness
    (N : ι → ℝ) (hN : ∀ i, 0 < N i) (group : ι → κ) (w : ι → ℝ)
    (i j : ι) (hg : group i = group j) (hw : w i ≠ w j) :
    ∃ x z, PhysicalOccupation x ∧ PhysicalOccupation z ∧
      (∀ k, classAmount N group x k = classAmount N group z k) ∧
      weightedReadout N w x ≠ weightedReadout N w z := by
  classical
  by_contra no_witness
  apply hw
  apply class_readout_sufficient_coefficients_necessary N hN group w _ i j hg
  intro x z hx hz hq
  by_contra different
  exact no_witness ⟨x, z, hx, hz, hq, different⟩

end Classes

theorem total_rhs_trapping_sufficient_iff
    (N : ι → ℝ) (hN : ∀ i, 0 < N i) (a b c : ι → ℝ) :
    (∀ x z, PhysicalOccupation x → PhysicalOccupation z →
      totalAmount N x = totalAmount N z →
      detailedAmountRate N a b c x = detailedAmountRate N a b c z ∧
        trappedRate N c x = trappedRate N c z) ↔
      ∀ i j, (a i + b i + c i = a j + b j + c j) ∧ c i = c j := by
  simpa [ClassRHSTrappingSufficient, classAmount, totalAmount] using
    class_rhs_trapping_sufficient_iff N hN (fun _ => ()) a b c

def fourSiteN : Fin 4 → ℝ := fun i => if i.val = 0 then 1 else if i.val = 1 then 2 else if i.val = 2 then 3 else 4
def fourSiteGroup : Fin 4 → Fin 2 := fun i => if i.val < 2 then 0 else 1
noncomputable def fourSiteA : Fin 4 → ℝ := fun i => if i.val = 0 then 1 else if i.val = 1 then 3/2 else if i.val = 2 then 2 else 3
noncomputable def fourSiteB : Fin 4 → ℝ := fun i => if i.val = 0 then 3/2 else if i.val = 1 then 1 else if i.val = 2 then 2 else 1
noncomputable def fourSiteC : Fin 4 → ℝ := fun i => if i.val < 2 then 1/2 else 1
noncomputable def fourSiteX : Fin 4 → ℝ := fun i => if i.val = 0 then 1/4 else if i.val = 1 then 3/4 else if i.val = 2 then 1/5 else 3/5

/- Positive capacities and rates, heterogeneous sources within each class,
   distinct class r/c, four physical occupations -> two sufficient amounts.
   This witnesses actual rank reduction; it is not a fitted battery. -/
theorem four_to_two_class_sufficiency_example :
    (∀ i, 0 < fourSiteN i ∧ 0 < fourSiteA i ∧ 0 < fourSiteB i ∧ 0 < fourSiteC i) ∧
    ClassRHSTrappingSufficient fourSiteN fourSiteGroup fourSiteA fourSiteB fourSiteC ∧
    Fintype.card (Fin 2) < Fintype.card (Fin 4) := by
  have hN : ∀ i, 0 < fourSiteN i := by
    intro i; fin_cases i <;> norm_num [fourSiteN]
  refine ⟨?_, (class_rhs_trapping_sufficient_iff _ hN _ _ _ _).2 ?_, by decide⟩
  · intro i
    fin_cases i <;> norm_num [fourSiteN, fourSiteA, fourSiteB, fourSiteC]
  · intro i j hg
    fin_cases i <;> fin_cases j <;>
      norm_num [fourSiteGroup, fourSiteA, fourSiteB, fourSiteC] at hg ⊢

theorem four_to_two_actual_outputs_example :
    (∀ i, 0 < fourSiteX i ∧ fourSiteX i < 1) ∧
    classAmount fourSiteN fourSiteGroup fourSiteX 0 = (7/4 : ℝ) ∧
    classAmount fourSiteN fourSiteGroup fourSiteX 1 = (3 : ℝ) ∧
    detailedAmountRate fourSiteN fourSiteA fourSiteB fourSiteC fourSiteX = (7/4 : ℝ) ∧
    trappedRate fourSiteN fourSiteC fourSiteX = (31/8 : ℝ) := by
  constructor
  · intro i; fin_cases i <;> norm_num [fourSiteX]
  · norm_num [classAmount, detailedAmountRate, trappedRate, siteDerivative,
      fourSiteN, fourSiteGroup, fourSiteA, fourSiteB, fourSiteC, fourSiteX,
      Finset.sum_filter, Fin.sum_univ_succ]

theorem four_to_two_total_only_insufficient_example :
    ¬ (∀ x z, PhysicalOccupation x → PhysicalOccupation z →
      totalAmount fourSiteN x = totalAmount fourSiteN z →
      detailedAmountRate fourSiteN fourSiteA fourSiteB fourSiteC x =
        detailedAmountRate fourSiteN fourSiteA fourSiteB fourSiteC z ∧
      trappedRate fourSiteN fourSiteC x = trappedRate fourSiteN fourSiteC z) := by
  intro h
  have hN := fun i => (four_to_two_class_sufficiency_example.1 i).1
  have shared := (total_rhs_trapping_sufficient_iff fourSiteN hN fourSiteA fourSiteB fourSiteC).1 h
  have impossible := (shared 0 2).1
  norm_num [fourSiteA, fourSiteB, fourSiteC] at impossible

end Naheng.Reduction

#print Naheng.Reduction.weighted_readout_single_site
#print axioms Naheng.Reduction.weighted_readout_single_site
#print Naheng.Reduction.single_site_physical
#print axioms Naheng.Reduction.single_site_physical
#print Naheng.Reduction.class_amount_single_site
#print axioms Naheng.Reduction.class_amount_single_site
#print Naheng.Reduction.class_readout_sufficient_coefficients_necessary
#print axioms Naheng.Reduction.class_readout_sufficient_coefficients_necessary
#print Naheng.Reduction.class_readout_sufficient_of_shared_coefficients
#print axioms Naheng.Reduction.class_readout_sufficient_of_shared_coefficients
#print Naheng.Reduction.class_readout_sufficient_iff_shared_coefficients
#print axioms Naheng.Reduction.class_readout_sufficient_iff_shared_coefficients
#print Naheng.Reduction.detailed_rate_is_source_minus_weighted_readout
#print axioms Naheng.Reduction.detailed_rate_is_source_minus_weighted_readout
#print Naheng.Reduction.class_rhs_trapping_sufficient_iff
#print axioms Naheng.Reduction.class_rhs_trapping_sufficient_iff
#print Naheng.Reduction.differing_class_coefficient_has_physical_witness
#print axioms Naheng.Reduction.differing_class_coefficient_has_physical_witness
#print Naheng.Reduction.total_rhs_trapping_sufficient_iff
#print axioms Naheng.Reduction.total_rhs_trapping_sufficient_iff
#print Naheng.Reduction.four_to_two_class_sufficiency_example
#print axioms Naheng.Reduction.four_to_two_class_sufficiency_example
#print Naheng.Reduction.four_to_two_actual_outputs_example
#print axioms Naheng.Reduction.four_to_two_actual_outputs_example
#print Naheng.Reduction.four_to_two_total_only_insufficient_example
#print axioms Naheng.Reduction.four_to_two_total_only_insufficient_example
