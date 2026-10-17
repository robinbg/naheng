import Naheng.Chemistry.Thermodynamics

/- Declared isothermal reversible electrode fixture. capacity is mol of sites;
   zF is charge per mol, theta is molar energy, u is electrical potential and
   muExternal is the reservoir chemical potential. A/B are occupation rates.
   The same reversible flux supplies the Faraday current and reservoir port;
   p is a distinct material occupation port. This explicitly separates I*u
   electrical work from chemical supply. faradayInputCurrent is positive for
   insertion; dischargeCurrent follows the project's positive-discharge sign.
   It does not map default SiteModel
   voltage/temperature/side products to these ideal constitutive parameters. -/
namespace Naheng.Chemistry.ElectricalPorts
open Naheng.Chemistry.Thermodynamics
set_option pp.proofs false

def portDrive (zF u muExternal : ℝ) : ℝ := zF * u + muExternal

noncomputable def portInsertion (theta a zF u muExternal x : ℝ) : ℝ :=
  insertionFlux a x * Real.exp (portDrive zF u muExternal / (2*theta))
noncomputable def portRemoval (theta b zF u muExternal x : ℝ) : ℝ :=
  removalFlux b x * Real.exp (-portDrive zF u muExternal / (2*theta))
noncomputable def portRate (theta a b zF u muExternal x : ℝ) : ℝ :=
  portInsertion theta a zF u muExternal x - portRemoval theta b zF u muExternal x
noncomputable def faradayInputCurrent (capacity theta a b zF u muExternal x : ℝ) : ℝ :=
  zF * capacity * portRate theta a b zF u muExternal x
noncomputable def dischargeCurrent (capacity theta a b zF u muExternal x : ℝ) : ℝ :=
  -faradayInputCurrent capacity theta a b zF u muExternal x
noncomputable def electricalPower (capacity theta a b zF u muExternal x : ℝ) : ℝ :=
  faradayInputCurrent capacity theta a b zF u muExternal x * u
noncomputable def materialPower (capacity theta a b zF u muExternal x p : ℝ) : ℝ :=
  capacity * (muExternal * portRate theta a b zF u muExternal x +
    chemicalPotential theta a b x * p)

theorem positive_driven_reversible_fluxes (theta a b zF u muExternal x : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hx : 0 < x) (hx1 : x < 1) :
    0 < portInsertion theta a zF u muExternal x ∧
      0 < portRemoval theta b zF u muExternal x := by
  have h := positive_site_fluxes a b x ha hb hx hx1
  exact ⟨mul_pos h.1 (Real.exp_pos _), mul_pos h.2 (Real.exp_pos _)⟩

/- Local detailed balance is derived from the independently defined base
   free energy and exponential port-dependent rates, not postulated as the
   requested dissipation or an energy-derivative condition. -/
theorem driven_local_detailed_balance (theta a b zF u muExternal x : ℝ)
    (htheta : 0 < theta) (ha : 0 < a) (hb : 0 < b) (hx : 0 < x) (hx1 : x < 1) :
    chemicalPotential theta a b x - portDrive zF u muExternal =
      theta * (Real.log (portRemoval theta b zF u muExternal x) -
        Real.log (portInsertion theta a zF u muExternal x)) := by
  have h := positive_site_fluxes a b x ha hb hx hx1
  rw [chemicalPotential_local_detailed_balance theta a b x ha hb hx hx1]
  dsimp [portInsertion, portRemoval]
  rw [Real.log_mul (ne_of_gt h.2) (ne_of_gt (Real.exp_pos _)),
    Real.log_mul (ne_of_gt h.1) (ne_of_gt (Real.exp_pos _)), Real.log_exp, Real.log_exp]
  field_simp [ne_of_gt htheta]
  ring

theorem faraday_current_same_reversible_material_flux
    (capacity theta a b zF u muExternal x : ℝ) (hzF : 0 < zF) :
    faradayInputCurrent capacity theta a b zF u muExternal x / zF =
      capacity * portRate theta a b zF u muExternal x := by
  dsimp [faradayInputCurrent]
  field_simp [ne_of_gt hzF] <;> ring

theorem electrical_power_matches_positive_discharge_sign
    (capacity theta a b zF u muExternal x : ℝ) :
    electricalPower capacity theta a b zF u muExternal x =
      -(dischargeCurrent capacity theta a b zF u muExternal x * u) := by
  simp [electricalPower, dischargeCurrent]

theorem driven_electrical_and_material_supply_dissipation
    (capacity theta a b zF u muExternal x p : ℝ)
    (hcapacity : 0 ≤ capacity) (htheta : 0 < theta) (ha : 0 < a) (hb : 0 < b)
    (hx : 0 < x) (hx1 : x < 1) :
    capacity * chemicalPotential theta a b x * (portRate theta a b zF u muExternal x + p) -
      electricalPower capacity theta a b zF u muExternal x -
      materialPower capacity theta a b zF u muExternal x p ≤ 0 := by
  have hflux := positive_driven_reversible_fluxes theta a b zF u muExternal x ha hb hx hx1
  have hdb := driven_local_detailed_balance theta a b zF u muExternal x htheta ha hb hx hx1
  have hdis := positive_flux_log_dissipation
    (portInsertion theta a zF u muExternal x) (portRemoval theta b zF u muExternal x)
    hflux.1 hflux.2
  have hid : capacity * chemicalPotential theta a b x * (portRate theta a b zF u muExternal x + p) -
      electricalPower capacity theta a b zF u muExternal x -
      materialPower capacity theta a b zF u muExternal x p =
      capacity * (chemicalPotential theta a b x - portDrive zF u muExternal) *
        portRate theta a b zF u muExternal x := by
    dsimp [electricalPower, faradayInputCurrent, materialPower, portDrive]
    ring
  rw [hid, hdb]
  have h := mul_le_mul_of_nonneg_left hdis (mul_nonneg hcapacity htheta.le)
  convert h using 1 <;> dsimp [portRate] <;> ring

theorem free_energy_along_driven_solution_supply_dissipation
    (capacity theta a b zF u muExternal : ℝ) (x p : ℝ → ℝ) (t : ℝ)
    (hcapacity : 0 ≤ capacity) (htheta : 0 < theta) (ha : 0 < a) (hb : 0 < b)
    (hx : 0 < x t) (hx1 : x t < 1)
    (solution : HasDerivAt x (portRate theta a b zF u muExternal (x t) + p t) t) :
    deriv (fun s => capacity * freeEnergy theta a b (x s)) t -
      electricalPower capacity theta a b zF u muExternal (x t) -
      materialPower capacity theta a b zF u muExternal (x t) (p t) ≤ 0 := by
  have hf := ((freeEnergy_hasDerivAt theta a b (x t) hx hx1).comp t solution).const_mul capacity
  have hder : deriv (fun s => capacity * freeEnergy theta a b (x s)) t =
      capacity * chemicalPotential theta a b (x t) *
        (portRate theta a b zF u muExternal (x t) + p t) := by
    convert hf.deriv using 1 <;> dsimp only [Function.comp_def] <;> ring
  rw [hder]
  exact driven_electrical_and_material_supply_dissipation capacity theta a b zF u muExternal
    (x t) (p t) hcapacity htheta ha hb hx hx1

theorem nonempty_nonequilibrium_electrical_port_witness :
    chemicalPotential 1 1 1 (1/2) = 0 ∧
    0 < portRate 1 1 1 1 1 0 (1/2) ∧
    0 < electricalPower 1 1 1 1 1 1 0 (1/2) ∧
    materialPower 1 1 1 1 1 1 0 (1/2) 0 = 0 ∧
    1 * chemicalPotential 1 1 1 (1/2) * portRate 1 1 1 1 1 0 (1/2) -
      electricalPower 1 1 1 1 1 1 0 (1/2) - materialPower 1 1 1 1 1 1 0 (1/2) 0 < 0 := by
  have hmu : chemicalPotential 1 1 1 (1/2) = 0 := by
    norm_num [chemicalPotential]
  have he : Real.exp (-(1/2 : ℝ)) < Real.exp (1/2 : ℝ) :=
    Real.exp_lt_exp.mpr (by norm_num)
  have hrate : 0 < portRate 1 1 1 1 1 0 (1/2) := by
    norm_num [portRate, portInsertion, portRemoval, insertionFlux, removalFlux, portDrive] <;>
      linarith only [he]
  have hpower : electricalPower 1 1 1 1 1 1 0 (1/2) = portRate 1 1 1 1 1 0 (1/2) := by
    simp [electricalPower, faradayInputCurrent]
  have hmaterial : materialPower 1 1 1 1 1 1 0 (1/2) 0 = 0 := by
    simp [materialPower]
  refine ⟨hmu, hrate, by rw [hpower]; exact hrate, hmaterial, ?_⟩
  rw [hmu, hpower, hmaterial]
  linarith only [hrate]

end Naheng.Chemistry.ElectricalPorts

set_option pp.proofs false

#print Naheng.Chemistry.ElectricalPorts.positive_driven_reversible_fluxes
#print axioms Naheng.Chemistry.ElectricalPorts.positive_driven_reversible_fluxes
#print Naheng.Chemistry.ElectricalPorts.driven_local_detailed_balance
#print axioms Naheng.Chemistry.ElectricalPorts.driven_local_detailed_balance
#print Naheng.Chemistry.ElectricalPorts.faraday_current_same_reversible_material_flux
#print axioms Naheng.Chemistry.ElectricalPorts.faraday_current_same_reversible_material_flux
#print Naheng.Chemistry.ElectricalPorts.electrical_power_matches_positive_discharge_sign
#print axioms Naheng.Chemistry.ElectricalPorts.electrical_power_matches_positive_discharge_sign
#print Naheng.Chemistry.ElectricalPorts.driven_electrical_and_material_supply_dissipation
#print axioms Naheng.Chemistry.ElectricalPorts.driven_electrical_and_material_supply_dissipation
#print Naheng.Chemistry.ElectricalPorts.free_energy_along_driven_solution_supply_dissipation
#print axioms Naheng.Chemistry.ElectricalPorts.free_energy_along_driven_solution_supply_dissipation
#print Naheng.Chemistry.ElectricalPorts.nonempty_nonequilibrium_electrical_port_witness
#print axioms Naheng.Chemistry.ElectricalPorts.nonempty_nonequilibrium_electrical_port_witness
