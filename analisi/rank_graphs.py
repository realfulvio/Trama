"""Dedicated rank and paired-difference plotting for Mann–Whitney and Wilcoxon signed-rank."""
from __future__ import annotations

from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from .category_graphs import COLORS, _spread
from .graph_legend import typed_group_token
from .i18n import localized_count, tr
from .point_style import attach_points, positions_of
from .processing import FieldError
from .rank_graphs_text import (
    CHOICE_KEYS,
    EN,
    IT,
    LABEL_KEYS,
    LEGACY_P_METHOD,
    RANK_PLOT,
    RANK_PLOTS,
    WILCOXON_DIFFERENCES,
)
from .rank_tests import DISCARD, MANN_WHITNEY, PRATT, WILCOXON, ZERO_DIFFERENCES
from .worksheet_row_identity import ROW_SPANS

# Keep scatter drawing fast on huge tables without altering Ranks or test inference.
VISUAL_POINT_LIMIT = 5_000


def rank_plot_options(method, options) -> tuple[str, ...]:
    """Return validated active graph options requested for Mann–Whitney or Wilcoxon."""
    if not isinstance(options, dict):
        return ()
    if method == MANN_WHITNEY:
        requested = (RANK_PLOT,)
    elif method == WILCOXON:
        requested = RANK_PLOTS
    else:
        return ()
    selected = []
    for name in requested:
        if name not in options:
            continue
        value = options[name]
        if not isinstance(value, (bool, np.bool_)):
            raise FieldError(name, f"{name}: choose on or off.")
        if value:
            selected.append(name)
    return tuple(selected)


def validated_source_positions(frame, ranks: pd.DataFrame, source_positions=None) -> np.ndarray:
    """Resolve 1-based worksheet positions safely, never blindly treating index labels as positions."""
    count = len(ranks)
    if count == 0:
        return np.empty(0, dtype=np.int64)
    if source_positions is not None:
        positions = np.asarray(source_positions, dtype=np.int64)
        if positions.ndim != 1 or len(positions) != count:
            raise ValueError("Source row positions do not match the Ranks table.")
        upper = len(frame) if frame is not None else int(positions.max())
        if int(positions.min()) < 1 or int(positions.max()) > upper:
            raise ValueError("Source row position is outside the worksheet row bounds.")
        return positions
    if frame is None:
        raise ValueError("Cannot validate source row positions without the source worksheet.")
    if "Source row" not in ranks:
        raise ValueError("Ranks table has no Source row column.")
    labels = ranks["Source row"]
    if frame.index.is_unique:
        resolved = positions_of(frame, labels)
        if resolved is None:
            raise ValueError("Ranks source rows do not match the worksheet.")
        return resolved.astype(np.int64, copy=False)
    raise ValueError("Cannot validate duplicate source index labels without explicit row positions.")


def _sample_indices(total: int, limit: int, *, values=None, priority_mask=None) -> tuple[np.ndarray, bool]:
    """Select up to ``limit`` deterministic indices for visual display only, keeping extrema and priorities."""
    if total <= limit:
        return np.arange(total, dtype=np.intp), False
    chosen: set[int] = set()
    if priority_mask is not None:
        pri = np.flatnonzero(priority_mask)
        if len(pri) > limit // 4:
            step_idx = np.linspace(0, len(pri) - 1, limit // 4, dtype=np.intp)
            pri = pri[step_idx]
        chosen.update(int(i) for i in pri)
    if values is not None and len(values) == total:
        finite = np.flatnonzero(np.isfinite(values))
        if len(finite):
            chosen.add(int(finite[int(np.argmin(values[finite]))]))
            chosen.add(int(finite[int(np.argmax(values[finite]))]))
    chosen.add(0)
    chosen.add(total - 1)
    remaining = max(0, limit - len(chosen))
    if remaining > 0:
        grid = np.linspace(0, total - 1, limit, dtype=np.intp)
        for idx in grid:
            if len(chosen) >= limit:
                break
            chosen.add(int(idx))
    return np.asarray(sorted(chosen), dtype=np.intp), True


def _format_axis_text(axes):
    axes.spines[["right", "top"]].set_visible(False)
    for label in (*axes.get_xticklabels(), *axes.get_yticklabels()):
        label.set_parse_math(False)


def _draw_legend(axes):
    handles, labels = axes.get_legend_handles_labels()
    visible = [(h, l) for h, l in zip(handles, labels) if l and not l.startswith("_")]
    if not visible:
        return None
    legend = axes.legend(
        [h for h, _ in visible],
        [l for _, l in visible],
        fontsize="small",
        frameon=False,
        loc="best",
    )
    for text in legend.get_texts():
        text.set_parse_math(False)
    return legend


def _draw_mann_whitney(figure, cell, ranks: pd.DataFrame, options: dict, frame, source_positions: np.ndarray):
    axes = figure.add_subplot(cell)
    labels = list(pd.unique(ranks["Group"]))
    total = len(ranks)
    reduced = False
    shown_total = 0
    row_spans = frame.attrs.get(ROW_SPANS) if frame is not None else None
    sheet_rows = len(frame) if frame is not None else int(source_positions.max(initial=0))
    recipe = (str(options["Response"]), str(options["Group"]))

    remaining_budget = VISUAL_POINT_LIMIT
    for idx, label in enumerate(labels):
        mask = (ranks["Group"] == label).to_numpy()
        vals = ranks.loc[mask, "Rank"].to_numpy(dtype=float)
        pos_group = source_positions[mask]
        remaining_groups = len(labels) - idx
        if total <= VISUAL_POINT_LIMIT:
            group_limit = len(vals)
        elif remaining_groups == 1:
            group_limit = max(2, remaining_budget)
        else:
            group_limit = min(
                max(2, remaining_budget - 2 * (remaining_groups - 1)),
                max(2, int(round(VISUAL_POINT_LIMIT * len(vals) / max(1, total)))),
            )
        picked, group_reduced = _sample_indices(len(vals), group_limit, values=vals)
        remaining_budget -= len(picked)
        reduced |= group_reduced
        drawn_vals = vals[picked]
        drawn_pos = pos_group[picked]
        shown_total += len(drawn_vals)

        offsets = _spread(drawn_vals, "Spread exact ties", 0.35, None)
        xs = np.full(len(drawn_vals), float(idx)) + offsets
        color = COLORS[idx % len(COLORS)]
        dots = axes.scatter(
            xs,
            drawn_vals,
            color=color,
            s=28,
            edgecolors="white",
            linewidths=0.6,
            zorder=3,
            label=str(label),
        )
        dots._tramastat_legend_key = f"group:{typed_group_token(label)}"
        attach_points(
            dots,
            drawn_pos,
            xs,
            drawn_vals,
            recipe,
            sheet_rows,
            row_spans=row_spans,
            data=frame,
        )
        if len(vals):
            median_rank = float(np.median(vals))
            axes.hlines(median_rank, idx - 0.18, idx + 0.18, color=color, linewidth=2.2, zorder=4)

    axes.set_xticks(list(range(len(labels))), [str(label) for label in labels])
    axes.set_xlim(-0.5, max(0.5, len(labels) - 0.5))
    axes.set_ylim(0.4, max(1.6, total + 0.6))
    axes.set_title(tr("rank.plot.mw_title"), parse_math=False)
    axes.set_xlabel(str(options["Group"]), parse_math=False)
    axes.set_ylabel(tr("rank.plot.mean_rank"), parse_math=False)
    _format_axis_text(axes)
    return reduced, shown_total, total


def _draw_wilcoxon_ranks(axes, ranks: pd.DataFrame, options: dict, frame, source_positions: np.ndarray, policy: str):
    diffs = ranks["Difference"].to_numpy(dtype=float)
    abs_ranks = ranks["Absolute rank"].to_numpy(dtype=float)
    included = ranks["Included"].to_numpy(dtype=bool) & np.isfinite(abs_ranks)
    pair_nums = np.arange(1, len(ranks) + 1, dtype=np.int64)
    zero_mask = (diffs == 0) & np.isfinite(abs_ranks) if policy == PRATT else np.zeros(len(ranks), dtype=bool)
    plot_mask = included | zero_mask

    total = len(ranks)
    picked, reduced = _sample_indices(
        total,
        VISUAL_POINT_LIMIT,
        values=np.where(included, np.where(diffs > 0, abs_ranks, -abs_ranks), 0.0),
        priority_mask=zero_mask,
    ) if plot_mask.any() else (np.arange(total, dtype=np.intp), False)

    row_spans = frame.attrs.get(ROW_SPANS) if frame is not None else None
    sheet_rows = len(frame) if frame is not None else int(source_positions.max(initial=0))
    recipe = (str(options["First"]), str(options["Second"]))

    drawn_pairs = pair_nums[picked]
    drawn_diffs = diffs[picked]
    drawn_abs = abs_ranks[picked]
    drawn_inc = included[picked]
    drawn_pos = source_positions[picked]
    drawn_zero = zero_mask[picked]

    signed = np.where(drawn_diffs > 0, drawn_abs, -drawn_abs)
    pos_sel = drawn_inc & (drawn_diffs > 0)
    neg_sel = drawn_inc & (drawn_diffs < 0)

    axes.axhline(0.0, color="#81929b", linewidth=1.0, linestyle="--", zorder=1)
    shown = 0
    if pos_sel.any():
        dots_pos = axes.scatter(
            drawn_pairs[pos_sel],
            signed[pos_sel],
            color=COLORS[0],
            s=28,
            edgecolors="white",
            linewidths=0.6,
            zorder=3,
            label=tr("rank.plot.positive_ranks"),
        )
        attach_points(
            dots_pos,
            drawn_pos[pos_sel],
            drawn_pairs[pos_sel],
            signed[pos_sel],
            recipe,
            sheet_rows,
            row_spans=row_spans,
            data=frame,
        )
        shown += int(pos_sel.sum())
    if neg_sel.any():
        dots_neg = axes.scatter(
            drawn_pairs[neg_sel],
            signed[neg_sel],
            color=COLORS[1],
            s=28,
            edgecolors="white",
            linewidths=0.6,
            zorder=3,
            label=tr("rank.plot.negative_ranks"),
        )
        attach_points(
            dots_neg,
            drawn_pos[neg_sel],
            drawn_pairs[neg_sel],
            signed[neg_sel],
            recipe,
            sheet_rows,
            row_spans=row_spans,
            data=frame,
        )
        shown += int(neg_sel.sum())
    if drawn_zero.any():
        zero_y = np.zeros(int(drawn_zero.sum()), dtype=float)
        dots_zero = axes.scatter(
            drawn_pairs[drawn_zero],
            zero_y,
            facecolors="none",
            edgecolors="#5c6b7a",
            marker="o",
            s=36,
            linewidths=1.4,
            zorder=4,
            label=tr("rank.plot.pratt_zeros"),
        )
        attach_points(
            dots_zero,
            drawn_pos[drawn_zero],
            drawn_pairs[drawn_zero],
            zero_y,
            recipe,
            sheet_rows,
            row_spans=row_spans,
            data=frame,
        )
        shown += int(drawn_zero.sum())

    if not included.any():
        if not drawn_zero.any():
            axes.set_ylim(-1.0, 1.0)
        axes.text(
            0.5,
            0.88 if drawn_zero.any() else 0.55,
            tr("rank.plot.all_zeros"),
            transform=axes.transAxes,
            ha="center",
            va="center",
            fontsize="small",
            color="#5c6b7a",
            parse_math=False,
        )
    max_abs = float(np.nanmax(abs_ranks[included])) if included.any() else 0.5
    pad = max(0.6, max_abs * 0.14)
    axes.set_ylim(-(max_abs + pad), max_abs + pad)
    axes.set_xlim(0.4, max(1.6, total + 0.6))
    axes.xaxis.set_major_locator(MaxNLocator(integer=True))
    policy_label = tr("rank.choice.pratt") if policy == PRATT else tr("rank.choice.discard")
    axes.set_title(tr("rank.plot.signed_ranks_title", policy=policy_label), parse_math=False)
    axes.set_xlabel(tr("ttest.plot.pair_number"), parse_math=False)
    axes.set_ylabel(tr("rank.plot.signed_rank"), parse_math=False)
    _format_axis_text(axes)
    _draw_legend(axes)
    return reduced, shown, int(plot_mask.sum())


def _draw_wilcoxon_differences(axes, ranks: pd.DataFrame, options: dict, frame, source_positions: np.ndarray):
    diffs = ranks["Difference"].to_numpy(dtype=float)
    pair_nums = np.arange(1, len(ranks) + 1, dtype=np.int64)
    total = len(ranks)
    picked, reduced = _sample_indices(total, VISUAL_POINT_LIMIT, values=diffs)
    drawn_x = pair_nums[picked]
    drawn_diffs = diffs[picked]
    drawn_pos = source_positions[picked]

    row_spans = frame.attrs.get(ROW_SPANS) if frame is not None else None
    sheet_rows = len(frame) if frame is not None else int(source_positions.max(initial=0))
    recipe = (str(options["First"]), str(options["Second"]))

    axes.axhline(0.0, color="#81929b", linewidth=1.0, linestyle="--", zorder=1)
    dots = axes.scatter(
        drawn_x,
        drawn_diffs,
        color=COLORS[0],
        s=26,
        edgecolors="white",
        linewidths=0.6,
        zorder=3,
    )
    attach_points(
        dots,
        drawn_pos,
        drawn_x,
        drawn_diffs,
        recipe,
        sheet_rows,
        row_spans=row_spans,
        data=frame,
    )
    axes.set_xlim(0.4, max(1.6, total + 0.6))
    axes.xaxis.set_major_locator(MaxNLocator(integer=True))
    axes.set_title(tr("ttest.plot.differences"), parse_math=False)
    axes.set_xlabel(tr("ttest.plot.pair_number"), parse_math=False)
    axes.set_ylabel(f'{options["First"]} − {options["Second"]}', parse_math=False)
    _format_axis_text(axes)
    return reduced, len(drawn_diffs), total


def _sampled_caption(shown: int, total: int) -> str:
    return tr(
        "rank.plot.sampled",
        shown=localized_count(f"{shown:,}"),
        total=localized_count(f"{total:,}"),
    )


def rank_test_figure(method: str, tables: dict[str, pd.DataFrame], options: dict, *,
                     frame=None, source_positions=None) -> Figure | None:
    """Build the requested Mann–Whitney or Wilcoxon figure strictly from ``tables['Ranks']``."""
    plots = rank_plot_options(method, options)
    if not plots:
        return None
    ranks = tables["Ranks"]
    positions = validated_source_positions(frame, ranks, source_positions)

    if method == MANN_WHITNEY:
        figure = Figure(figsize=(8.0, 4.8), dpi=100, layout="constrained")
        grid = figure.add_gridspec(1, 1)
        reduced, shown, total = _draw_mann_whitney(figure, grid[0, 0], ranks, options, frame, positions)
        if reduced:
            figure.supxlabel(_sampled_caption(shown, total), fontsize="small", color="#5c6b7a", parse_math=False)
        return figure

    summary = tables[method]["Value"] if method in tables and "Value" in tables[method] else None
    policy = summary.get(ZERO_DIFFERENCES) if summary is not None and ZERO_DIFFERENCES in summary else options.get(ZERO_DIFFERENCES, DISCARD)
    if policy not in (DISCARD, PRATT):
        policy = DISCARD

    panels = len(plots)
    figure = Figure(figsize=(10.5 if panels == 2 else 8.0, 4.8), dpi=100, layout="constrained")
    grid = figure.add_gridspec(1, panels)
    any_reduced = False
    max_total = 0
    max_shown = 0
    for column, plot_kind in enumerate(plots):
        axes = figure.add_subplot(grid[0, column])
        if plot_kind == RANK_PLOT:
            reduced, shown, total = _draw_wilcoxon_ranks(axes, ranks, options, frame, positions, policy)
        else:
            reduced, shown, total = _draw_wilcoxon_differences(axes, ranks, options, frame, positions)
        if reduced:
            any_reduced = True
            if total >= max_total:
                max_total, max_shown = total, shown
    if any_reduced:
        figure.supxlabel(_sampled_caption(max_shown, max_total), fontsize="small", color="#5c6b7a", parse_math=False)
    return figure
