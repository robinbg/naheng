"""Observable filter diagnostics, without a reference-state interface."""
from __future__ import annotations

import numpy as np


def effective_sample_size(weights) -> float:
    values = np.asarray(weights, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("Weights must be a finite nonnegative vector")
    if not np.isclose(values.sum(), 1.0):
        raise ValueError("Weights must be normalized")
    return float(1.0 / np.dot(values, values))


def weighted_quantiles(values, weights, probabilities=(0.05, 0.5, 0.95)) -> list[float]:
    values, weights = np.asarray(values, dtype=float), np.asarray(weights, dtype=float)
    order = np.argsort(values)
    positive = weights[order] > 0
    ordered, cumulative = values[order][positive], np.cumsum(weights[order][positive])
    if not len(ordered):
        raise ValueError("At least one positive weight is required")
    return np.interp(probabilities, cumulative, ordered).tolist()


def systematic_resample(weights, rng) -> np.ndarray:
    values = np.asarray(weights, dtype=float)
    effective_sample_size(values)
    positions = (rng.random() + np.arange(len(values))) / len(values)
    cumulative = np.cumsum(values)
    cumulative[-1] = 1.0
    return np.searchsorted(cumulative, positions, side="right")
