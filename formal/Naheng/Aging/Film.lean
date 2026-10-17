import Mathlib.Analysis.Calculus.MeanValue
import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Analysis.Calculus.Deriv.Mul
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith

namespace Naheng.Aging
open Set
open scoped Topology

noncomputable def filmRate (D k Omega deltaC thickness : ℝ) : ℝ :=
  Omega * deltaC / (1 / k + thickness / D)

noncomputable def filmPrimitive (D k thickness : ℝ) : ℝ :=
  thickness / k + thickness * thickness / (2 * D)

theorem film_denominator_positive (D k thickness : ℝ)
    (hD : 0 < D) (hk : 0 < k) (hl : 0 ≤ thickness) :
    0 < 1 / k + thickness / D :=
  add_pos_of_pos_of_nonneg (one_div_pos.mpr hk) (div_nonneg hl hD.le)

theorem filmPrimitive_hasDerivWithinAt
    (D k Omega deltaC : ℝ) (hD : 0 < D) (hk : 0 < k)
    (l : ℝ → ℝ) (s : Set ℝ) (t : ℝ) (hl : 0 ≤ l t)
    (hode : HasDerivWithinAt l (filmRate D k Omega deltaC (l t)) s t) :
    HasDerivWithinAt (fun u => filmPrimitive D k (l u)) (Omega * deltaC) s t := by
  have chain : HasDerivWithinAt (fun u => filmPrimitive D k (l u))
      (filmRate D k Omega deltaC (l t) / k +
        (filmRate D k Omega deltaC (l t) * l t +
          l t * filmRate D k Omega deltaC (l t)) / (2 * D)) s t := by
    simpa only [filmPrimitive] using (hode.div_const k).add ((hode.mul hode).div_const (2 * D))
  have hden := film_denominator_positive D k (l t) hD hk hl
  have hlinear : D + k * l t ≠ 0 := ne_of_gt (by
    have hm : 0 ≤ k * l t := mul_nonneg hk.le hl
    linarith)
  have coefficient : filmRate D k Omega deltaC (l t) / k +
      (filmRate D k Omega deltaC (l t) * l t +
        l t * filmRate D k Omega deltaC (l t)) / (2 * D) = Omega * deltaC := by
    dsimp [filmRate]
    field_simp [ne_of_gt hD, ne_of_gt hk, ne_of_gt hden, hlinear]
    <;> ring
  rw [coefficient] at chain
  exact chain

/- The time domain is a finite forward interval. Assuming global nonnegative
   thickness on all real times together with positive growth would be an
   inappropriate applicability domain. No integral conclusion is a premise. -/
theorem reaction_diffusion_film_integral_within
    (D k Omega deltaC T : ℝ) (hD : 0 < D) (hk : 0 < k)
    (_hOmega : 0 < Omega) (_hdeltaC : 0 < deltaC) (hT : 0 ≤ T)
    (l : ℝ → ℝ) (hl : ∀ t ∈ Icc 0 T, 0 ≤ l t)
    (hode : ∀ t ∈ Icc 0 T,
      HasDerivWithinAt l (filmRate D k Omega deltaC (l t)) (Icc 0 T) t) :
    ∀ t ∈ Icc 0 T,
      filmPrimitive D k (l t) - filmPrimitive D k (l 0) = Omega * deltaC * t := by
  let g : ℝ → ℝ := fun t => filmPrimitive D k (l t) - Omega * deltaC * t
  have zero_derivative : ∀ t ∈ Icc 0 T, HasDerivWithinAt g 0 (Icc 0 T) t := by
    intro t ht
    have hp := filmPrimitive_hasDerivWithinAt D k Omega deltaC hD hk l (Icc 0 T) t
      (hl t ht) (hode t ht)
    simpa only [g, mul_one, sub_self] using
      hp.sub ((hasDerivWithinAt_id t (Icc 0 T)).const_mul (Omega * deltaC))
  intro t ht
  have h0 : (0 : ℝ) ∈ Icc 0 T := ⟨le_rfl, hT⟩
  have norm_bound : ‖g t - g 0‖ ≤ 0 := by
    simpa using Convex.norm_image_sub_le_of_norm_hasDerivWithin_le
      (C := 0) zero_derivative (fun u _ => by simp) (convex_Icc (0 : ℝ) T) h0 ht
  have same : g t - g 0 = 0 := norm_eq_zero.mp
    (le_antisymm norm_bound (norm_nonneg _))
  dsimp [g] at same
  simp only [mul_zero, sub_zero] at same
  linarith

theorem reaction_diffusion_film_integral_at
    (D k Omega deltaC T : ℝ) (hD : 0 < D) (hk : 0 < k)
    (hOmega : 0 < Omega) (hdeltaC : 0 < deltaC) (hT : 0 ≤ T)
    (l : ℝ → ℝ) (hl : ∀ t ∈ Icc 0 T, 0 ≤ l t)
    (hode : ∀ t ∈ Icc 0 T,
      HasDerivAt l (filmRate D k Omega deltaC (l t)) t) :
    ∀ t ∈ Icc 0 T,
      filmPrimitive D k (l t) - filmPrimitive D k (l 0) = Omega * deltaC * t :=
  reaction_diffusion_film_integral_within D k Omega deltaC T hD hk hOmega hdeltaC hT l hl
    (fun t ht => (hode t ht).hasDerivWithinAt)

theorem reaction_diffusion_film_integral_expanded
    (D k Omega deltaC T : ℝ) (hD : 0 < D) (hk : 0 < k)
    (hOmega : 0 < Omega) (hdeltaC : 0 < deltaC) (hT : 0 ≤ T)
    (l : ℝ → ℝ) (hl : ∀ t ∈ Icc 0 T, 0 ≤ l t)
    (hode : ∀ t ∈ Icc 0 T,
      HasDerivAt l (filmRate D k Omega deltaC (l t)) t) :
    ∀ t ∈ Icc 0 T,
      (l t - l 0) / k + ((l t) ^ 2 - (l 0) ^ 2) / (2 * D) = Omega * deltaC * t := by
  intro t ht
  calc
    (l t - l 0) / k + ((l t) ^ 2 - (l 0) ^ 2) / (2 * D) =
        filmPrimitive D k (l t) - filmPrimitive D k (l 0) := by
      simp only [filmPrimitive, pow_two, sub_div]
      ring
    _ = Omega * deltaC * t :=
      reaction_diffusion_film_integral_at D k Omega deltaC T hD hk hOmega hdeltaC hT l hl hode t ht

end Naheng.Aging

