"""A physical model override cannot silently become the base worker model."""
import pytest
from naheng.control.mpc import plan, MPCStage
from naheng.domain.contracts import Observation
from naheng.estimation.particle_filter import ParticleFilter
from naheng.models.site_model import SiteModel


def test_physical_subclass_is_rejected_before_worker_prediction():
    base = SiteModel()
    state = base.initial_state()
    measured = base.observe(state, 0)
    pf = ParticleFilter('identity-negative', base, particles=4, seed=20261012)
    snapshot = pf.update(Observation(run_id='identity-negative',timestamp_s=0,current_A=0,
        voltage_V=measured['voltage_V'],temperature_K=measured['temperature_K']),duration_s=0)
    class DifferentPhysics(SiteModel):
        def rhs(self, *args, **kwargs):
            raise AssertionError('A subclass must not be reconstructed as the base predictor')
    with pytest.raises(TypeError, match='declared SiteModel'):
        plan(snapshot,DifferentPhysics(),{},[MPCStage(30,.15,.3)]*3)
