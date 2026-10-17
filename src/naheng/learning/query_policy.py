"""Constrained expected improvement and a cost-aware fidelity query score."""
import numpy as np
from scipy.special import ndtr


def expected_improvement(mean, variance, incumbent):
    mean, variance = np.asarray(mean, float), np.asarray(variance, float)
    if mean.shape != variance.shape or not np.isfinite(mean).all() or not np.isfinite(variance).all() or np.any(variance < 0):
        raise ValueError('Finite compatible predictive moments required')
    sigma = np.sqrt(variance)
    improvement = mean - incumbent
    z = np.divide(improvement, sigma, out=np.zeros_like(improvement), where=sigma > 0)
    density = np.exp(-.5 * z**2) / np.sqrt(2 * np.pi)
    value = improvement * ndtr(z) + sigma * density
    return np.where(sigma > 0, np.maximum(value, 0.), np.maximum(improvement, 0.))


def probability_feasible(mean_margin, variance):
    mean_margin, variance = np.asarray(mean_margin, float), np.asarray(variance, float)
    if mean_margin.shape != variance.shape or not np.isfinite(mean_margin).all() or not np.isfinite(variance).all() or np.any(variance < 0):
        raise ValueError('Finite constraint moments required')
    sigma = np.sqrt(variance)
    z = np.divide(-mean_margin, sigma, out=np.zeros_like(mean_margin), where=sigma > 0)
    return np.where(sigma > 0, ndtr(z), (mean_margin <= 0).astype(float))


def score(utility_model, constraint_model, x, incumbent, fidelity, costs, feasible_incumbent=True):
    if fidelity not in ('low', 'high') or set(costs) != {'low', 'high'} or min(costs.values()) <= 0:
        raise ValueError('Two positive declared fidelity costs required')
    mean, variance = utility_model.predict(x, 'high')
    margin, margin_variance = constraint_model.predict(x, 'high')
    probability = probability_feasible(margin, margin_variance)
    if feasible_incumbent:
        benefit = expected_improvement(mean, variance, incumbent) * probability
    else:
        benefit = probability + .1 * np.sqrt(margin_variance)
    if fidelity == 'low':
        _, low_variance = utility_model.predict(x, 'low')
        transfer_fraction = np.divide(utility_model.rho**2 * low_variance, variance + 1e-20)
        benefit = benefit * np.clip(transfer_fraction, 0., 1.)
    return benefit / costs[fidelity], {'high_mean': mean, 'high_variance': variance,
        'feasibility_probability_model_only': probability, 'risk_certificate': False}
