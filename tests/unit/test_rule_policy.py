import pytest
from naheng.domain.contracts import PosteriorSnapshot
from naheng.control.rules import propose


def snapshot(soc=0.6, upper=None):
    return PosteriorSnapshot(snapshot_id="snapshot-rules",run_id="run-rules",obs_until_s=2,
        state_names=["soc","temperature_K"],state_units=["1","K"],
        samples=[[soc,298.15]],weights=[1],mean={"soc":soc,"temperature_K":298.15},
        quantiles={"soc":[soc-0.05,soc,soc+0.05 if upper is None else upper],
                   "temperature_K":[298.0,298.15,298.3]},ess=1)


def test_price_policy_uses_discharge_sign_and_credible_soc_limits():
    posterior=snapshot()
    assert propose(posterior,0.05,2,30).current_A < 0
    assert propose(posterior,0.30,2,30).current_A > 0
    assert propose(posterior,0.20,2,30).current_A == 0
    assert propose(snapshot(0.6,upper=0.95),0.05,2,30).current_A == 0
    assert propose(snapshot(0.1),0.30,2,30).current_A == 0
    with pytest.raises(ValueError,match="before"):
        propose(posterior,0.3,1,30)


def test_missing_uncertainty_does_not_default_to_safe_admission():
    posterior = snapshot().model_copy(update={"quantiles":{}})
    with pytest.raises(ValueError,match="uncertainty"):
        propose(posterior,0.3,2,30)
