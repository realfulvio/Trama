"""Use a saved PCA reference summary with the measurements that produced it."""

from hashlib import sha256
import json

import numpy as np

from .stats import complete


ARCHIVE = "Imported PCA parallel reference"


def _signature(frame, variables, simulations, seed, percentile):
    values = complete(frame, variables).to_numpy(dtype="<f8", copy=True)
    values[values == 0] = 0.0
    settings = json.dumps((values.shape, simulations, seed, percentile), separators=(",", ":"))
    digest = sha256(settings.encode("ascii"))
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def capture(frame, variables, simulations, seed, percentile, observed, mean, lower, upper):
    """Bind the saved eigenvalues and reference bounds to the selected measurement matrix."""
    data = np.asarray([observed, mean, lower, upper], dtype=float)
    if not _valid(data):
        return None
    return {"source": _signature(frame, variables, simulations, seed, percentile), "values": data.tolist()}


def _valid(data):
    observed, mean, lower, upper = data
    return (np.isfinite(data).all() and (observed >= 0).all() and (lower >= 0).all()
            and (lower <= mean).all() and (mean <= upper).all())


def matching(frame, options, observed, simulations, seed, percentile):
    """Require the original inputs, simulation settings and observed eigenvalues."""
    saved = options.get(ARCHIVE)
    if not isinstance(saved, dict) or not options["Standardize"] or percentile != 95:
        return None
    rows = saved.get("values")
    if (not isinstance(rows, list) or len(rows) != 4
            or any(not isinstance(row, list) or len(row) != len(observed)
                   or any(type(value) not in (int, float) for value in row) for row in rows)):
        return None
    try:
        data = np.asarray(rows, dtype=float)
    except (ValueError, OverflowError):
        return None
    if (not _valid(data) or not np.allclose(data[0], observed, rtol=2e-10, atol=1e-12)
            or _signature(frame, options["Variables"], simulations, seed, percentile) != saved.get("source")):
        return None
    return tuple(data[1:])
