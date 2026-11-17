"""XY error bars calculation, validation, and dialog visibility."""
from matplotlib.colors import is_color_like, to_rgba
from matplotlib.container import ErrorbarContainer
import numpy as np
import pandas as pd

from .field_error import FieldError
from .reporting import Result, _plot

XY_ERRORS = "XY error bars"
X_DISTANCE = "X error distance"
X_LOWER = "X lower error"
X_UPPER = "X upper error"
X_VALUES = "X error values"
X_DIRECTION = "X error direction"
Y_LOWER = "Y lower error"
Y_UPPER = "Y upper error"
Y_VALUES = "Y error values"
Y_DIRECTION = "Y error direction"
ERROR_CAP_SIZE = "Error cap size"
ERROR_WIDTH = "Error width"
ERROR_COLOR = "Error color"
ERROR_LINE_STYLE = "Error line style"

VALUE_MODES = ("Distances", "Endpoints")
DIRECTIONS = ("Both", "Negative only", "Positive only")
ERROR_LINE_STYLES = ("solid", "dashed", "dotted", "dash-dot")
_MPL_LINESTYLES = {
    "solid": "-",
    "dashed": "--",
    "dotted": ":",
    "dash-dot": "-.",
}

XY_ERROR_TABS = {
    "X errors": ("X", "Group", X_DISTANCE, X_LOWER, X_UPPER, X_VALUES, X_DIRECTION),
    "Y errors": ("Y", Y_LOWER, Y_UPPER, Y_VALUES, Y_DIRECTION),
    "Error appearance": (ERROR_CAP_SIZE, ERROR_WIDTH, ERROR_COLOR, ERROR_LINE_STYLE),
}

XY_ERROR_TAB_KEYS = {
    "X errors": "xy_error.group.x",
    "Y errors": "xy_error.group.y",
    "Error appearance": "xy_error.group.appearance",
}

XY_ERROR_LABEL_KEYS = {
    "X": "xy_error.field.x",
    "Y": "xy_error.field.y",
    "Group": "xy_error.field.group",
    X_DISTANCE: "xy_error.field.x_distance",
    X_LOWER: "xy_error.field.x_lower",
    X_UPPER: "xy_error.field.x_upper",
    X_VALUES: "xy_error.field.x_values",
    X_DIRECTION: "xy_error.field.x_direction",
    Y_LOWER: "xy_error.field.y_lower",
    Y_UPPER: "xy_error.field.y_upper",
    Y_VALUES: "xy_error.field.y_values",
    Y_DIRECTION: "xy_error.field.y_direction",
    ERROR_CAP_SIZE: "xy_error.field.cap_size",
    ERROR_WIDTH: "xy_error.field.width",
    ERROR_COLOR: "xy_error.field.color",
    ERROR_LINE_STYLE: "xy_error.field.line_style",
}

XY_ERROR_CHOICE_KEYS = {
    "Distances": "xy_error.choice.distances",
    "Endpoints": "xy_error.choice.endpoints",
    "Both": "xy_error.choice.both",
    "Negative only": "xy_error.choice.negative",
    "Positive only": "xy_error.choice.positive",
    "solid": "graph.line.solid",
    "dashed": "graph.line.dashed",
    "dotted": "graph.line.dotted",
    "dash-dot": "graph.line.dash_dot",
}


def _clean_col(options, key):
    value = options.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value)


def _parse_float(raw, field, low, high, unit="points"):
    if isinstance(raw, bool):
        raise FieldError(field, f"{field} must be a finite number between {low:g} and {high:g} {unit}.")
    text = str(raw).strip().replace(",", ".") if isinstance(raw, str) else raw
    try:
        value = float(text)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, f"{field} must be a finite number between {low:g} and {high:g} {unit}.") from None
    if not np.isfinite(value) or not low <= value <= high:
        raise FieldError(field, f"{field} must be a finite number between {low:g} and {high:g} {unit}.")
    return value


def _validate_style_options(options):
    cap_raw = options.get(ERROR_CAP_SIZE, 4.0)
    capsize = 4.0 if cap_raw in (None, "") else _parse_float(cap_raw, ERROR_CAP_SIZE, 0.0, 20.0)

    width_raw = options.get(ERROR_WIDTH)
    error_width = None if width_raw in (None, "") else _parse_float(width_raw, ERROR_WIDTH, 0.1, 10.0)

    color_raw = options.get(ERROR_COLOR)
    if color_raw in (None, ""):
        error_color = None
    else:
        if not isinstance(color_raw, str):
            raise FieldError(ERROR_COLOR, "Enter a valid Matplotlib color.")
        candidate = color_raw.strip()
        if not candidate or len(candidate) > 40 or candidate.lower() == "none" or not is_color_like(candidate):
            raise FieldError(ERROR_COLOR, "Enter a valid color, for example #b12435.")
        try:
            to_rgba(candidate)
        except (TypeError, ValueError):
            raise FieldError(ERROR_COLOR, "Enter a valid color, for example #b12435.") from None
        error_color = candidate

    style_raw = options.get(ERROR_LINE_STYLE, "solid")
    if style_raw in (None, ""):
        error_line_style = "solid"
    elif style_raw not in ERROR_LINE_STYLES:
        raise FieldError(ERROR_LINE_STYLE, "Choose solid, dashed, dotted, or dash-dot for error line style.")
    else:
        error_line_style = style_raw

    return capsize, error_width, error_color, error_line_style


def _axis_distances(data, center_col, lower_col, upper_col, mode, lower_field, upper_field, axis_name):
    center = data[center_col].to_numpy(dtype=float)
    if mode == "Distances":
        low_vals = None
        up_vals = None
        if lower_col:
            low_vals = data[lower_col].to_numpy(dtype=float)
            bad = np.flatnonzero(~np.isfinite(low_vals) | (low_vals < 0))
            if len(bad):
                row_label = data.index[int(bad[0])]
                raise FieldError(lower_field, f"{lower_field} must be finite and nonnegative (row {row_label}).")
        if upper_col:
            up_vals = data[upper_col].to_numpy(dtype=float)
            bad = np.flatnonzero(~np.isfinite(up_vals) | (up_vals < 0))
            if len(bad):
                row_label = data.index[int(bad[0])]
                raise FieldError(upper_field, f"{upper_field} must be finite and nonnegative (row {row_label}).")
        down = low_vals if low_vals is not None else up_vals
        up = up_vals if up_vals is not None else low_vals
        return down, up

    low_ep = data[lower_col].to_numpy(dtype=float)
    up_ep = data[upper_col].to_numpy(dtype=float)
    down = center - low_ep
    bad_low = np.flatnonzero(~np.isfinite(down) | (down < 0))
    if len(bad_low):
        row_label = data.index[int(bad_low[0])]
        raise FieldError(lower_field, f"{lower_field} endpoint must not exceed {axis_name} (row {row_label}).")
    up = up_ep - center
    bad_up = np.flatnonzero(~np.isfinite(up) | (up < 0))
    if len(bad_up):
        row_label = data.index[int(bad_up[0])]
        raise FieldError(upper_field, f"{upper_field} endpoint must not be below {axis_name} (row {row_label}).")
    return down, up


def xy_error_visibility(x_distance, x_lower, x_upper, x_values, y_lower, y_upper, y_values):
    """Return field visibility for AnalysisDialog based on current control selections."""
    has_legacy_x = bool(str(x_distance or "").strip())
    has_new_x = bool(str(x_lower or "").strip() or str(x_upper or "").strip())
    has_any_x = has_legacy_x or has_new_x
    has_y = bool(str(y_lower or "").strip() or str(y_upper or "").strip())
    return {
        X_VALUES: has_new_x,
        X_DIRECTION: has_any_x,
        Y_VALUES: has_y,
        Y_DIRECTION: has_y,
    }


def prune_xy_error_options(options, saved=None):
    """Omit inactive new options on freshly confirmed recipes while keeping active choices."""
    cleaned = dict(options)
    saved = saved or {}
    has_legacy_x = bool(_clean_col(cleaned, X_DISTANCE))
    has_new_x = bool(_clean_col(cleaned, X_LOWER) or _clean_col(cleaned, X_UPPER))
    has_any_x = has_legacy_x or has_new_x
    has_y = bool(_clean_col(cleaned, Y_LOWER) or _clean_col(cleaned, Y_UPPER))

    for col_key in (X_DISTANCE, X_LOWER, X_UPPER, Y_LOWER, Y_UPPER, "Group"):
        if not _clean_col(cleaned, col_key) and col_key not in saved:
            cleaned.pop(col_key, None)
        elif not _clean_col(cleaned, col_key) and col_key in {X_LOWER, X_UPPER}:
            cleaned.pop(col_key, None)

    if not has_new_x:
        cleaned.pop(X_VALUES, None)
    if not has_any_x:
        cleaned.pop(X_DIRECTION, None)
    elif cleaned.get(X_DIRECTION) == "Both" and X_DIRECTION not in saved and not has_new_x:
        cleaned.pop(X_DIRECTION, None)

    if not has_y:
        cleaned.pop(Y_VALUES, None)
        cleaned.pop(Y_DIRECTION, None)
    elif cleaned.get(Y_DIRECTION) == "Both" and Y_DIRECTION not in saved and not has_new_x:
        cleaned.pop(Y_DIRECTION, None)

    if cleaned.get(ERROR_WIDTH) in (None, "") or not str(cleaned.get(ERROR_WIDTH)).strip():
        cleaned.pop(ERROR_WIDTH, None)
    else:
        cleaned[ERROR_WIDTH] = _parse_float(cleaned[ERROR_WIDTH], ERROR_WIDTH, 0.1, 10.0)
    if cleaned.get(ERROR_COLOR) in (None, "") or not str(cleaned.get(ERROR_COLOR)).strip():
        cleaned.pop(ERROR_COLOR, None)
    elif isinstance(cleaned.get(ERROR_COLOR), str):
        cleaned[ERROR_COLOR] = cleaned[ERROR_COLOR].strip()
    if cleaned.get(ERROR_CAP_SIZE) not in (None, ""):
        cleaned[ERROR_CAP_SIZE] = _parse_float(cleaned[ERROR_CAP_SIZE], ERROR_CAP_SIZE, 0.0, 20.0)
    if cleaned.get(ERROR_CAP_SIZE) == 4.0 and ERROR_CAP_SIZE not in saved and not has_new_x:
        cleaned.pop(ERROR_CAP_SIZE, None)
    if cleaned.get(ERROR_LINE_STYLE) == "solid" and ERROR_LINE_STYLE not in saved and not has_new_x:
        cleaned.pop(ERROR_LINE_STYLE, None)
    return cleaned


def xy_errors(frame, options):
    """Validate and plot XY error bars with symmetric/asymmetric X and Y errors."""
    x = _clean_col(options, "X")
    y = _clean_col(options, "Y")
    group = _clean_col(options, "Group")
    if not x:
        raise FieldError("X", "Choose a column for X.")
    if x not in frame.columns:
        raise FieldError("X", f'Column "{x}" is not in the table.')
    if not y:
        raise FieldError("Y", "Choose a column for Y.")
    if y not in frame.columns:
        raise FieldError("Y", f'Column "{y}" is not in the table.')
    if group and group not in frame.columns:
        raise FieldError("Group", f'Column "{group}" is not in the table.')

    x_legacy = _clean_col(options, X_DISTANCE)
    x_lower = _clean_col(options, X_LOWER)
    x_upper = _clean_col(options, X_UPPER)
    y_lower = _clean_col(options, Y_LOWER)
    y_upper = _clean_col(options, Y_UPPER)

    if x_legacy and (x_lower or x_upper):
        raise FieldError(
            X_DISTANCE,
            "Use either symmetric X error distance or X lower/upper error columns, not both.",
        )

    has_new_x = bool(x_lower or x_upper)
    has_x = bool(x_legacy or has_new_x)
    has_y = bool(y_lower or y_upper)
    if not has_x and not has_y:
        raise FieldError(Y_LOWER, "Select an error distance column or both endpoint columns.")

    x_mode = "Distances"
    if has_new_x:
        x_mode = options.get(X_VALUES) or "Distances"
        if x_mode not in VALUE_MODES:
            raise FieldError(X_VALUES, "Choose Distances or Endpoints for X error values.")
        if x_mode == "Endpoints":
            if not x_lower:
                raise FieldError(X_LOWER, "Select both X lower error and X upper error for endpoints.")
            if not x_upper:
                raise FieldError(X_UPPER, "Select both X lower error and X upper error for endpoints.")

    y_mode = "Distances"
    if has_y:
        y_mode = options.get(Y_VALUES) or "Distances"
        if y_mode not in VALUE_MODES:
            raise FieldError(Y_VALUES, "Choose Distances or Endpoints for Y error values.")
        if y_mode == "Endpoints":
            if not y_lower:
                raise FieldError(Y_LOWER, "Select both Y lower error and Y upper error for endpoints.")
            if not y_upper:
                raise FieldError(Y_UPPER, "Select both Y lower error and Y upper error for endpoints.")

    x_dir = "Both"
    if has_x:
        x_dir = options.get(X_DIRECTION) or "Both"
        if x_dir not in DIRECTIONS:
            raise FieldError(X_DIRECTION, "Choose Both, Negative only, or Positive only for X error direction.")

    y_dir = "Both"
    if has_y:
        y_dir = options.get(Y_DIRECTION) or "Both"
        if y_dir not in DIRECTIONS:
            raise FieldError(Y_DIRECTION, "Choose Both, Negative only, or Positive only for Y error direction.")

    capsize, error_width, error_color, error_line_style = _validate_style_options(options)

    numeric_fields = [("X", x), ("Y", y)]
    if x_legacy:
        numeric_fields.append((X_DISTANCE, x_legacy))
    if x_lower:
        numeric_fields.append((X_LOWER, x_lower))
    if x_upper:
        numeric_fields.append((X_UPPER, x_upper))
    if y_lower:
        numeric_fields.append((Y_LOWER, y_lower))
    if y_upper:
        numeric_fields.append((Y_UPPER, y_upper))

    seen = set()
    for field_name, col_name in numeric_fields:
        if col_name not in frame.columns:
            raise FieldError(field_name, f'Column "{col_name}" is not in the table.')
        if col_name in seen:
            raise FieldError(field_name, "Select distinct columns for the analysis.")
        seen.add(col_name)
    if group:
        if group in seen:
            raise FieldError("Group", "Select distinct columns for the analysis.")
        seen.add(group)

    ordered_cols = [col for _, col in numeric_fields] + ([group] if group else [])
    data = frame.loc[:, ordered_cols].copy()
    for field_name, col_name in numeric_fields:
        series = data[col_name]
        if series.dtype == object or isinstance(series.dtype, pd.StringDtype):
            cleaned_series = series.replace(r"^\s*$", np.nan, regex=True)
        else:
            cleaned_series = series
        numeric = pd.to_numeric(cleaned_series, errors="coerce")
        if np.iscomplexobj(numeric.to_numpy()):
            raise FieldError(field_name, f'Column "{col_name}" contains complex data.')
        values = numeric.astype(float)
        invalid = cleaned_series.notna() & (~np.isfinite(values))
        if invalid.any():
            bad_pos = int(np.flatnonzero(invalid.to_numpy())[0])
            row_label = data.index[bad_pos]
            raise FieldError(field_name, f'Column "{col_name}" contains non-numeric or infinite data (row {row_label}).')
        data[col_name] = values
    if group and (data[group].dtype == object or isinstance(data[group].dtype, pd.StringDtype)):
        data[group] = data[group].replace(r"^\s*$", np.nan, regex=True)

    data = data.dropna()
    if data.empty:
        raise FieldError("Y", "No complete observations with error values.")

    if x_legacy:
        vals = data[x_legacy].to_numpy(dtype=float)
        bad = np.flatnonzero(~np.isfinite(vals) | (vals < 0))
        if len(bad):
            row_label = data.index[int(bad[0])]
            raise FieldError(X_DISTANCE, f"{X_DISTANCE} must be finite and nonnegative (row {row_label}).")
    elif has_new_x:
        _axis_distances(data, x, x_lower, x_upper, x_mode, X_LOWER, X_UPPER, "X")

    if has_y:
        _axis_distances(data, y, y_lower, y_upper, y_mode, Y_LOWER, Y_UPPER, "Y")

    is_legacy = (
        not has_new_x
        and x_dir == "Both"
        and y_dir == "Both"
        and capsize == 4.0
        and error_width is None
        and error_color is None
        and error_line_style == "solid"
    )

    figure, axes = _plot(XY_ERRORS, x, y)
    groups = data.groupby(group, sort=False, observed=True) if group else [("All", data)]
    for label, part in groups:
        if is_legacy:
            xerr = part[x_legacy].to_numpy() if x_legacy else None
            yerr = None
            if has_y:
                down, up = _axis_distances(part, y, y_lower, y_upper, y_mode, Y_LOWER, Y_UPPER, "Y")
                yerr = np.stack([down, up])
            axes.errorbar(part[x], part[y], xerr=xerr, yerr=yerr, fmt="o", capsize=4, label=str(label))
            continue

        xerr = None
        if x_legacy:
            vals = part[x_legacy].to_numpy(dtype=float)
            dx_down = np.zeros(len(part), dtype=float) if x_dir == "Positive only" else vals
            dx_up = np.zeros(len(part), dtype=float) if x_dir == "Negative only" else vals
            xerr = np.stack([dx_down, dx_up])
        elif has_new_x:
            down, up = _axis_distances(part, x, x_lower, x_upper, x_mode, X_LOWER, X_UPPER, "X")
            dx_down = np.zeros(len(part), dtype=float) if x_dir == "Positive only" else down
            dx_up = np.zeros(len(part), dtype=float) if x_dir == "Negative only" else up
            xerr = np.stack([dx_down, dx_up])

        yerr = None
        if has_y:
            down, up = _axis_distances(part, y, y_lower, y_upper, y_mode, Y_LOWER, Y_UPPER, "Y")
            dy_down = np.zeros(len(part), dtype=float) if y_dir == "Positive only" else down
            dy_up = np.zeros(len(part), dtype=float) if y_dir == "Negative only" else up
            yerr = np.stack([dy_down, dy_up])

        kwargs = {"fmt": "o", "capsize": capsize, "label": str(label)}
        if error_width is not None:
            kwargs["elinewidth"] = error_width
            kwargs["capthick"] = error_width
        if error_color is not None:
            kwargs["ecolor"] = error_color

        container = axes.errorbar(part[x], part[y], xerr=xerr, yerr=yerr, **kwargs)
        plotline, caplines, barlinecols = container.lines

        if error_color is not None:
            for cap in caplines:
                cap.set(color=error_color, markeredgecolor=error_color)

        if error_line_style != "solid":
            mpl_ls = _MPL_LINESTYLES[error_line_style]
            for whisker in barlinecols:
                whisker.set_linestyle(mpl_ls)

        if caplines and (x_dir != "Both" or y_dir != "Both"):
            kept_caps = []
            idx = 0
            if has_x and len(caplines) >= idx + 2:
                left_cap, right_cap = caplines[idx], caplines[idx + 1]
                idx += 2
                if x_dir == "Positive only":
                    left_cap.remove()
                else:
                    kept_caps.append(left_cap)
                if x_dir == "Negative only":
                    right_cap.remove()
                else:
                    kept_caps.append(right_cap)
            if has_y and len(caplines) >= idx + 2:
                bottom_cap, top_cap = caplines[idx], caplines[idx + 1]
                idx += 2
                if y_dir == "Positive only":
                    bottom_cap.remove()
                else:
                    kept_caps.append(bottom_cap)
                if y_dir == "Negative only":
                    top_cap.remove()
                else:
                    kept_caps.append(top_cap)
            axes.containers[-1] = ErrorbarContainer(
                (plotline, tuple(kept_caps), barlinecols),
                has_xerr=container.has_xerr,
                has_yerr=container.has_yerr,
                label=container.get_label(),
            )

    if group:
        axes.legend()
    return Result({"Observations": data}, figure)
