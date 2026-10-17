import Naheng.Aging.Film
import Mathlib.Data.Real.Sqrt
import Mathlib.Analysis.Calculus.Deriv.Inv

/- Constant-parameter diffusion limit and genuinely variable-coefficient
   primitive derivative. The separate SiteModel has no film-thickness state.
   No capacity, retirement or runtime applicability conclusion is assumed. -/
namespace Naheng.Aging.FilmLimits
open Set

private theorem sqrt_error_of_identity
    (A B l : ℝ) (hA : 0 ≤ A) (hB : 0 ≤ B) (hl : 0 ≤ l)
    (hid : l ^ 2 + 2 * A * l = B) :
    0 ≤ Real.sqrt B - l ∧ Real.sqrt B - l ≤ A := by
  have hs := Real.sqrt_nonneg B
  have hsq := Real.sq_sqrt hB
  have hlow : l ≤ Real.sqrt B := by
    by_contra hn
    have hlt : Real.sqrt B < l := lt_of_not_ge hn
    nlinarith [mul_nonneg hA hl]
  have hupp : Real.sqrt B ≤ l + A := by
    by_contra hn
    have hlt : l + A < Real.sqrt B := lt_of_not_ge hn
    nlinarith [sq_nonneg A]
  constructor <;> linarith

/- The sqrt trajectory and its absolute error are consequences of the ODE,
   not a sampled fit. At t=0 the absolute inequality still holds. -/
theorem constant_film_sqrt_trajectory_error
    (D k F T : ℝ) (hD : 0 < D) (hk : 0 < k) (hF : 0 < F)
    (hT : 0 ≤ T) (l : ℝ → ℝ) (hzero : l 0 = 0)
    (hl : ∀ t ∈ Icc 0 T, 0 ≤ l t)
    (hode : ∀ t ∈ Icc 0 T, HasDerivAt l (filmRate D k F 1 (l t)) t) :
    ∀ t ∈ Icc 0 T,
      0 ≤ Real.sqrt (2 * D * F * t) - l t ∧
      Real.sqrt (2 * D * F * t) - l t ≤ D / k := by
  intro t ht
  have hi := reaction_diffusion_film_integral_expanded D k F 1 T
    hD hk hF (by norm_num) hT l hl hode t ht
  rw [hzero] at hi
  simp only [sub_zero, zero_pow (by norm_num : 2 ≠ 0), mul_one] at hi
  have hid : (l t) ^ 2 + 2 * (D / k) * l t = 2 * D * F * t := by
    have he : 2 * D * (l t / k + (l t) ^ 2 / (2 * D)) = 2 * D * (F * t) :=
      congrArg (fun v : ℝ => 2 * D * v) hi
    field_simp [ne_of_gt hD, ne_of_gt hk] at he ⊢
    nlinarith [he]
  apply sqrt_error_of_identity (D / k) (2 * D * F * t) (l t)
  · exact div_nonneg hD.le hk.le
  · exact mul_nonneg (mul_nonneg (mul_nonneg (by norm_num) hD.le) hF.le) ht.1
  · exact hl t ht
  · exact hid

/- Explicit relative-validity condition: the constant absolute offset D/k
   must be small compared with the sqrt trajectory. No zero-time division. -/
theorem constant_film_sqrt_relative_error
    (D k F T : ℝ) (hD : 0 < D) (hk : 0 < k) (hF : 0 < F)
    (hT : 0 ≤ T) (l : ℝ → ℝ) (hzero : l 0 = 0)
    (hl : ∀ t ∈ Icc 0 T, 0 ≤ l t)
    (hode : ∀ t ∈ Icc 0 T, HasDerivAt l (filmRate D k F 1 (l t)) t)
    (t delta : ℝ) (ht : t ∈ Icc 0 T) (_hdelta : 0 ≤ delta)
    (hvalid : D / k ≤ delta * Real.sqrt (2 * D * F * t)) :
    0 ≤ Real.sqrt (2 * D * F * t) - l t ∧
      Real.sqrt (2 * D * F * t) - l t ≤ delta * Real.sqrt (2 * D * F * t) := by
  have h := constant_film_sqrt_trajectory_error D k F T hD hk hF hT l hzero hl hode t ht
  exact ⟨h.1, le_trans h.2 hvalid⟩

/- For D(T(t)), k(T(t)) and F(t)=Omega(t)*deltaC(t), the primitive
   has two coefficient-variation terms. F need not be constant. Its own
   derivative is not needed for this pointwise primitive identity. -/
theorem variable_film_primitive_derivative
    (D k F l : ℝ → ℝ) (dD dk t : ℝ)
    (hD : 0 < D t) (hk : 0 < k t) (hl : 0 ≤ l t)
    (hDderiv : HasDerivAt D dD t) (hkderiv : HasDerivAt k dk t)
    (hode : HasDerivAt l (filmRate (D t) (k t) (F t) 1 (l t)) t) :
    HasDerivAt (fun u => filmPrimitive (D u) (k u) (l u))
      (F t - l t * dk / (k t) ^ 2 - (l t) ^ 2 * dD / (2 * (D t) ^ 2)) t := by
  have hden := film_denominator_positive (D t) (k t) (l t) hD hk hl
  have htwo : 2 * D t ≠ 0 := mul_ne_zero (by norm_num) (ne_of_gt hD)
  have chain := (hode.div hkderiv (ne_of_gt hk)).add
    ((hode.mul hode).div (hDderiv.const_mul 2) htwo)
  change HasDerivAt (fun u => filmPrimitive (D u) (k u) (l u))
    ((filmRate (D t) (k t) (F t) 1 (l t) * k t - l t * dk) / (k t) ^ 2 +
      ((filmRate (D t) (k t) (F t) 1 (l t) * l t +
        l t * filmRate (D t) (k t) (F t) 1 (l t)) * (2 * D t) -
        (l t * l t) * (2 * dD)) / (2 * D t) ^ 2) t at chain
  have hlinear : D t + k t * l t ≠ 0 := ne_of_gt (by
    nlinarith [mul_nonneg hk.le hl])
  have hc :
    (filmRate (D t) (k t) (F t) 1 (l t) * k t - l t * dk) / (k t) ^ 2 +
      ((filmRate (D t) (k t) (F t) 1 (l t) * l t +
        l t * filmRate (D t) (k t) (F t) 1 (l t)) * (2 * D t) -
        (l t * l t) * (2 * dD)) / (2 * D t) ^ 2 =
      F t - l t * dk / (k t) ^ 2 - (l t) ^ 2 * dD / (2 * (D t) ^ 2) := by
    dsimp [filmRate]
    field_simp [ne_of_gt hD, ne_of_gt hk, ne_of_gt hden, hlinear]
    <;> ring
  rw [hc] at chain
  exact chain

end Naheng.Aging.FilmLimits
