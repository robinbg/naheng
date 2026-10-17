"""Fitted Gaussian-process low model and autoregressive high-model discrepancy.

Posterior variance is a surrogate estimate, never a trajectory risk certificate.
Inputs are dimensionless coordinates fixed by the caller's declared design space.
"""
from dataclasses import dataclass
import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize


def matrix(x, dimension=None):
    x = np.asarray(x, dtype=float)
    if x.ndim != 2 or not np.isfinite(x).all() or (dimension is not None and x.shape[1] != dimension):
        raise ValueError('Finite two-dimensional design matrix required')
    if np.any(x < 0) or np.any(x > 1):
        raise ValueError('Inputs outside the fixed normalized design domain')
    return x


@dataclass
class GaussianProcess:
    dimension: int
    prior_scale: float = 1.0
    noise_variance: float = 1e-6

    def __post_init__(self):
        if type(self.dimension) is not int or not 1 <= self.dimension <= 16:
            raise ValueError('Bounded design dimension 1..16 required')
        if not np.isfinite([self.prior_scale, self.noise_variance]).all() or min(self.prior_scale, self.noise_variance) <= 0:
            raise ValueError('Positive finite prior scale and noise variance required')
        self.x = np.empty((0, self.dimension)); self.y = np.empty(0)
        self.length = np.full(self.dimension, .25)
        self.mean = 0.; self.scale = self.prior_scale
        self.factor = self.alpha = None
        self.fit_status = 'prior_no_observations'

    @staticmethod
    def kernel(a, b, length):
        delta = (a[:, None, :] - b[None, :, :]) / length
        return np.exp(-.5 * np.einsum('ijk,ijk->ij', delta, delta))

    def fit(self, x, y):
        x = matrix(x, self.dimension)
        y = np.asarray(y, dtype=float)
        if y.shape != (len(x),) or not np.isfinite(y).all() or len(x) > 256:
            raise ValueError('Matching bounded finite observations required')
        if len(x) == 0:
            self.__post_init__(); return self
        if len({tuple(v) for v in x}) != len(x):
            raise ValueError('Repeated completed inputs must not be double-counted')
        self.x, self.y = x.copy(), y.copy()
        self.mean = float(y.mean())
        self.scale = max(float(y.std()), abs(self.mean) * 1e-6, self.prior_scale * 1e-6)
        centered = (y - self.mean) / self.scale
        noise = self.noise_variance

        def objective(log_length):
            length = np.exp(log_length)
            covariance = self.kernel(x, x, length) + (noise + 1e-10) * np.eye(len(x))
            try:
                factor = cho_factor(covariance, lower=True)
                alpha = cho_solve(factor, centered)
            except np.linalg.LinAlgError:
                return 1e30
            return float(.5 * centered @ alpha + np.log(np.diag(factor[0])).sum() + .5 * len(x) * np.log(2 * np.pi))

        solution = None
        if len(x) >= 3:
            solution = minimize(objective, np.log(self.length), method='L-BFGS-B',
                                bounds=[(np.log(.025), np.log(2.0))] * self.dimension,
                                options={'maxiter': 60, 'ftol': 1e-10})
            if np.isfinite(solution.fun) and solution.fun <= objective(np.log(self.length)):
                self.length = np.exp(solution.x)
        covariance = self.kernel(x, x, self.length) + (noise + 1e-10) * np.eye(len(x))
        self.factor = cho_factor(covariance, lower=True)
        self.alpha = cho_solve(self.factor, centered)
        self.fit_status = 'fitted_marginal_likelihood' if solution is not None else 'fitted_fixed_initial_kernel'
        return self

    def predict(self, x):
        x = matrix(x, self.dimension)
        if self.factor is None:
            return np.full(len(x), self.mean), np.full(len(x), self.scale**2)
        cross = self.kernel(x, self.x, self.length)
        mean = self.mean + self.scale * (cross @ self.alpha)
        reduction = np.einsum('ij,ji->i', cross, cho_solve(self.factor, cross.T))
        variance = self.scale**2 * np.maximum(0., 1. - reduction)
        return mean, variance

    def state(self):
        return {'kind': 'RBF_GP', 'x': self.x.tolist(), 'y': self.y.tolist(),
                'length_scales': self.length.tolist(), 'mean': self.mean, 'scale': self.scale,
                'noise_variance_normalized': self.noise_variance, 'fit_status': self.fit_status,
                'variance_scope': 'surrogate_latent_variance_not_a_risk_or_coverage_certificate'}


class MultiFidelity:
    def __init__(self, dimension, prior_scale=1.):
        self.dimension = dimension; self.prior_scale = prior_scale
        self.low = GaussianProcess(dimension, prior_scale)
        self.delta = GaussianProcess(dimension, prior_scale)
        self.rho = 1.; self.paired_count = 0
        self.rho_fitted_from_pairs=False;self.paired_low_centered_sum_squares=0.

    def fit(self, low_x, low_y, high_x, high_y):
        low_x, high_x = matrix(low_x, self.dimension), matrix(high_x, self.dimension)
        low_y, high_y = np.asarray(low_y, dtype=float), np.asarray(high_y, dtype=float)
        if low_y.shape != (len(low_x),) or high_y.shape != (len(high_x),):
            raise ValueError('Each fidelity must bind its own observations')
        self.low.fit(low_x, low_y)
        low_by_x = {tuple(x): y for x, y in zip(low_x, low_y)}
        pairs = [(low_by_x[tuple(x)], y) for x, y in zip(high_x, high_y) if tuple(x) in low_by_x]
        self.paired_count = len(pairs)
        self.rho = 1.
        self.rho_fitted_from_pairs=False;self.paired_low_centered_sum_squares=0.
        if len(pairs) >= 2:
            a, b = np.asarray(pairs).T
            centered_a, centered_b = a - a.mean(), b - b.mean()
            denominator = float(centered_a @ centered_a)
            self.paired_low_centered_sum_squares=denominator
            if denominator > 1e-24:
                self.rho_fitted_from_pairs=True
                self.rho = float(np.clip((centered_a @ centered_b) / denominator, -3., 3.))
        low_mean, _ = self.low.predict(high_x)
        residual = high_y - self.rho * low_mean
        self.delta = GaussianProcess(self.dimension, max(self.low.scale, self.prior_scale * 1e-3))
        self.delta.fit(high_x, residual)
        return self

    def predict(self, x, fidelity='high'):
        if fidelity not in ('low', 'high'):
            raise ValueError('Unknown fidelity')
        mean, variance = self.low.predict(x)
        if fidelity == 'low': return mean, variance
        delta, residual_variance = self.delta.predict(x)
        return self.rho * mean + delta, self.rho**2 * variance + residual_variance

    def state(self):
        return {'model': 'rho_times_low_plus_fitted_discrepancy', 'rho': self.rho,
                'paired_count': self.paired_count, 'rho_fitted_from_pairs':self.rho_fitted_from_pairs,
                'paired_low_centered_sum_squares':self.paired_low_centered_sum_squares,
                'rho_estimation':'paired_least_squares_clipped' if self.rho_fitted_from_pairs else 'default_unit_not_identified',
                'low': self.low.state(), 'discrepancy': self.delta.state(),
                'limitations': ['fixed fitted hyperparameters', 'independence approximation between low GP and discrepancy',
                                'no calibration or independent operational risk guarantee']}
