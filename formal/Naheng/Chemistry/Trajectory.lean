import Naheng.Chemistry.Balance
import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Analysis.Calculus.Deriv.Mul

namespace Naheng.Chemistry
open scoped BigOperators

/- A differentiable solution of the declared reaction/port ODE. The derivative
   hypothesis concerns each species, not the desired weighted inventory result.
   Rates and ports may vary with time. Existence/uniqueness is not assumed proved. -/
def IsAmountTrajectory (n : ℝ → Inventory)
    (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux) : Prop :=
  ∀ t species, HasDerivAt (fun time => n time species)
    (amountRate (v t) (b t) species) t

theorem weighted_inventory_hasDerivAt (w : Species → ℝ)
    (balanced : ∀ reaction,
      (∑ species : Species, w species * stoichiometry species reaction) = 0)
    (n : ℝ → Inventory) (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux)
    (t : ℝ) (solution : IsAmountTrajectory n v b) :
    HasDerivAt (fun time => ∑ species : Species, w species * n time species)
      (∑ species : Species, w species * b t species) t := by
  have derivative :
      HasDerivAt (fun time => ∑ species : Species, w species * n time species)
        (∑ species : Species, w species * amountRate (v t) (b t) species) t := by
    simpa only using (HasDerivAt.sum (u := Finset.univ)
      (fun species _ => (solution t species).const_mul (w species)))
  rw [weighted_rate_from_ports w balanced (v t) (b t)] at derivative
  exact derivative

theorem element_inventory_hasDerivAt (element : Element)
    (n : ℝ → Inventory) (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux)
    (t : ℝ) (solution : IsAmountTrajectory n v b) :
    HasDerivAt (fun time => ∑ species : Species,
      composition element species * n time species)
      (∑ species : Species, composition element species * b t species) t := by
  exact weighted_inventory_hasDerivAt (composition element)
    (element_stoichiometry_balanced element) n v b t solution

theorem charge_inventory_hasDerivAt
    (n : ℝ → Inventory) (v : ℝ → Reaction → ℝ) (b : ℝ → PortFlux)
    (t : ℝ) (solution : IsAmountTrajectory n v b) :
    HasDerivAt (fun time => ∑ species : Species, charge species * n time species)
      (∑ species : Species, charge species * b t species) t := by
  exact weighted_inventory_hasDerivAt charge
    charge_stoichiometry_balanced n v b t solution

end Naheng.Chemistry
