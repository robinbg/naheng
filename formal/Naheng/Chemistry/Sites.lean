import Mathlib.Data.Complex.Exponential
import Mathlib.Tactic.Linarith

namespace Naheng.Chemistry

def siteRate (a b c x : ℝ) : ℝ := a * (1 - x) - b * x - c * x

theorem site_lower_boundary (a b c : ℝ) (ha : 0 ≤ a) : 0 ≤ siteRate a b c 0 := by
  simpa [siteRate] using ha

theorem site_upper_boundary (a b c : ℝ) (hb : 0 ≤ b) (hc : 0 ≤ c) :
    siteRate a b c 1 ≤ 0 := by
  simp only [siteRate]
  nlinarith

/- Exact constant-rate representation. This theorem proves the declared curve
   stays in [0,1]. It does not establish arbitrary time-varying ODE invariance. -/
noncomputable def constantRateTrajectory (a b c x0 t : ℝ) : ℝ :=
  let r := a + b + c
  (1 - Real.exp (-r * t)) * (a / r) + Real.exp (-r * t) * x0

theorem constant_rate_trajectory_invariant (a b c x0 t : ℝ)
    (ha : 0 ≤ a) (hb : 0 ≤ b) (hc : 0 ≤ c)
    (hr : 0 < a + b + c) (hxlo : 0 ≤ x0) (hxhi : x0 ≤ 1) (ht : 0 ≤ t) :
    0 ≤ constantRateTrajectory a b c x0 t ∧
      constantRateTrajectory a b c x0 t ≤ 1 := by
  have helo : 0 ≤ Real.exp (-(a + b + c) * t) := le_of_lt (Real.exp_pos _)
  have hehi : Real.exp (-(a + b + c) * t) ≤ 1 := by
    apply Real.exp_le_one_iff.mpr
    nlinarith
  have heqlo : 0 ≤ a / (a + b + c) := div_nonneg ha (le_of_lt hr)
  have heqhi : a / (a + b + c) ≤ 1 := by
    apply (div_le_one hr).mpr
    linarith
  dsimp [constantRateTrajectory]
  constructor
  · exact add_nonneg (mul_nonneg (sub_nonneg.mpr hehi) heqlo) (mul_nonneg helo hxlo)
  · have h1 := mul_le_mul_of_nonneg_left heqhi (sub_nonneg.mpr hehi)
    have h2 := mul_le_mul_of_nonneg_left hxhi helo
    nlinarith

end Naheng.Chemistry
