import Naheng.Chemistry.Reaction
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Algebra.BigOperators.Group.Finset.Sigma

namespace Naheng.Chemistry
open scoped BigOperators

/- Algebraic instantaneous mass balance. Differentiable trajectories and their
   existence are separate obligations; this result alone is not an ODE theorem. -/
def amountRate (v : Reaction → ℝ) (b : PortFlux) : Inventory :=
  fun species => (∑ reaction : Reaction, stoichiometry species reaction * v reaction) + b species

theorem weighted_rate_from_ports (w : Species → ℝ)
    (balanced : ∀ reaction, (∑ species : Species, w species * stoichiometry species reaction) = 0)
    (v : Reaction → ℝ) (b : PortFlux) :
    (∑ species : Species, w species * amountRate v b species) =
      ∑ species : Species, w species * b species := by
  simp only [amountRate, mul_add, Finset.sum_add_distrib, Finset.mul_sum]
  have internal_zero :
      (∑ species : Species, ∑ reaction : Reaction,
        w species * (stoichiometry species reaction * v reaction)) = 0 := by
    rw [Finset.sum_comm]
    apply Finset.sum_eq_zero
    intro reaction _
    simp only [← mul_assoc, ← Finset.sum_mul, balanced, zero_mul]
  rw [internal_zero, zero_add]

theorem element_rate_from_ports (element : Element) (v : Reaction → ℝ) (b : PortFlux) :
    (∑ species : Species, composition element species * amountRate v b species) =
      ∑ species : Species, composition element species * b species := by
  exact weighted_rate_from_ports (composition element)
    (element_stoichiometry_balanced element) v b

theorem charge_rate_from_ports (v : Reaction → ℝ) (b : PortFlux) :
    (∑ species : Species, charge species * amountRate v b species) =
      ∑ species : Species, charge species * b species := by
  exact weighted_rate_from_ports charge charge_stoichiometry_balanced v b

end Naheng.Chemistry
