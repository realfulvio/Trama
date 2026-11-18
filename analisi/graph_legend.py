"""Validation, stable entry identity, and idempotent formatting for native Matplotlib legends."""
from dataclasses import dataclass
from math import isfinite
import re
from sys import float_info
from urllib.parse import quote, unquote

import numpy as np
from matplotlib.colors import is_color_like, to_hex
from matplotlib.legend import Legend
from matplotlib.offsetbox import HPacker, TextArea, VPacker

LEGEND_OPTIONS_KEY = "legend_options"
LEGEND_OPTION_KEYS = frozenset({
    "title",
    "columns",
    "frame",
    "facecolor",
    "edgecolor",
    "width",
    "alpha",
    "reverse",
    "labels",
})
MAX_LEGEND_TEXT_LENGTH = 160
MAX_LEGEND_KEY_LENGTH = 1024
MAX_LEGEND_COLUMNS = 8
MAX_LEGEND_BORDER_WIDTH = 10.0

# Documented grammar for stable legend entry keys in legend_options["labels"].
# Keys never use translated UI captions or reversed legend positions:
#   - Series keys:       (line|errorbar|scatter|bar|xy):<index>:<label>
#   - Group keys:        (box|violin|pair|trajectory|trajectory-mean):<identity>
#   - Typed data groups: group:(bool|int|float|str|datetime|repr):<value>
#   - FDR keys:          fdr:(threshold|discovery|other)
#   - Artist GID keys:   gid:<artist_gid>
#   - Scoped fallbacks:  entry:<legend_scope>#<creation_index>
#   - Panel entries:     scope:<URL-encoded legend_scope>:<original entry key>
_ENTRY_KEY_PATTERNS = (
    re.compile(r"(line|errorbar|scatter|bar|xy):[1-9][0-9]*:.*", re.DOTALL),
    re.compile(r"(box|violin|pair|trajectory|trajectory-mean):.+", re.DOTALL),
    re.compile(r"group:(bool|int|float|str|datetime|repr):.+", re.DOTALL),
    re.compile(r"fdr:(threshold|discovery|other)"),
    re.compile(r"gid:.+", re.DOTALL),
    re.compile(
        r"entry:(axes:[0-9]+:(main|extra:[0-9]+|gid:.+)|qq:(normal|lognormal)|figure:([0-9]+|gid:.+))#[0-9]+",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class LegendEntry:
    """One legend entry identified by a stable key independent of language and display order."""
    scope: str
    key: str
    label: str
    display_name: str
    legend: Legend


def typed_group_token(value):
    """Return a type-preserving identity token so e.g. integer 1 and string '1' never collide."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        return f"float:{value!r}"
    if isinstance(value, str):
        return f"str:{value}"
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return f"datetime:{value.isoformat()}"
    return f"repr:{type(value).__name__}:{value!r}"


def is_valid_entry_key(key):
    """Return True if ``key`` matches the documented stable legend entry key grammar."""
    if not isinstance(key, str) or not (1 <= len(key) <= MAX_LEGEND_KEY_LENGTH):
        return False
    if key.startswith("scope:"):
        encoded, separator, original = key[6:].partition(":")
        scope = unquote(encoded)
        if not separator or quote(scope, safe="") != encoded:
            return False
        if not re.fullmatch(r"axes:[0-9]+:(main|extra:[0-9]+|gid:.+)|qq:(normal|lognormal)|figure:([0-9]+|gid:.+)", scope):
            return False
        return any(pattern.fullmatch(original) is not None for pattern in _ENTRY_KEY_PATTERNS)
    return any(pattern.fullmatch(key) is not None for pattern in _ENTRY_KEY_PATTERNS)


def _panel_entry_key(scope, key):
    # Retain published single-legend identities. Q–Q names must remain stable
    # even if the other distribution is removed and the axes indices change.
    if scope in {"axes:0:main", "figure:0"} or key.startswith(("entry:", "scope:")):
        return key
    return f"scope:{quote(scope, safe='')}:{key}"


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        numeric = float(value)
    except OverflowError:
        return False
    return isfinite(numeric) and abs(numeric) <= float_info.max


def _validate_color(value, message):
    if isinstance(value, str):
        if not value.strip() or len(value) > 40:
            raise ValueError(message)
        try:
            valid = is_color_like(value)
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(message)
        return value
    if isinstance(value, (tuple, list)) and len(value) in (3, 4):
        if any(not _finite_number(channel) or not (0.0 <= float(channel) <= 1.0) for channel in value):
            raise ValueError(message)
        try:
            return to_hex(tuple(float(channel) for channel in value), keep_alpha=len(value) == 4)
        except (TypeError, ValueError) as error:
            raise ValueError(message) from error
    raise ValueError(message)


def validate_legend_options(options):
    """Validate legend formatting ``options`` and return a new canonical dictionary."""
    if not isinstance(options, dict):
        raise ValueError("Invalid legend formatting options.")
    unknown = set(options) - LEGEND_OPTION_KEYS
    if unknown:
        raise ValueError("Invalid legend formatting options.")
    canonical = {}
    if "title" in options:
        title = options["title"]
        if not isinstance(title, str) or len(title) > MAX_LEGEND_TEXT_LENGTH:
            raise ValueError("Enter a legend title of up to 160 characters.")
        canonical["title"] = title
    if "columns" in options:
        columns = options["columns"]
        if type(columns) is not int or not (1 <= columns <= MAX_LEGEND_COLUMNS):
            raise ValueError("Enter a legend column count from 1 to 8.")
        canonical["columns"] = columns
    if "frame" in options:
        frame = options["frame"]
        if type(frame) is not bool:
            raise ValueError("Invalid legend frame setting.")
        canonical["frame"] = frame
    if "facecolor" in options:
        canonical["facecolor"] = _validate_color(
            options["facecolor"], "Enter a valid legend background color, for example #ffffff."
        )
    if "edgecolor" in options:
        canonical["edgecolor"] = _validate_color(
            options["edgecolor"], "Enter a valid legend border color, for example #445566."
        )
    if "width" in options:
        width = options["width"]
        if not _finite_number(width) or not (0.0 <= float(width) <= MAX_LEGEND_BORDER_WIDTH):
            raise ValueError("Enter a legend border width between 0 and 10 points.")
        canonical["width"] = float(width)
    if "alpha" in options:
        alpha = options["alpha"]
        if not _finite_number(alpha) or not (0.0 <= float(alpha) <= 1.0):
            raise ValueError("Enter a legend frame opacity between 0 and 1.")
        canonical["alpha"] = float(alpha)
    if "reverse" in options:
        reverse = options["reverse"]
        if type(reverse) is not bool:
            raise ValueError("Invalid legend entry order setting.")
        canonical["reverse"] = reverse
    if "labels" in options:
        raw_labels = options["labels"]
        if not isinstance(raw_labels, dict) or len(raw_labels) > 512:
            raise ValueError("Invalid legend entry labels.")
        cleaned_labels = {}
        for key, label in raw_labels.items():
            if not is_valid_entry_key(key):
                raise ValueError("Invalid legend entry key.")
            if not isinstance(label, str) or not (1 <= len(label) <= MAX_LEGEND_TEXT_LENGTH) or label.startswith("_"):
                raise ValueError(
                    "Enter a legend entry label of 1 to 160 characters that does not start with an underscore."
                )
            cleaned_labels[key] = label
        canonical["labels"] = cleaned_labels
    return canonical


def is_non_native_figure(figure):
    """Return True when ``figure`` holds only non-native raster/archived preview axes."""
    if figure is None:
        return False
    axes = getattr(figure, "axes", ())
    if not axes:
        return False
    return all(getattr(ax, "_tramastat_non_native", False) for ax in axes)


def _figure_legends(figure):
    """Return all legends on ``figure`` as ``(scope, axes_or_none, legend)`` in deterministic order."""
    if figure is None:
        return []
    found = []
    seen = set()
    for ax_idx, ax in enumerate(getattr(figure, "axes", ())):
        main = ax.get_legend()
        if main is not None and id(main) not in seen:
            seen.add(id(main))
            panel_id = getattr(ax, "_trama_qq_panel", None)
            scope = f"qq:{panel_id}" if panel_id else f"axes:{ax_idx}:main"
            found.append((scope, ax, main))
        extra_idx = 0
        for artist in getattr(ax, "artists", ()):
            if isinstance(artist, Legend) and id(artist) not in seen:
                seen.add(id(artist))
                gid = artist.get_gid()
                scope = f"axes:{ax_idx}:gid:{gid}" if gid else f"axes:{ax_idx}:extra:{extra_idx}"
                extra_idx += 1
                found.append((scope, ax, artist))
    for fig_idx, leg in enumerate(getattr(figure, "legends", ())):
        if id(leg) not in seen:
            seen.add(id(leg))
            gid = leg.get_gid()
            scope = f"figure:gid:{gid}" if gid else f"figure:{fig_idx}"
            found.append((scope, None, leg))
    return found


def _series_key_map(figure):
    """Map artist ``id(artist)`` -> canonical ``GraphSeries.key`` across all axes in ``figure``."""
    from .presentation import graph_series

    mapping = {}
    for ax in getattr(figure, "axes", ()):
        for series in graph_series(ax):
            mapping.setdefault(id(series.artist), series.key)
    return mapping


def _group_key_map(figure):
    """Map group artist ``id(artist)`` -> ``GraphGroup.key`` across all axes in ``figure``."""
    from .presentation import graph_groups

    mapping = {}
    for ax in getattr(figure, "axes", ()):
        for group in graph_groups(ax):
            for artist, _ in group.artists:
                mapping.setdefault(id(artist), group.key)
    return mapping


def _is_fdr_figure(figure):
    return any(
        str(line.get_gid() or "").startswith("fdr-threshold-")
        for ax in getattr(figure, "axes", ())
        for line in getattr(ax, "lines", ())
    )


def _match_source_handles(figure, axes, legend):
    """Best-effort mapping from legend entry index to original plotted artist when available."""
    texts = [text.get_text() for text in legend.get_texts()]
    count = len(texts)
    if count == 0:
        return []
    if axes is not None and legend is axes.get_legend():
        order = getattr(axes, "_tramastat_xy_order", None)
        if order:
            from .presentation import xy_artists, xy_legend_handles

            # Lines and bar containers of every axes in Y-column order; then only the series the legend shows.
            xy_handles = [artist for artist in xy_artists(axes)
                          if (artist.get_label() or "") and not (artist.get_label() or "").startswith("_")]
            for candidates in (xy_handles, xy_legend_handles(axes)):
                if len(candidates) == count and [h.get_label() for h in candidates] == texts:
                    return candidates
        auto_handles, auto_labels = axes.get_legend_handles_labels()
        if len(auto_handles) == count and auto_labels == texts:
            return auto_handles
    if axes is None and legend in getattr(figure, "legends", ()):
        all_handles, all_labels = [], []
        for ax in getattr(figure, "axes", ()):
            handles, labels = ax.get_legend_handles_labels()
            all_handles.extend(handles)
            all_labels.extend(labels)
        if len(all_handles) == count and all_labels == texts and not _is_fdr_figure(figure):
            return all_handles
    return [None] * count


def _resolve_entry_keys(figure, scope, axes, legend):
    """Determine stable keys for all entries of ``legend`` in its creation order."""
    explicit = getattr(legend, "_tramastat_legend_keys", None)
    count = len(legend.get_texts())
    if isinstance(explicit, (list, tuple)) and len(explicit) == count:
        if all(is_valid_entry_key(key) for key in explicit) and len(set(explicit)) == count:
            return list(explicit)

    series_by_id = _series_key_map(figure)
    groups_by_id = _group_key_map(figure)
    source_handles = _match_source_handles(figure, axes, legend)
    fdr_mode = axes is None and _is_fdr_figure(figure)

    keys = []
    used = set()
    for idx in range(count):
        source = source_handles[idx] if idx < len(source_handles) else None
        proxy = legend.legend_handles[idx] if idx < len(legend.legend_handles) else None
        key = None
        for candidate_artist in (source, proxy):
            if candidate_artist is None:
                continue
            if scope.startswith("qq:") and axes is not None:
                # The reference label includes fitted coefficients in a single
                # panel, so its text cannot serve as identity after recalculation.
                if candidate_artist is getattr(axes, "_trama_qq_points", None):
                    key = "gid:qq-points"
                    break
                if candidate_artist is getattr(axes, "_trama_qq_reference", None):
                    key = "gid:qq-reference"
                    break
            explicit_key = getattr(candidate_artist, "_tramastat_legend_key", None)
            if is_valid_entry_key(explicit_key):
                key = explicit_key
                break
            if id(candidate_artist) in groups_by_id:
                key = groups_by_id[id(candidate_artist)]
                break
            if id(candidate_artist) in series_by_id:
                key = series_by_id[id(candidate_artist)]
                break
            gid = candidate_artist.get_gid() if hasattr(candidate_artist, "get_gid") else None
            if gid:
                candidate = f"gid:{gid}"
                if is_valid_entry_key(candidate):
                    key = candidate
                    break
        if key is None and fdr_mode and proxy is not None:
            linestyle = getattr(proxy, "get_linestyle", lambda: None)()
            marker = getattr(proxy, "get_marker", lambda: None)()
            if linestyle == "--":
                key = "fdr:threshold"
            elif marker == "o":
                key = "fdr:discovery"
            elif marker == "x":
                key = "fdr:other"
        if key is None or key in used:
            key = f"entry:{scope}#{idx}"
        used.add(key)
        keys.append(key)
    return keys


def _extract_legend_items(legend):
    """Extract ``(itembox, handlebox, textbox, proxy_handle)`` tuples in current visual order."""
    raw_items = []
    handle_box = getattr(legend, "_legend_handle_box", None)
    if handle_box is not None:
        for column in handle_box.get_children():
            for itembox in column.get_children():
                children = itembox.get_children()
                if len(children) != 2:
                    continue
                if isinstance(children[0], TextArea):
                    textbox, handlebox = children[0], children[1]
                    markerfirst = False
                else:
                    handlebox, textbox = children[0], children[1]
                    markerfirst = True
                raw_items.append((itembox, handlebox, textbox, markerfirst))
    proxies = list(getattr(legend, "legend_handles", ()))
    if len(raw_items) != len(proxies):
        return []
    return [
        (itembox, handlebox, textbox, markerfirst, proxy)
        for (itembox, handlebox, textbox, markerfirst), proxy in zip(raw_items, proxies, strict=True)
    ]


def _snapshot_legend(figure, scope, axes, legend):
    """Capture the original, pre-formatting state of ``legend`` once."""
    existing = getattr(legend, "_tramastat_legend_snapshot", None)
    if existing is not None:
        return existing
    items = _extract_legend_items(legend)
    keys = _resolve_entry_keys(figure, scope, axes, legend)
    if len(keys) != len(items):
        keys = [f"entry:{scope}#{idx}" for idx in range(len(items))]
    keys = [_panel_entry_key(scope, key) for key in keys]
    frame = legend.get_frame()
    title_artist = legend.get_title()
    snapshot = {
        "scope": scope,
        "title": title_artist.get_text(),
        "title_parse_math": bool(title_artist.get_parse_math()),
        "ncols": int(getattr(legend, "_ncols", 1)),
        "frameon": bool(legend.get_frame_on()),
        "facecolor": frame.get_facecolor(),
        "edgecolor": frame.get_edgecolor(),
        "linewidth": float(frame.get_linewidth()),
        "alpha": frame.get_alpha(),
        "entries": [
            {
                "key": key,
                "label": textbox.get_text(),
                "parse_math": bool(textbox._text.get_parse_math()),
                "itembox": itembox,
                "handlebox": handlebox,
                "textbox": textbox,
                "markerfirst": markerfirst,
                "proxy": proxy,
            }
            for key, (itembox, handlebox, textbox, markerfirst, proxy) in zip(keys, items, strict=True)
        ],
    }
    legend._tramastat_legend_snapshot = snapshot
    return snapshot


def capture_legend_snapshots(figure):
    """Snapshot every legend in ``figure`` before any preview or style edits occur."""
    for scope, axes, legend in _figure_legends(figure):
        _snapshot_legend(figure, scope, axes, legend)


def _repack_legend(legend, entries, ncols):
    """Rebuild ``legend._legend_handle_box`` for ``entries`` and ``ncols`` without recreating ``Legend``."""
    effective_ncols = max(1, int(ncols))
    legend._ncols = effective_ncols
    fontsize = getattr(legend, "_fontsize", 10.0)
    columnbox = []
    if entries:
        for col_indices in filter(len, np.array_split(np.arange(len(entries)), effective_ncols)):
            itemboxes = []
            for idx in col_indices:
                entry = entries[int(idx)]
                itembox = entry["itembox"]
                itembox._children = (
                    [entry["handlebox"], entry["textbox"]]
                    if entry["markerfirst"]
                    else [entry["textbox"], entry["handlebox"]]
                )
                itemboxes.append(itembox)
            alignment = "baseline" if entries[int(col_indices[0])]["markerfirst"] else "right"
            columnbox.append(VPacker(pad=0, sep=legend.labelspacing * fontsize, align=alignment, children=itemboxes))
    mode = "expand" if getattr(legend, "_mode", None) == "expand" else "fixed"
    legend._legend_handle_box = HPacker(
        pad=0, sep=legend.columnspacing * fontsize, align="baseline", mode=mode, children=columnbox
    )
    legend._legend_box._children = [legend._legend_title_box, legend._legend_handle_box]
    legend._legend_box.set_figure(legend.get_figure(root=False))
    legend._legend_box.axes = legend.axes
    legend.texts = [entry["textbox"]._text for entry in entries]
    legend.legend_handles = [entry["proxy"] for entry in entries]
    legend.stale = True


def _restore_legend(legend, snapshot):
    """Restore ``legend`` to its captured ``snapshot`` state."""
    title_artist = legend.get_title()
    legend.set_title(snapshot["title"])
    title_artist.set_parse_math(snapshot["title_parse_math"])

    for entry in snapshot["entries"]:
        entry["textbox"].set_text(entry["label"])
        entry["textbox"]._text.set_parse_math(entry["parse_math"])
    _repack_legend(legend, snapshot["entries"], snapshot["ncols"])

    legend.set_frame_on(snapshot["frameon"])
    frame = legend.get_frame()
    if snapshot["alpha"] is None:
        frame.set_alpha(None)
        frame.set_facecolor(snapshot["facecolor"])
        frame.set_edgecolor(snapshot["edgecolor"])
    else:
        frame.set_facecolor(snapshot["facecolor"])
        frame.set_edgecolor(snapshot["edgecolor"])
        frame.set_alpha(snapshot["alpha"])
    frame.set_linewidth(snapshot["linewidth"])
    legend.stale = True


def restore_legend_snapshots(figure):
    """Restore all snapshotted legends in ``figure`` back to their pristine pre-edit state."""
    for _, _, legend in _figure_legends(figure):
        snapshot = getattr(legend, "_tramastat_legend_snapshot", None)
        if snapshot is not None:
            _restore_legend(legend, snapshot)


def _disambiguate_label(label, key):
    if key.startswith("group:"):
        kind = key.split(":", 2)[1]
        return f"{label} ({kind})"
    if ":" in key:
        prefix = key.split(":", 2)[:2]
        return f"{label} ({':'.join(prefix)})"
    return f"{label} ({key})"


def collect_legend_entries(figure):
    """Return all legend entries in ``figure`` in stable original order with disambiguated captions."""
    collected = []
    raw_items = []
    for scope, axes, legend in _figure_legends(figure):
        snapshot = _snapshot_legend(figure, scope, axes, legend)
        for entry in snapshot["entries"]:
            raw_items.append((scope, entry["key"], entry["label"], legend))
    labels = [item[2] for item in raw_items]
    scopes = list(dict.fromkeys(item[0] for item in raw_items))
    for scope, key, label, legend in raw_items:
        display = _disambiguate_label(label, key) if labels.count(label) > 1 else label
        if labels.count(label) > 1 and len({item[0] for item in raw_items if item[2] == label}) > 1:
            from .i18n import tr

            if scope.startswith("qq:"):
                panel = tr("legend_editor.panel." + scope.split(":", 1)[1])
            else:
                panel = tr("legend_editor.legend", number=scopes.index(scope) + 1)
            display = f"{label} ({panel})"
        collected.append(LegendEntry(scope=scope, key=key, label=label, display_name=display, legend=legend))
    return collected


def apply_legend_options(figure, options):
    """Validate and idempotently apply ``options`` to all legends on ``figure`` without inventing legends."""
    if figure is None or not hasattr(figure, "axes"):
        raise ValueError("Invalid figure for legend formatting.")
    canonical = validate_legend_options(options)
    legends = _figure_legends(figure)
    if canonical and is_non_native_figure(figure) and not legends:
        raise ValueError("Legend formatting is not supported on raster or archived preview figures without native artists.")
    if not legends:
        return

    for scope, axes, legend in legends:
        snapshot = _snapshot_legend(figure, scope, axes, legend)
        # Always start from the captured pristine snapshot so repeated calls stay idempotent.
        _restore_legend(legend, snapshot)
        if not canonical:
            continue

        if "title" in canonical:
            legend.set_title(canonical["title"])
            legend.get_title().set_parse_math(False)

        labels_map = canonical.get("labels", {})
        ordered_entries = list(snapshot["entries"])
        for entry in ordered_entries:
            if entry["key"] in labels_map:
                entry["textbox"].set_text(labels_map[entry["key"]])
                entry["textbox"]._text.set_parse_math(False)
        if canonical.get("reverse", False):
            ordered_entries.reverse()

        ncols = canonical.get("columns", snapshot["ncols"])
        if "reverse" in canonical or "columns" in canonical or labels_map:
            _repack_legend(legend, ordered_entries, ncols)

        if "frame" in canonical:
            legend.set_frame_on(canonical["frame"])

        frame = legend.get_frame()
        facecolor = canonical.get("facecolor", snapshot["facecolor"])
        edgecolor = canonical.get("edgecolor", snapshot["edgecolor"])
        alpha = canonical.get("alpha", snapshot["alpha"])
        if alpha is None:
            frame.set_alpha(None)
            frame.set_facecolor(facecolor)
            frame.set_edgecolor(edgecolor)
        else:
            frame.set_facecolor(facecolor)
            frame.set_edgecolor(edgecolor)
            frame.set_alpha(alpha)
        if "width" in canonical:
            frame.set_linewidth(canonical["width"])
        legend.stale = True
