import Mathlib.Data.Real.Basic
import Mathlib.Tactic.DeriveFintype

/- Abstract species for the synthetic reaction-site fixture.
   trappedProduct is an effective neutral Na-containing category, not measured SEI.
   Amounts are in mol; compositions are mol element / mol species.
   Electron charge is counted explicitly; open ports are retained. -/
namespace Naheng.Chemistry

inductive Species
  | sodiumIon | electron | vacantSite | occupiedSite | trappedProduct
  deriving DecidableEq, Fintype

inductive Element
  | sodium | site
  deriving DecidableEq, Fintype

def composition : Element → Species → ℝ
  | .sodium, .sodiumIon => 1
  | .sodium, .occupiedSite => 1
  | .sodium, .trappedProduct => 1
  | .site, .vacantSite => 1
  | .site, .occupiedSite => 1
  | _, _ => 0

def charge : Species → ℝ
  | .sodiumIon => 1
  | .electron => -1
  | _ => 0

abbrev Inventory := Species → ℝ
abbrev PortFlux := Species → ℝ

def ValidInventory (n : Inventory) : Prop := ∀ species, 0 ≤ n species

end Naheng.Chemistry
