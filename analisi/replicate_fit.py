"""Use the replicate subcolumns of an XY worksheet as observations of one series."""
import pandas as pd

from .field_error import FieldError
from .fit_weights import INVERSE_VARIANCE
from .worksheet_series import series_columns, series_labels

MERGE_REPLICATES = "Merge numbered replicates"


def replicate_groups(frame, options):
    names = options.get("Y columns") or []
    if options.get("Grouping variables"):
        raise FieldError(MERGE_REPLICATES, "Choose numbered replicates or grouping variables.")
    x = options.get("X")
    sd = options.get("SD column") if options.get("Weighting") == INVERSE_VARIANCE else None
    fields = [x, *names, *([sd] if sd else [])]
    if not names or len(set(fields)) != len(fields) or any(name not in frame for name in fields):
        raise FieldError("Y columns", "Select distinct X, Y and optional SD columns.")
    if options.get("Weighting") == INVERSE_VARIANCE and not sd:
        raise FieldError("SD column", "Choose a separate column of positive relative standard deviations.")
    groups = series_columns(frame, names, recognize_replicates=True)
    if len(groups) > 8:
        raise FieldError("Y columns", "Select up to eight response series.")
    if len(frame) * len(names) > 500_000:
        raise FieldError("Y columns", "The selected wide curves contain too many observations.")
    return groups


def stack_replicates(frame, options):
    groups = replicate_groups(frame, options)
    x = frame[options["X"]].to_numpy()
    sd = frame[options["SD column"]].to_numpy() if options.get("Weighting") == INVERSE_VARIANCE else None
    blocks = []
    for label, group in zip(series_labels(groups), groups, strict=True):
        for column in group:
            data = pd.DataFrame({"X": x, "Response": frame[column].to_numpy(), "Series": label})
            if sd is not None:
                data["SD"] = sd
            blocks.append(data)
    return pd.concat(blocks, ignore_index=True)
