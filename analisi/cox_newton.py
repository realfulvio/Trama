"""Cox proportional hazards by Newton–Raphson with Efron or Breslow ties, vectorised (0.109.x).

statsmodels ``PHReg`` evaluates the Efron score and Hessian with a Python loop over the distinct
event times, which costs about a second at 10,000 rows. The same partial likelihood is written here
with risk-set sums accumulated from the longest time down, so one Newton step is a few passes over
the data and one p×p product.

For the event time t_k with d_k events, risk set R_k = {j: T_j >= t_k} and fractions f = r/d_k
(r = 0..d_k-1, Efron) or f = 0 (Breslow):

    den = S0_k - f D0_k,  num = S1_k - f D1_k,  where S are sums over R_k and D over the events at t_k
    log L = sum(eta_i, events) - sum_kr log(den)
    score = sum(x_i, events) - sum_kr num / den
    information = sum_kr (S2_k - f D2_k) / den - num num' / den²

The second-moment sums are never stored per event time: sum_k a_k S2_k equals X' diag(w A) X with
A(T_j) the running sum of a_k over the event times t_k <= T_j. The result object exposes what the
analysis reads from a statsmodels result: params, bse, cov_params(), conf_int(), pvalues and llf.
"""
from dataclasses import dataclass

import numpy as np
from scipy import stats

MAX_HALVINGS = 30


class CoxConvergenceError(ValueError):
    """Newton–Raphson did not reach a stationary point within the iteration limit."""


@dataclass
class CoxResult:
    params: np.ndarray
    cov: np.ndarray
    llf: float
    iterations: int

    @property
    def bse(self):
        return np.sqrt(np.diag(self.cov))

    def cov_params(self):
        return self.cov

    @property
    def pvalues(self):
        return 2 * stats.norm.sf(np.abs(self.params / self.bse))

    def conf_int(self, alpha=0.05):
        q = stats.norm.isf(alpha / 2)
        return np.column_stack((self.params - q * self.bse, self.params + q * self.bse))


class _Problem:
    """Sorted data and the event-time structure, shared by every Newton step."""

    def __init__(self, time, design, status, ties):
        time = np.asarray(time, dtype=float)
        x = np.asarray(design, dtype=float)
        if x.ndim == 1:
            x = x[:, None]
        event = np.asarray(status, dtype=float) == 1
        order = np.argsort(-time, kind="stable")          # longest first: a running sum is a risk set
        self.time, self.x, self.event = time[order], x[order], event[order]
        self.efron = ties == "efron"
        times = np.unique(self.time[self.event])            # ascending distinct event times
        self.n_times = len(times)
        # last row of each risk set in the descending order (all rows with T >= t_k)
        self.risk_end = np.searchsorted(-self.time, -times, side="right") - 1
        # index k of the event time of each event row, and of the latest event time <= T_j for any row
        self.event_rows = np.flatnonzero(self.event)
        self.event_time = np.searchsorted(times, self.time[self.event_rows])
        self.deaths = np.bincount(self.event_time, minlength=self.n_times)
        self.below = np.searchsorted(times, self.time, side="right") - 1   # -1: before the first event time
        # one (k, r) pair per event: r = 0..d_k-1
        self.pair_time = np.repeat(np.arange(self.n_times), self.deaths)
        start = np.cumsum(self.deaths) - self.deaths
        self.pair_fraction = ((np.arange(len(self.pair_time)) - start[self.pair_time]) / self.deaths[self.pair_time]
                              if self.efron else np.zeros(len(self.pair_time)))
        self.x_events = self.x[self.event_rows].sum(axis=0)

    def evaluate(self, beta, derivatives=True):
        x, k, f = self.x, self.pair_time, self.pair_fraction
        eta = x @ beta
        shift = float(eta.max())
        w = np.exp(eta - shift)
        s0 = np.cumsum(w)[self.risk_end]
        d0 = np.bincount(self.event_time, weights=w[self.event_rows], minlength=self.n_times)
        den = s0[k] - f * d0[k]
        llf = float(eta[self.event_rows].sum() - np.log(den).sum() - len(k) * shift)
        if not derivatives:
            return llf, None, None
        p = x.shape[1]
        s1 = np.cumsum(w[:, None] * x, axis=0)[self.risk_end]
        d1 = np.zeros((self.n_times, p))
        np.add.at(d1, self.event_time, w[self.event_rows, None] * x[self.event_rows])
        inv = 1 / den
        a = np.bincount(k, weights=inv, minlength=self.n_times)
        b = np.bincount(k, weights=f * inv, minlength=self.n_times)
        c = np.bincount(k, weights=inv ** 2, minlength=self.n_times)
        e = np.bincount(k, weights=f * inv ** 2, minlength=self.n_times)
        g = np.bincount(k, weights=f * f * inv ** 2, minlength=self.n_times)
        score = self.x_events - (a @ s1 - b @ d1)
        # sum_k a_k S2_k = X' diag(w A) X, A(T_j) = sum of a_k over t_k <= T_j
        running = np.concatenate(([0.], np.cumsum(a)))[self.below + 1]
        second = (x * (w * running)[:, None]).T @ x
        event_weight = np.zeros(len(w))
        event_weight[self.event_rows] = w[self.event_rows] * b[self.event_time]
        second -= (x * event_weight[:, None]).T @ x
        mixed = (s1 * e[:, None]).T @ d1
        outer = (s1 * c[:, None]).T @ s1 - mixed - mixed.T + (d1 * g[:, None]).T @ d1
        information = second - outer
        return llf, score, (information + information.T) / 2


def fit(time, design, status, ties="efron", maxiter=100):
    """Newton–Raphson from zero with step halving; raises CoxConvergenceError or LinAlgError."""
    problem = _Problem(time, design, status, ties)
    p = problem.x.shape[1]
    beta = np.zeros(p)
    llf, score, information = problem.evaluate(beta)
    for iteration in range(1, maxiter + 1):
        step = np.linalg.solve(information, score)
        scale = 1.0
        for _ in range(MAX_HALVINGS):
            candidate = beta + scale * step
            new_llf = problem.evaluate(candidate, derivatives=False)[0]
            if np.isfinite(new_llf) and new_llf >= llf - 1e-12 * max(1., abs(llf)):
                break
            scale /= 2
        else:
            raise CoxConvergenceError("The Cox regression did not converge.")
        beta = candidate
        change = np.max(np.abs(scale * step)) / (1 + np.max(np.abs(beta)))
        gain = abs(new_llf - llf)
        llf, score, information = problem.evaluate(beta)
        if change < 1e-10 or gain < 1e-14 * max(1., abs(llf)):
            cov = np.linalg.inv(information)
            if not np.all(np.isfinite(cov)) or np.any(np.diag(cov) <= 0):
                raise np.linalg.LinAlgError("The information matrix is singular.")
            return CoxResult(beta, cov, llf, iteration)
    raise CoxConvergenceError("The Cox regression did not converge.")
