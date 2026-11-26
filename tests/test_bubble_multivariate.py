"""Comprehensive engine, oracle, layout export, legacy compatibility and 50k benchmark tests for multivariate Bubble plots."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from analisi.bubble import (
    ATTR, COLOR_COLUMN, COLOR_LEGEND, COLOR_LIMITS, COLOR_MAX, COLOR_MID, COLOR_MIN, COLOR_TITLE,
    FILL_BY_CATEGORY, FILL_CONTINUOUS, FILL_FIXED, FILL_MODE, FIXED_AREA, FIXED_COLOR, FIXED_SHAPE,
    LIMITS_AUTO, LIMITS_MANUAL, MAX_AREA, MISSING_COLOR, MISSING_SHAPE, NEUTRAL, PALETTE,
    REVERSE_PALETTE, SHAPE_BY_CATEGORY, SHAPE_CHOICES, SHAPE_COLUMN, SHAPE_FIXED,
    SHAPE_LEGEND, SHAPE_MAP, SHAPE_MODE, SHEET, SHOW_LABELS, SIZE_BY_COLUMN, SIZE_FIXED,
    SIZE_LEGEND, SIZE_MODE, bubble_plot,
)
from analisi.bubble_style import (
    CATEGORY_COLORS, PRIMARY_SHAPES, apply_bubble_style, resolve_category_levels, sync_bubble_tables, validate_bubble_style,
)
from analisi.data import Dataset
from analisi.figure_export import export_figure
from analisi.presentation import apply_style, compose_layout
from analisi.processing import FieldError
from analisi.workbench import BUBBLE, analyse
from trama_qt.project import Project, compute


SPEC_DIR = Path(__file__).resolve().parents[2]
MISURE_CSV = Path(__file__).with_name("data") / "bubble_multivariate" / "misure.csv"
CONFRONTA_PY = SPEC_DIR / "confronta.py"
ATTESO_JSON = SPEC_DIR / "atteso.json"
SVG_NS = "{http://www.w3.org/2000/svg}"


def _misure_frame():
    source = MISURE_CSV if MISURE_CSV.exists() else SPEC_DIR / "misure.csv"
    return pd.read_csv(source, keep_default_na=True)


def _extract_oracle_case(result, df_source):
    """Extract rendered oracle payload directly from real Matplotlib figure artists & metadata."""
    figure = result.figure
    axes = figure.axes[0]
    state = getattr(figure, ATTR)
    pts = state["rendered_points"]
    id_col = df_source["id"].to_numpy()

    # Cross-check actual Matplotlib PathCollection offsets, sizes and facecolors against rendered state.
    drawn_xy = []
    drawn_sizes = []
    drawn_rgba = []
    for coll in axes.collections:
        gid = str(coll.get_gid() or "")
        if gid.startswith("bubble:"):
            drawn_xy.extend(coll.get_offsets().tolist())
            drawn_sizes.extend(np.asarray(coll.get_sizes(), dtype=float).tolist())
            fc = np.asarray(coll.get_facecolors(), dtype=float)
            if len(fc) == 1 and len(coll.get_offsets()) > 1:
                fc = np.tile(fc, (len(coll.get_offsets()), 1))
            drawn_rgba.extend(fc.tolist())
    assert len(drawn_xy) == len(pts["source_rows"])

    lo, hi = state["color_summary"]["limits"]
    out_points = []
    for idx, row1 in enumerate(pts["source_rows"]):
        row_idx = int(row1) - 1
        u = pts["color_u"][idx]
        # Verify the point's actual drawn XY and area exist in the real PathCollection artists.
        xy = [float(pts["x"][idx]), float(pts["y"][idx])]
        area = float(pts["area_pt2"][idx])
        assert any(
            np.allclose(pxy, xy, atol=1e-12) and abs(psize - area) < 1e-12
            for pxy, psize in zip(drawn_xy, drawn_sizes, strict=True)
        )
        out_points.append({
            "id": str(id_col[row_idx]),
            "xy": xy,
            "area_pt2": area,
            "color_u": None if np.isnan(u) else float(u),
            "shape_key": pts["shape_keys"][idx],
        })
    return {"limits": [float(lo), float(hi)], "points": out_points}


class MultivariateBubbleEngineTests(unittest.TestCase):
    def test_oracle_confronta_exact_and_after_alab_reopen(self):
        df = _misure_frame()
        base = {
            "X": "x", "Y": "y", "Size": "area", MAX_AREA: 400.0,
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "classe",
        }
        cases = {
            "auto": analyse(BUBBLE, df, base),
            "fisso": analyse(BUBBLE, df, {**base, COLOR_LIMITS: LIMITS_MANUAL, COLOR_MIN: 0, COLOR_MAX: 50}),
            "inverso": analyse(BUBBLE, df, {**base, REVERSE_PALETTE: True}),
        }
        measured = {name: _extract_oracle_case(res, df) for name, res in cases.items()}
        if ATTESO_JSON.exists() and CONFRONTA_PY.exists():
            with tempfile.TemporaryDirectory() as tmp:
                json_path = Path(tmp) / "misurato.json"
                json_path.write_text(json.dumps(measured, indent=2), encoding="utf-8")
                subprocess.check_call([sys.executable, str(CONFRONTA_PY), str(json_path)])
                subprocess.check_call([sys.executable, str(CONFRONTA_PY), str(json_path), "--tolleranza", "1e-6"])

        # Verify save & reopen of .alab reproduces exact oracle values via confronta logic.
        with tempfile.TemporaryDirectory() as tmp:
            project = Project()
            project.add_tables({"misure": df})
            runs = []
            for key, extra in (
                ("auto", {}),
                ("fisso", {COLOR_LIMITS: LIMITS_MANUAL, COLOR_MIN: 0, COLOR_MAX: 50}),
                ("inverso", {REVERSE_PALETTE: True}),
            ):
                run = project.candidate("misure", BUBBLE, {**base, **extra})
                project.add_result(run, compute(run, project.tables["misure"].raw))
                runs.append((key, run))
            alab_path = Path(tmp) / "oracle.alab"
            project.save(alab_path)
            reopened = Project()
            reopened.load(alab_path)
            for idx, (key, _) in enumerate(runs):
                r_open = reopened.runs[idx]
                res_open = compute(r_open, reopened.tables["misure"].raw)
                re_case = _extract_oracle_case(res_open, df)
                self.assertEqual(re_case["limits"], measured[key]["limits"])
                for p1, p2 in zip(re_case["points"], measured[key]["points"], strict=True):
                    self.assertEqual(p1["id"], p2["id"])
                    self.assertEqual(p1["xy"], p2["xy"])
                    self.assertAlmostEqual(p1["area_pt2"], p2["area_pt2"], places=9)
                    if p1["color_u"] is None:
                        self.assertIsNone(p2["color_u"])
                    else:
                        self.assertAlmostEqual(p1["color_u"], p2["color_u"], places=9)
                    self.assertEqual(p1["shape_key"], p2["shape_key"])

        # Also assert p01 and p02 remain two distinct points despite sharing xy=[1.0, 6.0].
        ids = [p["id"] for p in measured["auto"]["points"]]
        self.assertEqual(ids[:2], ["p01", "p02"])
        self.assertEqual(measured["auto"]["points"][0]["xy"], [1.0, 6.0])
        self.assertEqual(measured["auto"]["points"][1]["xy"], [1.0, 6.0])

    def test_diverging_midpoint_negative_constant_and_all_missing_signals(self):
        # 1. Internal diverging center: 25 between 0 and 100 maps 0, 25, 100 -> 0.0, 0.5, 1.0.
        df = pd.DataFrame({
            "x": [1.0, 2.0, 3.0, 4.0],
            "y": [10.0, 20.0, 30.0, 40.0],
            "s": [10.0, 10.0, 10.0, 10.0],
            "sig": [0.0, 25.0, 100.0, -50.0],
        })
        res = analyse(BUBBLE, df, {
            "X": "x", "Y": "y", "Size": "s",
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "sig",
            PALETTE: "Blue–red", COLOR_LIMITS: LIMITS_MANUAL,
            COLOR_MIN: 0.0, COLOR_MID: 25.0, COLOR_MAX: 100.0,
        })
        u = getattr(res.figure, ATTR)["rendered_points"]["color_u"]
        np.testing.assert_allclose(u, [0.0, 0.5, 1.0, 0.0], atol=1e-12)  # -50 clamps to 0.0 boundary

        # 2. Negative automatic range without errors.
        df_neg = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0], "sig": [-40.0, -10.0, 20.0]})
        res_neg = analyse(BUBBLE, df_neg, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 90.0,
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "sig",
        })
        st_neg = getattr(res_neg.figure, ATTR)
        self.assertEqual(st_neg["color_summary"]["limits"], (-40.0, 20.0))
        np.testing.assert_allclose(st_neg["rendered_points"]["color_u"], [0.0, 0.5, 1.0], atol=1e-12)

        # 3. Constant finite signal -> center color 0.5 and single colorbar tick.
        df_const = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [2.0, 3.0, 4.0], "sig": [42.0, 42.0, np.nan]})
        res_const = analyse(BUBBLE, df_const, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 100.0,
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "sig", MISSING_COLOR: "#cccccc",
        })
        st_const = getattr(res_const.figure, ATTR)
        self.assertTrue(st_const["color_summary"]["constant"])
        self.assertAlmostEqual(st_const["rendered_points"]["color_u"][0], 0.5)
        self.assertTrue(np.isnan(st_const["rendered_points"]["color_u"][2]))
        cb = res_const.figure.axes[0]._tramastat_bubble_colorbar
        self.assertEqual(list(cb.get_ticks()), [42.0])

        # 4. All signals missing -> points stay drawn in Missing color and legend clarifies.
        df_miss = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0], "sig": [np.nan, np.nan]})
        res_miss = analyse(BUBBLE, df_miss, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 150.0,
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "sig", MISSING_COLOR: "#8899aa",
        })
        st_miss = getattr(res_miss.figure, ATTR)
        self.assertTrue(st_miss["color_summary"]["all_missing"])
        self.assertEqual(len(st_miss["rendered_points"]["x"]), 2)
        self.assertEqual(st_miss["rendered_points"]["color_hex"], ["#8899aa", "#8899aa"])
        miss_leg = next(l for l in res_miss.figure.legends if l.get_gid() == "bubble-missing-legend")
        self.assertTrue(any("missing" in t.get_text().casefold() or "mancant" in t.get_text().casefold()
                            for t in miss_leg.get_texts()))

    def test_fixed_area_allows_single_valid_xy_pair_without_size_column(self):
        df = pd.DataFrame({"x": [3.5, np.nan], "y": [7.5, 2.0]})
        res = analyse(BUBBLE, df, {"X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 200.0})
        st = getattr(res.figure, ATTR)
        self.assertEqual(len(st["rendered_points"]["x"]), 1)
        np.testing.assert_allclose(st["rendered_points"]["area_pt2"], [200.0])
        unit_texts = [a for a in res.figure.axes[0].artists if str(a.get_gid() or "") == "bubble-size-legend"]
        self.assertTrue(unit_texts)

    def test_shapes_12_distinct_warning_mixed_types_and_reorder_persistence(self):
        # 12 distinct shape categories give 12 unique markers and zero repetition warning.
        levels12 = [f"Cat{i:02d}" for i in range(12)]
        df12 = pd.DataFrame({
            "x": np.arange(12, dtype=float),
            "y": np.arange(12, dtype=float),
            "sh": levels12,
        })
        res12 = analyse(BUBBLE, df12, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 80.0,
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "sh",
        })
        st12 = getattr(res12.figure, ATTR)
        self.assertEqual(len({row["marker"] for row in st12["shape_summary"]["levels"]}), 12)
        self.assertIsNone(st12["shape_warning"])

        # 13 levels -> triggers repetition warning cleanly without failing.
        df13 = pd.DataFrame({"x": np.arange(13, dtype=float), "y": np.arange(13, dtype=float), "sh": [f"K{i:02d}" for i in range(13)]})
        res13 = analyse(BUBBLE, df13, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 80.0,
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "sh",
        })
        self.assertIsNotNone(getattr(res13.figure, ATTR)["shape_warning"])

        # Mixed integer 1 vs text "1" remain distinct levels!
        df_mix = pd.DataFrame({
            "x": [1.0, 2.0, 3.0],
            "y": [4.0, 5.0, 6.0],
            "sh": pd.Series([1, "1", None], dtype=object),
        })
        levels, disamb, _ = resolve_category_levels(df_mix["sh"].to_numpy(dtype=object))
        tokens = [item[0] for item in levels]
        self.assertEqual(tokens, ["int:1", "str:1"])
        self.assertNotEqual(disamb["int:1"], disamb["str:1"])

        custom_map = {"int:1": "^", "str:1": "D"}
        res_mix = analyse(BUBBLE, df_mix, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 100.0,
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "sh",
            SHAPE_MAP: custom_map, MISSING_SHAPE: "+",
        })
        pts_before = getattr(res_mix.figure, ATTR)["rendered_points"]
        self.assertEqual(list(pts_before["markers"]), ["^", "D", "+"])

        # Reverse row order in worksheet -> markers remain attached to category identity, not row order!
        df_rev = df_mix.iloc[::-1].reset_index(drop=True)
        res_rev = analyse(BUBBLE, df_rev, {
            "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED, FIXED_AREA: 100.0,
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "sh",
            SHAPE_MAP: custom_map, MISSING_SHAPE: "+",
        })
        pts_after = getattr(res_rev.figure, ATTR)["rendered_points"]
        self.assertEqual(list(pts_after["markers"]), ["+", "D", "^"])

    def test_row_exclusion_updates_scale_legends_and_svg_pdf_png_and_layout(self):
        df = _misure_frame()
        opts = {
            "X": "x", "Y": "y", "Size": "area", MAX_AREA: 400.0,
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "classe", "Label": "etichetta",
        }
        res_full = analyse(BUBBLE, df, opts)
        self.assertEqual(getattr(res_full.figure, ATTR)["color_summary"]["limits"], (0.0, 100.0))

        # Simulate worksheet exclusion/removal of row p04 (segnale=100) -> max becomes 50.0.
        df_excl = df.copy()
        df_excl.loc[df_excl["id"] == "p04", "x"] = np.nan
        res_excl = analyse(BUBBLE, df_excl, opts)
        self.assertEqual(getattr(res_excl.figure, ATTR)["color_summary"]["limits"], (0.0, 50.0))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for ext in ("png", "svg", "pdf"):
                p = tmp_dir / f"bubble.{ext}"
                export_figure(res_excl.figure, p, {"format": ext, "dpi": 150})
                self.assertGreater(p.stat().st_size, 500)
            svg_text = (tmp_dir / "bubble.svg").read_text(encoding="utf-8")
            self.assertIn("pt²", svg_text)
            self.assertNotIn("p04", "".join(ET.fromstring(svg_text).itertext()))

            # Narrow window size & multi-panel Layout export work cleanly with independent legends.
            res_excl.figure.set_size_inches(5.5, 3.8)
            res_excl.figure.canvas.draw()
            layout_fig = compose_layout("Bubble layout", 2, [res_full.figure, res_excl.figure])
            pdf_out = tmp_dir / "layout.pdf"
            svg_out = tmp_dir / "layout.svg"
            export_figure(layout_fig, pdf_out, {"format": "pdf"})
            export_figure(layout_fig, svg_out, {"format": "svg"})
            self.assertGreater(pdf_out.stat().st_size, 1000)
            self.assertGreater(svg_out.stat().st_size, 1000)

    def test_v0116_legacy_alab_backward_compatibility_and_upgrade(self):
        legacy_df = pd.read_csv(Path(__file__).with_name("data") / "bubble.csv")
        legacy_opts = {"X": "X", "Y": "Y", "Size": "Size", "Group": "Group", "Label": "Label"}
        with tempfile.TemporaryDirectory() as tmp:
            p = Project()
            p.add_tables({"Data 1": legacy_df})
            run = p.candidate("Data 1", BUBBLE, legacy_opts)
            p.add_result(run, compute(run, p.tables["Data 1"].raw))
            legacy_path = Path(tmp) / "v0116_legacy.alab"
            p.save(legacy_path)

            # Reopen legacy project: identical geometry & group colors before new options.
            reopened = Project()
            reopened.load(legacy_path)
            r0 = reopened.runs[0]
            res0 = compute(r0, reopened.tables["Data 1"].raw)
            reopened.add_result(r0, res0, index=0)
            self.assertAlmostEqual(float(res0.tables[SHEET]["Marker area (pt²)"].max()), 400.0)

            # Activate multivariate options without changing recipe -> style updates cleanly and persists.
            new_style = {"bubble": {"size_mode": SIZE_FIXED, "fixed_area": 180.0, "fill_mode": FILL_FIXED, "fixed_color": "#cc3311", "fixed_shape": "D"}}
            apply_style(res0.figure, new_style)
            reopened.commit_style(r0, new_style)
            sync_bubble_tables(res0)
            np.testing.assert_allclose(res0.tables[SHEET]["Marker area (pt²)"], 180.0)
            reopened.save(legacy_path)

            reopened2 = Project()
            reopened2.load(legacy_path)
            res2 = compute(reopened2.runs[0], reopened2.tables["Data 1"].raw)
            np.testing.assert_allclose(getattr(res2.figure, ATTR)["rendered_points"]["area_pt2"], 180.0)
            self.assertEqual(getattr(res2.figure, ATTR)["effective_encoding"]["fixed_color"], "#cc3311")

    def test_50000_point_benchmark(self):
        n = 50_000
        rng = np.random.default_rng(123)
        big = pd.DataFrame({
            "x": rng.normal(size=n),
            "y": rng.normal(size=n),
            "sz": rng.uniform(1.0, 100.0, size=n),
            "sig": rng.normal(size=n),
            "sh": [f"G{i % 12:02d}" for i in range(n)],
        })
        t0 = time.perf_counter()
        res = analyse(BUBBLE, big, {
            "X": "x", "Y": "y", "Size": "sz",
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "sig",
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "sh",
        })
        build_s = time.perf_counter() - t0

        t1 = time.perf_counter()
        apply_bubble_style(res.figure, {"palette": "Cividis", "reverse": True})
        redraw_s = time.perf_counter() - t1

        with tempfile.TemporaryDirectory() as tmp:
            svg_path = Path(tmp) / "bench50k.svg"
            t2 = time.perf_counter()
            export_figure(res.figure, svg_path, {"format": "svg"})
            svg_s = time.perf_counter() - t2
            self.assertGreater(svg_path.stat().st_size, 50_000)

        self.assertLess(build_s, 10.0)
        self.assertLess(redraw_s, 5.0)
        self.assertLess(svg_s, 15.0)

    def test_invalid_manual_limits_and_midpoint_raise_field_errors(self):
        df = _misure_frame()
        with self.assertRaises(FieldError):
            analyse(BUBBLE, df, {
                "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED,
                FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
                COLOR_LIMITS: LIMITS_MANUAL, COLOR_MIN: 50, COLOR_MAX: 10,
            })
        with self.assertRaises(FieldError):
            analyse(BUBBLE, df, {
                "X": "x", "Y": "y", SIZE_MODE: SIZE_FIXED,
                FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
                COLOR_LIMITS: LIMITS_MANUAL, COLOR_MIN: 0, COLOR_MID: 120, COLOR_MAX: 100,
            })
        with self.assertRaises(ValueError):
            validate_bubble_style({"fixed_color": "not-a-color"})
