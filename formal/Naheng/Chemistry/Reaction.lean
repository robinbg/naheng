import Naheng.Chemistry.Species
import Mathlib.Algebra.BigOperators.Group.Finset.Basic
import Mathlib.Tactic.NormNum

namespace Naheng.Chemistry
open scoped BigOperators

inductive Reaction
  | insertion | extraction | trapping
  deriving DecidableEq, Fintype

private theorem species_univ : (Finset.univ : Finset Species) =
    {.sodiumIon, .electron, .vacantSite, .occupiedSite, .trappedProduct} := by
  ext species
  cases species <;> simp

/- Positive entries are products, negative entries are consumed reactants.
   Na+ + e- + vacant <-> occupied; occupied -> vacant + trapped.
   This is an effective bookkeeping system, not an identified commercial cell. -/
def stoichiometry : Species → Reaction → ℝ
  | .sodiumIon, .insertion => -1
  | .electron, .insertion => -1
  | .vacantSite, .insertion => -1
  | .occupiedSite, .insertion => 1
  | .sodiumIon, .extraction => 1
  | .electron, .extraction => 1
  | .vacantSite, .extraction => 1
  | .occupiedSite, .extraction => -1
  | .occupiedSite, .trapping => -1
  | .vacantSite, .trapping => 1
  | .trappedProduct, .trapping => 1
  | _, _ => 0

theorem element_stoichiometry_balanced (element : Element) (reaction : Reaction) :
    (∑ species : Species, composition element species * stoichiometry species reaction) = 0 := by
  cases element <;> cases reaction <;>
    simp [species_univ, Finset.sum_insert, Finset.sum_singleton, composition, stoichiometry]

theorem charge_stoichiometry_balanced (reaction : Reaction) :
    (∑ species : Species, charge species * stoichiometry species reaction) = 0 := by
  cases reaction <;>
    simp [species_univ, Finset.sum_insert, Finset.sum_singleton, charge, stoichiometry]

end Naheng.Chemistry
