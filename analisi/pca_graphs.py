"""Scree, loadings and symmetric biplot views for principal component analysis.

Scores and eigenvectors use :func:`analisi.exploration.pca` and its sample standard
deviation. Imported recipes can retain the archived component directions. A is the centered matrix,
divided by that standard deviation when standardization is on. The SVD is A = U D Vᵀ.
Historical scores are U D and historical eigenvectors are V.

The symmetric TramaStat biplot puts rows at U √D and variables at V √D. Their product
over every component reconstructs A. A numerically zero singular value is zero in both
sets of coordinates, so the scaling never divides by zero.
"""
from collections import Counter

import numpy as np
import pandas as pd

from . import exploration, pca_overlays, pca_regression, pca_reports, pca_retention
from .graph_legend import typed_group_token
from .processing import FieldError
from .reporting import Result, _plot

GRAPH = "Graph display"
HORIZONTAL = "Horizontal PC"
VERTICAL = "Vertical PC"
LABEL = "Label column"
SHOW_LABELS = "Show row labels"
COLOR_GROUPS = "Color groups by"
SAVED_DIRECTIONS = "PCA saved component directions"
SCORES, LOADINGS, BIPLOT = "Scores", "Loadings", "Biplot"
SCREE, PROPORTION = "Scree", "Proportion of variance"
VIEWS = (SCORES, LOADINGS, BIPLOT, SCREE, PROPORTION)
ONE_DIMENSION = (SCREE, PROPORTION)
POINT_VIEWS = (SCORES, BIPLOT)
COORDINATES = "PC graph coordinates"
SETTINGS = "Settings"
TABS = {"Graph": (GRAPH, HORIZONTAL, VERTICAL, LABEL, SHOW_LABELS, COLOR_GROUPS)}
_KEYS = TABS["Graph"]
# Below this fraction of the leading eigenvalue, a component is numerically empty.
_VARIANCE_SCALE = 1e-10
_LABEL_LIMIT = 60
MAX_COLOR_GROUPS = 40
_BIPLOT = ("Symmetric biplot: row coordinates are U·sqrt(D) and variable coordinates are V·sqrt(D), "
           "using {directions}. The product of the two matrices over every component "
           "reconstructs the centered data matrix, after standardization when that option is on. "
           "A numerically zero singular value is zero in both.")
_LOADINGS_STD = ("Loadings are eigenvectors multiplied by the square root of the sample eigenvalue. "
                 "With standardization they are correlations between each variable and the component.")
_LOADINGS_RAW = ("Loadings are eigenvectors multiplied by the square root of the sample eigenvalue. "
                 "Without standardization they keep the variable's unit and are not correlations.")
_LABELS_OMITTED = ("Row labels stay in PC graph coordinates and are omitted from the figure because "
                   "more than 60 were requested.")


def present(options):
    """True when the recipe carries any graph key. Older recipes keep the PC1/PC2 scatter."""
    return any(key in options for key in (*_KEYS, pca_overlays.KIND))


def _view(options):
    if GRAPH not in options or options[GRAPH] in (None, ""):
        return SCORES
    view = options[GRAPH]
    if view not in VIEWS:
        raise FieldError(GRAPH, "Choose a graph display.")
    return view


def _whole(value, field):
    if isinstance(value, bool):
        number = None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = None
    if number is None or not np.isfinite(number) or not number.is_integer():
        raise FieldError(field, f"{field} must be a whole number.")
    return int(number)


def _component(options, field, default, count):
    if field not in options or options[field] in (None, ""):
        index = default
    else:
        index = _whole(options[field], field)
    if not 1 <= index <= count:
        raise FieldError(field, f"{field} must be a component from 1 to {count}.")
    return index - 1


def _flag(options, active):
    if not active or SHOW_LABELS not in options or options[SHOW_LABELS] in (None, ""):
        return False
    value = options[SHOW_LABELS]
    if not isinstance(value, bool):
        raise FieldError(SHOW_LABELS, f"{SHOW_LABELS} must be yes or no.")
    return value


def _label_column(frame, variables, options, active):
    if not active or LABEL not in options or options[LABEL] in (None, ""):
        return None
    name = options[LABEL]
    if name in variables:
        raise FieldError(LABEL, "The label column must not be one of the variables.")
    if name not in frame:
        raise FieldError(LABEL, f'Column "{name}" is not in the table.')
    return name


def _complete_mask(frame, variables):
    """Rows kept by the historical PCA filter, in their original order."""
    mask = np.ones(len(frame), dtype=bool)
    for name in variables:
        values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
        mask &= frame[name].notna().to_numpy() & np.isfinite(values)
    return mask


def _labels(frame, mask, column):
    source = frame.index.to_numpy()[mask]
    if column is None:
        label = np.array([""] * int(mask.sum()), dtype=object)
    else:
        label = np.array(["" if pd.isna(value) else str(value) for value in frame.loc[mask, column]], dtype=object)
    return source, label


def _color_data(frame, options, view, mask):
    column = options.get(COLOR_GROUPS)
    if view not in POINT_VIEWS or column in (None, ""):
        return None, None
    if not isinstance(column, str) or column not in frame:
        raise FieldError(COLOR_GROUPS, "Choose a color grouping column from this table.")
    values = frame.loc[mask, column].to_numpy(dtype=object)
    return column, [None if pd.isna(value) or isinstance(value, str) and not value.strip() else value
                    for value in values]


def _dead(eigenvalues):
    scale = float(np.max(eigenvalues)) if len(eigenvalues) else 0.0
    return np.asarray(eigenvalues, dtype=float) <= scale * _VARIANCE_SCALE


def _apply_saved_directions(options, eigenvectors, scores, eigenvalues):
    """Match the sign of each living component to a compatible standardized reference."""
    references = options.get(SAVED_DIRECTIONS)
    if options["Standardize"] is not True or not isinstance(references, dict):
        return False
    flipped = False
    variables = set(eigenvectors.index)
    for name in eigenvectors.columns[~_dead(eigenvalues)]:
        reference = references.get(name)
        if not isinstance(reference, dict) or reference.keys() != variables:
            continue
        values = [reference[variable] for variable in eigenvectors.index]
        if any(type(value) not in (int, float) or not -1.000001 <= value <= 1.000001 for value in values):
            continue
        norm = np.linalg.norm(values)
        if norm and eigenvectors[name].to_numpy() @ values < -.95 * norm:
            eigenvectors[name] *= -1
            scores[name] *= -1
            flipped = True
    return flipped


def _coordinates(scores, eigenvectors, eigenvalues):
    """Loadings V√λ and symmetric biplot coordinates. Dead components are zero on both sides."""
    values = np.asarray(eigenvalues, dtype=float)
    singular = np.sqrt(np.clip(values, 0.0, None) * (len(scores) - 1))
    root = np.sqrt(singular)
    dead = _dead(values)
    loadings = np.asarray(eigenvectors, dtype=float) * np.sqrt(np.clip(values, 0.0, None))
    rows = np.asarray(scores, dtype=float).copy()
    variables = np.asarray(eigenvectors, dtype=float).copy()
    for index, (empty, scale) in enumerate(zip(dead, root)):
        if empty or not np.isfinite(scale) or scale == 0:
            rows[:, index] = 0.0
            variables[:, index] = 0.0
            loadings[:, index] = 0.0
        else:
            rows[:, index] = rows[:, index] / scale
            variables[:, index] = variables[:, index] * scale
    return loadings, rows, variables


def _pair(options, eigenvalues):
    count = len(eigenvalues)
    horizontal = _component(options, HORIZONTAL, 1, count)
    vertical = _component(options, VERTICAL, 2, count)
    if horizontal == vertical:
        raise FieldError(VERTICAL, "Horizontal PC and Vertical PC must be different components.")
    dead = _dead(eigenvalues)
    if dead[horizontal]:
        raise FieldError(HORIZONTAL, f"{HORIZONTAL} must be a component with positive variance.")
    if dead[vertical]:
        raise FieldError(VERTICAL, f"{VERTICAL} must be a component with positive variance.")
    return horizontal, vertical


def _axis(names, variance, index):
    return f"{names[index]} ({variance[index]:g}%)"


def _literal(text):
    """Keep a dollar sign as text. Matplotlib would otherwise read it as math."""
    return str(text).replace("$", r"\$")


def _annotate(axes, x, y, text):
    axes.annotate(_literal(text), (x, y), textcoords="offset points", xytext=(4, 4), fontsize=8, zorder=4)


def _observation_points(axes, coordinates, group_column, values, marker_colors):
    if group_column is None:
        artist = axes.scatter(coordinates[:, 0], coordinates[:, 1], zorder=3)
        return [("All", "All", slice(None), artist.get_facecolors()[0])]
    groups = {}
    for row, value in enumerate(values):
        key = f"group:{typed_group_token(value)}" if value is not None else "gid:pca-missing-color-group"
        caption = str(value) if value is not None else "Missing group"
        groups.setdefault(key, (caption, []))[1].append(row)
    if len(groups) > MAX_COLOR_GROUPS:
        raise FieldError(COLOR_GROUPS, f"Choose a column with at most {MAX_COLOR_GROUPS} color groups.")
    collisions = Counter(caption for caption, _ in groups.values())
    artists, captions, point_groups = [], [], []
    for key, (caption, rows) in groups.items():
        if collisions[caption] > 1:
            identity = "missing" if key.startswith("gid:") else key.split(":")[1]
            caption = f"{caption} ({identity})"
        label = _literal(caption)
        artist = axes.scatter(coordinates[rows, 0], coordinates[rows, 1], label=label,
                              color=marker_colors.get(key.removeprefix("group:")), zorder=3)
        artist._tramastat_legend_key = key
        artists.append(artist)
        captions.append(label)
        point_groups.append((key, caption, rows, artist.get_facecolors()[0]))
    legend = axes.legend(artists, captions, title=_literal(group_column), ncols=(len(artists) + 9) // 10)
    legend._tramastat_legend_keys = tuple(groups)
    return point_groups


def _figure(view, names, variance, eigenvalues, horizontal, vertical, row_xy, variable_xy, row_labels,
            variable_names, show_rows, parallel=None, *, group_column=None, group_values=None, overlay=None,
            marker_colors=None):
    if view == SCREE:
        figure, axes = _plot("Scree", "Principal component", "Eigenvalue")
        # The observed series stays unlabeled so its style key remains the historical line.
        axes.plot(np.arange(1, len(eigenvalues) + 1), eigenvalues, marker="o")
        if parallel is not None:
            percentile, quantile = parallel
            line, = axes.plot(np.arange(1, len(quantile) + 1), quantile, linestyle="--", marker="None",
                              label=pca_retention.percentile_label(percentile))
            line.set_gid(pca_retention.REFERENCE_GID)
            axes.legend()
        axes.set_xticks(np.arange(1, len(eigenvalues) + 1))
        return figure, None
    if view == PROPORTION:
        figure, axes = _plot("Proportion of variance", "Principal component", "Variance (%)")
        numbers = np.arange(1, len(variance) + 1)
        cumulative = np.cumsum(variance)
        axes.plot(numbers, variance, marker="o", label="Variance (%)")
        axes.plot(numbers, cumulative, marker="o", label="Cumulative (%)")
        axes.legend()
        axes.set_xticks(numbers)
        return figure, None
    xlabel, ylabel = _axis(names, variance, horizontal), _axis(names, variance, vertical)
    titles = {SCORES: "Principal component scores", LOADINGS: "Principal component loadings",
              BIPLOT: "Principal component biplot"}
    figure, axes = _plot(titles[view], xlabel, ylabel)
    axes.axhline(0, color="#d0d5dd", linewidth=.8, zorder=0)
    axes.axvline(0, color="#d0d5dd", linewidth=.8, zorder=0)
    contours = None
    if view in POINT_VIEWS:
        point_groups = _observation_points(axes, row_xy, group_column, group_values, marker_colors or {})
        if overlay is not None:
            contours = pca_overlays.draw(axes, row_xy, point_groups, overlay)
        if show_rows:
            for x, y, label in zip(row_xy[:, 0], row_xy[:, 1], row_labels):
                if label:
                    _annotate(axes, x, y, label)
    if view in (LOADINGS, BIPLOT):
        for x, y, name in zip(variable_xy[:, 0], variable_xy[:, 1], variable_names):
            axes.annotate("", xy=(x, y), xytext=(0, 0),
                          arrowprops={"arrowstyle": "->", "color": "#9a3412"}, zorder=2)
            _annotate(axes, x, y, name)
    axes.margins(.15)
    return figure, contours


def _settings(view, standardize, labels_omitted, saved_directions):
    directions = "saved component directions" if saved_directions else "the canonical eigenvector signs"
    notes = {"Graph display": view, "Biplot": _BIPLOT.format(directions=directions),
             "Loadings": _LOADINGS_STD if standardize else _LOADINGS_RAW}
    if labels_omitted:
        notes["Row labels"] = _LABELS_OMITTED
    return pd.DataFrame({"Value": notes})


def validate(frame, options):
    """Raise a graph FieldError without drawing parallel replicates."""
    if not present(options):
        return
    # The probe has no selection key, so it would regress on every living component. The regression is left to the
    # analysis itself, which has the real selection; its field checks stay in the dialog (pca_regression.settings).
    skipped = pca_retention.OPTION_NAMES | pca_regression.OPTION_NAMES
    probe = {key: value for key, value in options.items() if key not in skipped}
    pca_result(frame, probe)


def _finish(tables, figure, frame, options, regression, parts, eigenvectors, scores, retention):
    """Append the PCR sheets after the PCA ones; a PCR plot replaces the PCA figure, Keep PCA does not."""
    if regression is not None:
        found = pca_regression.regress(frame, options, regression, parts, eigenvectors, scores, retention)
        tables.update(found.tables)
        if found.figure is not None:
            figure = found.figure
    return Result(tables, figure)


def pca_result(frame, options):
    """Historical PCA sheets plus the coordinates and figure of the requested view."""
    view = _view(options)
    variables = list(options["Variables"])
    flat = view in ONE_DIMENSION
    column = _label_column(frame, variables, options, not flat)
    show = _flag(options, not flat)
    # Field errors of the regression come before any estimation; PCR is None unless it was explicitly turned on.
    regression = pca_regression.settings(frame, options)
    parts, eigenvectors, scores = exploration.pca(frame, variables, options["Standardize"])
    eigenvalues = parts["Eigenvalue"].to_numpy(dtype=float)
    oriented = _apply_saved_directions(options, eigenvectors, scores, eigenvalues)
    variance = parts["Variance (%)"].to_numpy(dtype=float)
    names = list(parts.index)
    mask = _complete_mask(frame, variables)
    source, labels = _labels(frame, mask, column)
    group_column, group_values = _color_data(frame, options, view, mask)
    overlay = pca_overlays.configuration(options, view in POINT_VIEWS, group_column)
    if len(source) != len(scores):
        raise ValueError("PCA row filter did not match the score rows.")
    loadings, rows, variable_coordinates = _coordinates(scores, eigenvectors, eigenvalues)
    score_values = np.asarray(scores, dtype=float)
    if not flat:
        # Reject an empty or repeated axis before a parallel simulation allocates replicates.
        horizontal, vertical = _pair(options, eigenvalues)
    retention = pca_retention.assess(frame, options, parts, eigenvectors, scores)
    parallel = None
    if view == SCREE and retention.quantile is not None:
        parallel = (retention.percentile, retention.quantile)
    if flat:
        table = pd.DataFrame({
            "PC": np.arange(1, len(names) + 1),
            "Eigenvalue": eigenvalues,
            "Variance (%)": variance,
            "Cumulative (%)": parts["Cumulative (%)"].to_numpy(dtype=float),
        })
        figure, _ = _figure(view, names, variance, eigenvalues, 0, 1, score_values, loadings, labels, variables, False,
                            parallel)
        tables = {"Explained variance": parts, "Eigenvectors": eigenvectors, "Scores": scores,
                  COORDINATES: table, SETTINGS: _settings(view, bool(options["Standardize"]), False, oriented)}
        tables.update(retention.tables)
        tables.update(pca_reports.optional_tables(frame, options, parts, eigenvectors, scores, retention))
        return _finish(tables, figure, frame, options, regression, parts, eigenvectors, scores, retention)
    omitted = bool(show and len(labels) > _LABEL_LIMIT)
    drawn = show and not omitted
    if view == SCORES:
        table = pd.DataFrame({
            "Source row": source, "Label": labels,
            "Horizontal": score_values[:, horizontal], "Vertical": score_values[:, vertical],
        })
        drawn_rows, drawn_variables = score_values, loadings
    elif view == LOADINGS:
        table = pd.DataFrame({
            "Variable": list(variables),
            "Horizontal": loadings[:, horizontal],
            "Vertical": loadings[:, vertical],
        })
        drawn_rows, drawn_variables = score_values, loadings
    else:
        table = pd.DataFrame({
            "Kind": ["Row"] * len(source) + ["Variable"] * len(variables),
            "Identity": [*source, *variables],
            "Label": [*labels, *variables],
            "Horizontal": [*rows[:, horizontal], *variable_coordinates[:, horizontal]],
            "Vertical": [*rows[:, vertical], *variable_coordinates[:, vertical]],
        })
        drawn_rows, drawn_variables = rows, variable_coordinates
    settings = _settings(view, bool(options["Standardize"]), omitted, oriented)
    if group_column is not None:
        values = group_values if view == SCORES else [*group_values, *([None] * len(variables))]
        table["Color group"] = pd.Series(values, dtype=object)
        settings.loc[COLOR_GROUPS, "Value"] = group_column
    figure, contours = _figure(view, names, variance, eigenvalues, horizontal, vertical,
                               drawn_rows[:, [horizontal, vertical]], drawn_variables[:, [horizontal, vertical]],
                               labels, variables, drawn, parallel, group_column=group_column,
                               group_values=group_values, overlay=overlay,
                               marker_colors=pca_overlays.saved_point_colors(options, group_column))
    tables = {"Explained variance": parts, "Eigenvectors": eigenvectors, "Scores": scores,
              COORDINATES: table, SETTINGS: settings}
    tables.update(retention.tables)
    tables.update(pca_reports.optional_tables(frame, options, parts, eigenvectors, scores, retention))
    if contours is not None:
        tables[pca_overlays.SHEET] = contours
    return _finish(tables, figure, frame, options, regression, parts, eigenvectors, scores, retention)
