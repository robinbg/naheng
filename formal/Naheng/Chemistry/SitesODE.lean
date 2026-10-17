import Naheng.Chemistry.Sites
import Mathlib.Analysis.Calculus.MeanValue

open Set
open scoped Topology

namespace Naheng.Chemistry

/- The strict epsilon fences below use only the actual ODE and nonnegative
   coefficients. No range, boundary derivative conclusion, or representation
   of the desired trajectory is assumed. -/
theorem time_varying_site_invariant_right
    (a b c x : ℝ → ℝ) (T : ℝ)
    (hx : ContinuousOn x (Icc 0 T))
    (hode : ∀ t ∈ Ico 0 T,
      HasDerivWithinAt x (siteRate (a t) (b t) (c t) (x t)) (Ici t) t)
    (ha : ∀ t ∈ Icc 0 T, 0 ≤ a t)
    (hb : ∀ t ∈ Icc 0 T, 0 ≤ b t)
    (hc : ∀ t ∈ Icc 0 T, 0 ≤ c t)
    (hx0 : 0 ≤ x 0) (hx1 : x 0 ≤ 1) :
    ∀ t ∈ Icc 0 T, 0 ≤ x t ∧ x t ≤ 1 := by
  have upper : ∀ t ∈ Icc 0 T, ∀ ε > 0, x t ≤ 1 + ε * (t + 1) := by
    intro t ht ε hε
    apply image_le_of_deriv_right_lt_deriv_boundary hx hode
      (B := fun s => 1 + ε * (s + 1)) (B' := fun _ => ε)
    · linarith
    · intro s
      convert (hasDerivAt_const s (1 : ℝ)).add
        (((hasDerivAt_id s).add_const 1).const_mul ε) using 1 <;> simp
    · intro s hs hboundary
      have hscc := Ico_subset_Icc_self hs
      have hεs : 0 ≤ ε * (s + 1) := mul_nonneg (le_of_lt hε) (by linarith [hs.1])
      have h1 : a s * (1 - (1 + ε * (s + 1))) ≤ 0 :=
        mul_nonpos_of_nonneg_of_nonpos (ha s hscc) (by linarith)
      have h2 : 0 ≤ b s * (1 + ε * (s + 1)) :=
        mul_nonneg (hb s hscc) (by linarith)
      have h3 : 0 ≤ c s * (1 + ε * (s + 1)) :=
        mul_nonneg (hc s hscc) (by linarith)
      dsimp [siteRate]
      rw [hboundary]
      linarith
    · exact ht
  have lower : ∀ t ∈ Icc 0 T, ∀ ε > 0, -x t ≤ ε * (t + 1) := by
    intro t ht ε hε
    apply image_le_of_deriv_right_lt_deriv_boundary hx.neg
      (fun s hs => (hode s hs).neg)
      (B := fun s => ε * (s + 1)) (B' := fun _ => ε)
    · linarith
    · intro s
      convert ((hasDerivAt_id s).add_const 1).const_mul ε using 1 <;> simp
    · intro s hs hboundary
      have hscc := Ico_subset_Icc_self hs
      have hεs : 0 ≤ ε * (s + 1) := mul_nonneg (le_of_lt hε) (by linarith [hs.1])
      have hxs : x s ≤ 0 := by linarith
      have h1 : 0 ≤ a s * (1 - x s) :=
        mul_nonneg (ha s hscc) (by linarith)
      have h2 : b s * x s ≤ 0 := mul_nonpos_of_nonneg_of_nonpos (hb s hscc) hxs
      have h3 : c s * x s ≤ 0 := mul_nonpos_of_nonneg_of_nonpos (hc s hscc) hxs
      dsimp [siteRate]
      linarith
    · exact ht
  intro t ht
  have hupper : x t ≤ 1 := by
    have hcont : ContinuousWithinAt (fun ε : ℝ => 1 + ε * (t + 1)) (Ioi 0) 0 :=
      continuousWithinAt_const.add (continuousWithinAt_id.mul continuousWithinAt_const)
    convert continuousWithinAt_const.closure_le _ hcont (upper t ht) using 1 <;> simp
  have hlower : -x t ≤ 0 := by
    have hcont : ContinuousWithinAt (fun ε : ℝ => ε * (t + 1)) (Ioi 0) 0 :=
      continuousWithinAt_id.mul continuousWithinAt_const
    convert continuousWithinAt_const.closure_le _ hcont (lower t ht) using 1 <;> simp
  exact ⟨by linarith, hupper⟩

/- Intended finite-time ODE interface. Coefficient continuity is an explicit
   model regularity condition; the comparison argument actually needs only
   their pointwise nonnegativity once a differentiable trajectory is given.
   This establishes invariance of every supplied ODE solution, not existence,
   uniqueness, discretization accuracy, or physical-cell safety. -/
theorem time_varying_site_ode_invariant
    (a b c x : ℝ → ℝ) (T : ℝ) (_hT : 0 ≤ T)
    (_ha_cont : ContinuousOn a (Icc 0 T))
    (_hb_cont : ContinuousOn b (Icc 0 T))
    (_hc_cont : ContinuousOn c (Icc 0 T))
    (ha : ∀ t ∈ Icc 0 T, 0 ≤ a t)
    (hb : ∀ t ∈ Icc 0 T, 0 ≤ b t)
    (hc : ∀ t ∈ Icc 0 T, 0 ≤ c t)
    (hode : ∀ t ∈ Icc 0 T,
      HasDerivWithinAt x (siteRate (a t) (b t) (c t) (x t)) (Icc 0 T) t)
    (hx0 : 0 ≤ x 0) (hx1 : x 0 ≤ 1) :
    ∀ t ∈ Icc 0 T, 0 ≤ x t ∧ x t ≤ 1 := by
  apply time_varying_site_invariant_right a b c x T
    (fun t ht => (hode t ht).continuousWithinAt) _ ha hb hc hx0 hx1
  intro t ht
  exact (hode t (Ico_subset_Icc_self ht)).mono_of_mem_nhdsWithin
    (Icc_mem_nhdsGE_of_mem ht)

theorem time_varying_site_ode_invariant_at
    (a b c x : ℝ → ℝ) (T : ℝ) (hT : 0 ≤ T)
    (ha_cont : ContinuousOn a (Icc 0 T))
    (hb_cont : ContinuousOn b (Icc 0 T))
    (hc_cont : ContinuousOn c (Icc 0 T))
    (ha : ∀ t ∈ Icc 0 T, 0 ≤ a t)
    (hb : ∀ t ∈ Icc 0 T, 0 ≤ b t)
    (hc : ∀ t ∈ Icc 0 T, 0 ≤ c t)
    (hode : ∀ t ∈ Icc 0 T,
      HasDerivAt x (siteRate (a t) (b t) (c t) (x t)) t)
    (hx0 : 0 ≤ x 0) (hx1 : x 0 ≤ 1) :
    ∀ t ∈ Icc 0 T, 0 ≤ x t ∧ x t ≤ 1 :=
  time_varying_site_ode_invariant a b c x T hT ha_cont hb_cont hc_cont ha hb hc
    (fun t ht => (hode t ht).hasDerivWithinAt) hx0 hx1

end Naheng.Chemistry

