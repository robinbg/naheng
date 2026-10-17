import Naheng.Chemistry.Trajectory
import Mathlib.Analysis.Calculus.MeanValue

namespace Naheng.Chemistry
open scoped BigOperators

/- Conservation along a differentiable solution of the declared reaction ODE.
   Internal rates may depend arbitrarily on time. Closed ports and balanced
   stoichiometry imply a zero derivative of the inventory; constancy is then a
   consequence of the mean value theorem, not an additional assumption.

   The solution hypothesis holds at every real time. This theorem does not
   establish existence, uniqueness, nonnegativity, or a floating-point solver's
   compliance with that hypothesis. -/
theorem weighted_inventory_time_invariant (w : Species → ℝ)
    (balanced : ∀ reaction,
      (∑ species : Species, w species * stoichiometry species reaction) = 0)
    (n : ℝ → Inventory) (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux)
    (solution : IsAmountTrajectory n v b)
    (closed : ∀ time species, b time species = 0) (t₀ t : ℝ) :
    (∑ species : Species, w species * n t species) =
      ∑ species : Species, w species * n t₀ species := by
  have zero_derivative (time : ℝ) :
      HasDerivAt (fun s => ∑ species : Species, w species * n s species) 0 time := by
    have derivative := weighted_inventory_hasDerivAt w balanced n v b time solution
    have port_zero : (∑ species : Species, w species * b time species) = 0 := by
      apply Finset.sum_eq_zero
      intro species _
      rw [closed time species, mul_zero]
    rw [port_zero] at derivative
    exact derivative
  exact is_const_of_deriv_eq_zero
    (fun time => (zero_derivative time).differentiableAt)
    (fun time => (zero_derivative time).deriv) t t₀

theorem element_inventory_time_invariant (element : Element)
    (n : ℝ → Inventory) (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux)
    (solution : IsAmountTrajectory n v b)
    (closed : ∀ time species, b time species = 0) (t₀ t : ℝ) :
    (∑ species : Species, composition element species * n t species) =
      ∑ species : Species, composition element species * n t₀ species := by
  exact weighted_inventory_time_invariant (composition element)
    (element_stoichiometry_balanced element) n v b solution closed t₀ t

theorem charge_inventory_time_invariant
    (n : ℝ → Inventory) (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux)
    (solution : IsAmountTrajectory n v b)
    (closed : ∀ time species, b time species = 0) (t₀ t : ℝ) :
    (∑ species : Species, charge species * n t species) =
      ∑ species : Species, charge species * n t₀ species := by
  exact weighted_inventory_time_invariant charge
    charge_stoichiometry_balanced n v b solution closed t₀ t

end Naheng.Chemistry
