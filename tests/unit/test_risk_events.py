from naheng.models.site_model import SiteModel
from naheng.risk.forecast import estimate_events


def test_proxy_events_do_not_become_fire_or_plating_probabilities():
    paths = [{"status":"computed","events":[{"name":"voltage_low"}]},
             {"status":"computed","events":[]},
             {"status":"failed","events":[]}]
    result = estimate_events(paths, SiteModel())
    assert result["events"]["voltage_low"]["probability"] is None
    assert result["events"]["voltage_low"]["successful_path_probability"] == 0.5
    assert result["events"]["voltage_low"]["reason"] == "incomplete_forward_ensemble"
    assert result["completed_paths"] == 2 and result["failed_paths"] == 1
    for name in ["fire","sodium_plating"]:
        assert result["events"][name]["status"] == "unknown"
        assert result["events"][name]["probability"] is None
    assert not result["risk_certificate"]


def test_zero_valid_paths_does_not_claim_zero_risk():
    result = estimate_events([{"status":"failed","events":[]}], SiteModel())
    assert result["events"]["voltage_low"]["probability"] is None
    assert result["events"]["voltage_low"]["status"] == "unknown"


def test_complete_posterior_ensemble_returns_defined_event_estimate():
    result = estimate_events([{"status":"computed","events":[{"name":"voltage_high"}]},
                              {"status":"computed","events":[]}], SiteModel())
    assert result["events"]["voltage_high"]["probability"] == 0.5
    assert result["events"]["voltage_high"]["status"] == "estimated"
