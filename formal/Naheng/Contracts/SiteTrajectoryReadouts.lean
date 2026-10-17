import Naheng.Contracts.GroupTrapping
import Naheng.Contracts.Output

/- A legitimate per-site delta source uses singleton classes, not a bound
   for one total q. The same time-indexed a source, actual detailed ODE,
   reduced singleton amount ODE and whole-time primitive coefficient budget
   are explicit. Composing the conditional same-current voltage readout does
   not prove that different feedback drives satisfy these ODE premises. -/
namespace Naheng.Contracts
open Set Naheng.Reduction
open scoped BigOperators
set_option pp.proofs false

variable {ι : Type*} [Fintype ι] [DecidableEq ι]

theorem singleton_class_amount (N x : ι → ℝ) (i : ι) :
    classAmount N (fun j => j) x i = N i * x i := by
  simp [classAmount, Finset.sum_filter]

theorem singleton_group_trajectory_site_error
    (N : ι → ℝ) (x z a b c : ℝ → ι → ℝ)
    (r : ℝ → ι → ℝ) (rmin delta epsilon : ι → ℝ) (T : ℝ)
    (hT : 0 ≤ T) (hN : ∀ i, 0 < N i) (hrmin : ∀ i, 0 < rmin i)
    (hdelta : ∀ i, 0 ≤ delta i) (hepsilon : ∀ i, 0 ≤ epsilon i)
    (hr : ∀ t ∈ Icc 0 T, ∀ i, rmin i ≤ r t i)
    (site_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => x s i) (siteDerivative (a t i) (b t i) (c t i) (x t i)) t)
    (reduced_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => N i * z s i) (N i * a t i - r t i * (N i * z t i)) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T, ∀ i,
      N i * |a t i + b t i + c t i - r t i| ≤ epsilon i)
    (initial_error : ∀ i, |N i * x 0 i - N i * z 0 i| ≤ delta i) :
    ∀ t ∈ Icc 0 T, ∀ i, |x t i - z t i| ≤
      dampedEnvelope (delta i) (rmin i) (epsilon i) t / N i := by
  have hred : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => classAmount N (fun j => j) (z s) i)
        (classSource N (fun j => j) (a t) i -
          r t i * classAmount N (fun j => j) (z t) i) t := by
    intro t ht i
    simpa [classSource, Finset.sum_filter, singleton_class_amount] using reduced_solution t ht i
  have hbudget : ∀ t ∈ Icc 0 T, ∀ i,
      rateResidualBudget (classMask N (fun j => j) i) (a t) (b t) (c t) (r t i) ≤ epsilon i := by
    intro t ht i
    simpa [rateResidualBudget, classMask, ite_mul] using coefficient_budget t ht i
  have h := class_trajectory_error_from_site_reduction N (fun j => j) x z a b c r
    rmin delta epsilon T hT hrmin hdelta hepsilon (fun i => (hN i).le) hr
    site_solution hred hx0 hx1 hbudget
    (by intro i; simpa only [singleton_class_amount] using initial_error i)
  intro t ht i
  have hh := h t ht i
  simp only [singleton_class_amount, ← mul_sub, abs_mul, abs_of_pos (hN i)] at hh
  exact (le_div_iff₀ (hN i)).mpr (by nlinarith only [hh])

theorem singleton_trajectory_to_primitive_voltage_error
    (N k bias : ι → ℝ) (x z a b c : ℝ → ι → ℝ)
    (r : ℝ → ι → ℝ) (rmin delta epsilon : ι → ℝ) (ux uz : ℝ → ℝ)
    (F theta V0 R I scale L U eta_x eta_z T : ℝ)
    (hT : 0 ≤ T) (hN : ∀ i, 0 < N i) (hk : ∀ i, 0 < k i)
    (hF : 0 < F) (htheta : 0 < theta) (hscale : 0 < scale)
    (hrmin : ∀ i, 0 < rmin i) (hdelta : ∀ i, 0 ≤ delta i) (hepsilon : ∀ i, 0 ≤ epsilon i)
    (hr : ∀ t ∈ Icc 0 T, ∀ i, rmin i ≤ r t i)
    (site_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => x s i) (siteDerivative (a t i) (b t i) (c t i) (x t i)) t)
    (reduced_solution : ∀ t ∈ Icc 0 T, ∀ i,
      HasDerivAt (fun s => N i * z s i) (N i * a t i - r t i * (N i * z t i)) t)
    (hx0 : ∀ t ∈ Icc 0 T, ∀ i, 0 ≤ x t i)
    (hx1 : ∀ t ∈ Icc 0 T, ∀ i, x t i ≤ 1)
    (hz : ∀ t ∈ Icc 0 T, ∀ i, z t i ∈ Icc 0 1)
    (coefficient_budget : ∀ t ∈ Icc 0 T, ∀ i,
      N i * |a t i + b t i + c t i - r t i| ≤ epsilon i)
    (initial_error : ∀ i, |N i * x 0 i - N i * z 0 i| ≤ delta i)
    (hux : ∀ t ∈ Icc 0 T, ux t ∈ Icc L U) (huz : ∀ t ∈ Icc 0 T, uz t ∈ Icc L U)
    (hrootx : ∀ t ∈ Icc 0 T, |fixedCurrentDriveBalance F theta N k bias scale I (x t) (ux t)| ≤ eta_x)
    (hrootz : ∀ t ∈ Icc 0 T, |fixedCurrentDriveBalance F theta N k bias scale I (z t) (uz t)| ≤ eta_z)
    [Nonempty ι] :
    ∀ t ∈ Icc 0 T,
      |fixedCurrentVoltage V0 R I (ux t) - fixedCurrentVoltage V0 R I (uz t)| ≤
        (primitiveDriveBudget F theta N k bias
          (fun i => dampedEnvelope (delta i) (rmin i) (epsilon i) t / N i) scale L U + eta_x + eta_z) /
        primitiveSlopeFloor F theta N k bias scale L U := by
  have hstate := singleton_group_trajectory_site_error N x z a b c r rmin delta epsilon T
    hT hN hrmin hdelta hepsilon hr site_solution reduced_solution hx0 hx1 coefficient_budget initial_error
  intro t ht
  exact voltage_error_from_primitive_occupation F theta V0 R I N k bias
    (fun i => dampedEnvelope (delta i) (rmin i) (epsilon i) t / N i) (x t) (z t)
    scale L U (ux t) (uz t) eta_x eta_z hF htheta hscale hN hk
    (hz t ht) (hstate t ht) (hux t ht) (huz t ht) (hrootx t ht) (hrootz t ht)

end Naheng.Contracts

set_option pp.proofs false
#print Naheng.Contracts.singleton_class_amount
#print axioms Naheng.Contracts.singleton_class_amount
#print Naheng.Contracts.singleton_group_trajectory_site_error
#print axioms Naheng.Contracts.singleton_group_trajectory_site_error
#print Naheng.Contracts.singleton_trajectory_to_primitive_voltage_error
#print axioms Naheng.Contracts.singleton_trajectory_to_primitive_voltage_error
