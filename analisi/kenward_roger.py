"""Kenward–Roger inference for covariance linear in its variance components."""

from dataclasses import dataclass

import numpy as np
from scipy import linalg


def _whiten_block(cells, bases, variances, fixed_root):
    covariance = np.einsum("k,kij->ij", variances, bases)
    root = linalg.cholesky(covariance, lower=True)
    whitener = linalg.solve_triangular(root, np.eye(len(cells)), lower=True)
    design = whitener @ fixed_root[cells]
    derivatives = whitener @ bases @ whitener.T
    return design, derivatives


@dataclass
class _KenwardRoger:
    covariance: np.ndarray
    fixed_root: np.ndarray
    gram_derivatives: np.ndarray
    variance_covariance: np.ndarray

    @classmethod
    def fit(cls, covariance, variances, patterns):
        # Kenward & Roger (1997), doi:10.2307/2533558.
        # Use whitened subject blocks and work in the coordinates of the
        # Cholesky factor of the unadjusted fixed-effect covariance. In these
        # coordinates, the stacked design has orthonormal columns.
        fixed_root = linalg.cholesky(covariance, lower=True)
        n_components = len(variances)
        derivative_trace = np.zeros((n_components, n_components))
        weighted_trace = np.zeros_like(derivative_trace)
        gram_derivatives = np.zeros((n_components, *covariance.shape))
        for cells, bases, count in patterns:
            design, derivatives = _whiten_block(cells, bases, variances, fixed_root)
            weighted = derivatives @ design
            gram_derivatives += count * (design.T @ weighted)
            flattened = derivatives.reshape(n_components, -1)
            derivative_trace += count * (flattened @ flattened.T)
            flattened = weighted.reshape(n_components, -1)
            weighted_trace += count * (flattened @ flattened.T)

        gram_derivatives = (gram_derivatives + gram_derivatives.transpose(0, 2, 1)) / 2
        flattened = gram_derivatives.reshape(n_components, -1)
        # Expected REML information, I_ij = tr(P dV_i P dV_j) / 2,
        # with P the residual precision. The three terms expand its trace.
        information = (derivative_trace - 2 * weighted_trace + flattened @ flattened.T) / 2
        diagonal = np.diag(information)
        if not np.isfinite(information).all() or np.any(diagonal <= 0):
            raise ValueError("The variance components are not separately identifiable.")
        scale = 1 / np.sqrt(diagonal)
        normalized = scale[:, None] * information * scale
        eigenvalues = linalg.eigvalsh(normalized)
        if eigenvalues[0] <= 1e-10 * eigenvalues[-1]:
            raise ValueError("The variance components are not separately identifiable.")
        variance_covariance = scale[:, None] * linalg.solve(
            normalized, np.eye(n_components), assume_a="pos") * scale

        # The full KR correction also has a second-derivative term, which
        # vanishes here since V is linear in the variance components. The
        # remaining Q_ij - P_i Phi P_j terms are crossproducts of residualized
        # weighted designs. Evaluate their sum without assembling an n×n
        # matrix or storing one fixed-effect matrix per component pair.
        variance_root = linalg.cholesky(variance_covariance, lower=True)
        adjusted = np.eye(len(covariance))
        for cells, bases, count in patterns:
            design, derivatives = _whiten_block(cells, bases, variances, fixed_root)
            residualized = derivatives @ design - design @ gram_derivatives
            combined = variance_root.T @ residualized.reshape(n_components, -1)
            combined = combined.reshape(-1, len(covariance))
            adjusted += 2 * count * (combined.T @ combined)
        adjusted = fixed_root @ adjusted @ fixed_root.T
        adjusted = (adjusted + adjusted.T) / 2
        linalg.cholesky(adjusted, lower=True)
        return cls(adjusted, fixed_root, gram_derivatives, variance_covariance)

    def degrees(self, contrasts):
        # Rank-one KR has A1 = A2, df = 2/A2 and F scaling = 1.
        # Use the unadjusted covariance in these moments, even though the
        # standard error and Wald statistic use the adjusted covariance.
        weighted = contrasts @ self.fixed_root
        variance = np.sum(weighted**2, axis=1)
        relative = (np.einsum("ni,kij,nj->nk", weighted, self.gram_derivatives, weighted, optimize=True)
                    / variance[:, None])
        a2 = np.einsum("ni,ij,nj->n", relative, self.variance_covariance, relative)
        with np.errstate(divide="ignore", invalid="ignore"):
            df = 2 / a2
        return np.where(np.isfinite(df) & (df > 0), df, np.nan)

    def test(self, contrasts, beta):
        rank = len(contrasts)
        if rank == 1:
            df = self.degrees(contrasts)[0]
            if not np.isfinite(df):
                return np.nan, np.nan, np.nan
            variance = (contrasts @ self.covariance @ contrasts.T).item()
            return (contrasts @ beta).item()**2 / variance, df, 1.

        weighted = contrasts @ self.fixed_root
        root = linalg.cholesky(weighted @ weighted.T, lower=True)
        basis = linalg.solve_triangular(root, weighted, lower=True)
        projected = basis @ self.gram_derivatives @ basis.T
        traces = np.trace(projected, axis1=1, axis2=2)
        a1 = traces @ self.variance_covariance @ traces
        a2 = np.sum(self.variance_covariance * np.einsum("kij,lji->kl", projected, projected))
        df, scaling = _f_moments(rank, a1, a2)
        if not np.isfinite(df):
            return np.nan, np.nan, np.nan
        effects = contrasts @ beta
        tested = contrasts @ self.covariance @ contrasts.T
        wald = effects @ linalg.solve(tested, effects, assume_a="pos")
        return scaling * wald / rank, df, scaling


def _f_moments(rank, a1, a2):
    # Moment matching for q > 1, as in Halekoh & Højsgaard (2014),
    # doi:10.18637/jss.v059.i09. Reject a degenerate F approximation.
    if not np.isfinite([a1, a2]).all() or a2 <= 0:
        return np.nan, np.nan
    # A1 = q A2 means the tested covariance varies only by a common
    # multiplier. The ANOVA form stays exact at df=2 or 4, where the
    # general moment formula has removable singularities.
    if abs(a1 - rank * a2) <= 1e-12 * rank * a2:
        return 2 * rank / a2, 1.
    b = (a1 + 6 * a2) / (2 * rank)
    g = ((rank + 1) * (a1 / a2) - (rank + 4)) / (rank + 2)
    denominator = 3 * rank + 2 * (1 - g)
    if denominator <= 0:
        return np.nan, np.nan
    v0 = 1 + b * g / denominator
    v1 = 1 - b * (rank - g) / denominator
    v2 = 1 - b * (rank + 2 - g) / denominator
    mean_inverse = 1 - a2 / rank
    # Write q rho = numerator / divisor and substitute directly into
    # the equations for df and scaling, so a pole at df=4 is harmless.
    numerator = mean_inverse**2 * v0
    divisor = v1**2 * v2
    difference = numerator - divisor
    scale_denominator = 2 * numerator + rank * divisor
    if difference == 0 or scale_denominator == 0:
        return np.nan, np.nan
    df = 4 + (rank + 2) * divisor / difference
    scaling = mean_inverse * (4 * numerator + (rank - 2) * divisor) / scale_denominator
    if not np.isfinite([df, scaling]).all() or min(df, scaling) <= 0:
        return np.nan, np.nan
    return df, scaling
