"""A linked nonlinear graph uses fitted coordinates and leaves mismatched graphs archived."""
import json
from math import log10
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.presentation import apply_style
from analisi import regression_range as rr
from analisi.legacy_fit_graph import (FIT_GRAPH, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC, FIT_GRAPH_TICKS, FIT_INTERVAL_BAND,
                                    LOG_DOSE_MODEL)
from analisi.workbench import analyse
from tests.test_legacy_binary_graphs import _record
from tests.test_legacy_recipes import var
from trama_qt.project import Project


def saved_viewport(fen_id, *, pooled=False, concentration_ticks=None, x_axis=None):
    def group(tag, payload, children=b""):
        return _record(tag, payload) + children + pack("<H", tag - 0x4000)

    chart = bytearray()
    default_x = ((-8, 0), 0, 1) if pooled else ((-2, 2), 1, 1)
    x_config = (1, *(x_axis if x_axis is not None else default_x))
    for uid, bounds, logarithmic, step in (x_config, (2, (0, 120), 0, 30), (3, (0, 120), 0, 30)):
        low, high = bounds
        axis, ticks = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, low, high)
        pack_into("<4H", axis, 42, 1200, 0, logarithmic, 30 + uid)
        pack_into("<H", axis, 54, uid)
        length = 1100 if pooled else 1200
        pack_into("<H3d", ticks, 0, uid, low, high, (high - low) / length)
        pack_into("<H", ticks, 28, logarithmic)
        pack_into("<2d", ticks, 54, step, low)
        if uid == 1 and concentration_ticks is not None:
            pack_into("<H", ticks, 52, 9 if concentration_ticks else 0)
            pack_into("<4H", ticks, 78, 2, 2, 0, 2)
        chart.extend(_record(0x17, axis) + group(0x8025, ticks))
    objects = b"".join(group(0x8020, pack("<H", 8) + bytes(28), _record(0x2A, pack("<H", uid)))
                       for uid in (1, 2)) if pooled else b""
    chart.extend(group(0x8018, bytes(12), objects))
    return b"PCFFGRA4" + group(0x8001, bytes(12), group(0x8012, pack("<H", fen_id), chart))


def fixture(path, *, graph_id=4, shifted_grid=False, binary_graph=None, fit_bounds=None,
            curve_bounds=None, include_outside=True):
    observed_x = np.asarray([.1, .4, 1, 3, 10, 30])
    observed_y = 100 / (1 + observed_x / 3) + np.asarray([2, -1, 0, -.5, .2, 1.])
    if fit_bounds is None:
        included = np.ones(len(observed_x), dtype=bool)
    else:
        included = (observed_x >= fit_bounds[0]) & (observed_x <= fit_bounds[1])
    endpoints = curve_bounds if curve_bounds else (observed_x[included].min(), observed_x[included].max())
    grid = np.linspace(*endpoints, 12)
    if shifted_grid:
        grid[1] += .2
    content = {
        "variableDesign": {"x": var("x"), "responseList": [var("y", 1)], "factorList": []},
        "data": {"handleReplicatesAs": "INDIVIDUAL",
                 "range": {edge: {"enabled": False} for edge in ("minX", "maxX")}},
        "model": {
            "equation": {"definition": "Y=100 / (1+(IC50/X)^HillSlope)", "parameters": ["IC50", "HillSlope"]},
            "constraints": {"IC50": {"type": "GREATER", "value": 0.}},
            "initialValues": {"IC50": [{"isAuto": True, "value": 3.}],
                              "HillSlope": [{"isAuto": True, "value": -1.}]},
        },
        "method": {"fittingMethod": "LS", "outliers": {"method": "DO_NOT_HANDLE"},
                   "weighting": {"type": "NO_WEIGHTING"}},
        "interpolation": {"enabled": False}, "modelComparison": {"type": "NO_COMPARISON"},
        "graph": {"curve": {"minX": {"isAuto": True}, "maxX": {"isAuto": True}, "pointCount": len(grid)},
                  "curveBands": {"type": "NONE"}},
    }
    if fit_bounds is not None:
        for edge, bounds in zip(("minX", "maxX"), fit_bounds, strict=True):
            content["data"]["range"][edge] = {"enabled": True, "value": bounds}
    if curve_bounds is not None:
        for edge, bounds in zip(("minX", "maxX"), curve_bounds, strict=True):
            content["graph"]["curve"][edge] = {"isAuto": False, "value": bounds}
    with ZipFile(path, "w") as archive:
        def write(name, value):
            archive.writestr(name, json.dumps(value))

        write("document.json", {"sheets": {"data": ["source"], "analyses": ["fit"], "graphs": ["plot"]}})
        write("data/sheets/source/sheet.json", {"title": "Experiment", "table": {
            "uid": "input", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["x", "y"]}})
        method = "NONLINEAR_REGRESSION"
        write("analyses/fit/sheet.json", {"analysisClass": method, "title": "Archived fit",
              "inputSheets": [{"uid": "source"}], "isAllDataAnalyzed": True,
              "resultSheets": [{"uid": "curve-view"}, {"uid": "xy-view"}]})
        write("analyses/fit/parameters.json", {"analysisClass": method, "version": "0.0.0", "content": content})
        points = np.column_stack((observed_x, observed_y))
        curve = np.column_stack((grid, 100 / (1 + grid / 3)))
        xy = points if include_outside else points[included]
        for prefix, name, table in (("xy", "XY data", xy), ("curve", "Curve", curve)):
            write(f"analyses/fit/result_sheets/{prefix}-view.json", {
                "name": name, "dataSheet": prefix, "graphId": 4})
            write(f"data/sheets/{prefix}/sheet.json", {"table": {
                "uid": prefix, "format": "xy", "dataFormat": "y_single",
                "xDataSet": f"{prefix}-x", "dataSets": [f"{prefix}-y"]}})
            for axis, title in (("x", "Concentration"), ("y", "Signal")):
                write(f"data/sets/{prefix}-{axis}.json", {"title": title})
            archive.writestr(f"data/tables/{prefix}/data.csv", "".join(f"{x},{y}\n" for x, y in table))
        write("data/sets/x.json", {"title": "Concentration"})
        write("data/sets/y.json", {"title": "Signal"})
        archive.writestr("data/tables/input/data.csv", "".join(f"{x},{y}\n" for x, y in points))
        write("graphs/plot/sheet.json", {"uid": "plot", "fenID": graph_id,
              "title": "Original plot", "inputDataSets": ["xy-y", "curve-y"]})
        if binary_graph is not None:
            archive.writestr("graphs/plot/data.bin", binary_graph)


def refresh(project, runs):
    job = project.plan_refresh(runs)
    return project.apply_refresh(job, project.run_refresh(job))


def chained_fixture(path, *, changed_transform=False, concentration_ticks=None):
    log_x = np.arange(-8., 1.)
    y = 10 + 90 / (1 + 10 ** (-4 - log_x))
    replicates = np.column_stack((y + 1, y - 1, y * 1.2 + 2, y * 1.2 - 2))
    replicates[-1, :2] = np.nan
    transformed_x = log_x.copy()
    if changed_transform:
        transformed_x[3] += .2
    grid = np.linspace(log_x[0], log_x[-1], 17)
    series = ("treated", "control")
    methods = ("TRNSFORM", "NONLINEAR_REGRESSION")
    names = ("Bottom", "Top", "LogEC50", "HillSlope")
    transform = {
        "data": {"handleReplicatesAs": "INDIVIDUAL"},
        "calc": {"transformType": "STANDARD", "standardFunction": {
            "interchangeXY": False, "yTransform": {"enabled": False},
            "xTransform": {"enabled": True, "function": "LOG10(X)", "k": "undefined"}}},
    }
    fit = {
        "data": {"handleReplicatesAs": "INDIVIDUAL",
                 "range": {edge: {"enabled": False} for edge in ("minX", "maxX")}},
        "model": {"equation": {"definition": "Y=Bottom+(Top-Bottom)/(1+10^((LogEC50-X)*HillSlope))",
                               "parameters": list(names)}, "constraints": {},
                  "initialValues": {name: [{"dataSet": var(f"log-{item}"), "isAuto": True, "value": 1.}
                                           for item in series] for name in names}},
        "method": {"fittingMethod": "LS", "outliers": {"method": "DO_NOT_HANDLE"},
                   "weighting": {"type": "NO_WEIGHTING"}},
        "interpolation": {"enabled": False}, "modelComparison": {"type": "NO_COMPARISON"},
        "confidence": {"calcCI": True, "ciMethod": "PROFILE_LIKELIHOOD", "confidenceLevel": 95.},
        "graph": {"curve": {"minX": {"isAuto": True}, "maxX": {"isAuto": True}, "pointCount": len(grid)},
                  "curveBands": {"type": "NONE"}},
    }
    with ZipFile(path, "w") as archive:
        def write(name, value):
            archive.writestr(name, json.dumps(value))

        write("document.json", {"sheets": {"data": ["raw"], "analyses": ["fit", "transform"], "graphs": ["plot"]}})
        for key, x, values, count in (("raw", 10 ** log_x, replicates, 2), ("log", transformed_x, replicates, 2),
                                       ("curve", grid, np.column_stack((
                                           np.where(grid <= log_x[-2], grid ** 2, np.nan), grid ** 2)), 1)):
            write(f"data/sheets/{key}/sheet.json", {"title": "Experiment", "table": {
                "uid": key, "format": "xy" if key == "raw" else "view",
                "dataFormat": "y_replicates" if count == 2 else "y_single", "replicatesCount": count,
                "xDataSet": f"{key}-x", "dataSets": [f"{key}-{item}" for item in series]}})
            write(f"data/sets/{key}-x.json", {"title": "Dose"})
            write(f"data/sets/{key}-treated.json", {"title": "Treated " if count == 2 else "Treated"})
            write(f"data/sets/{key}-control.json", {"title": "Control"})
            archive.writestr(f"data/tables/{key}/data.csv", "".join(
                ",".join("" if np.isnan(v) else str(v) for v in row) + "\n" for row in np.column_stack((x, values))))

        for key, kind, source, result, title, content in (
                ("transform", methods[0], "raw", "log", "Transformed data", transform),
                ("fit", methods[1], "log", "curve", "Curve", fit)):
            write(f"analyses/{key}/sheet.json", {
                "analysisClass": kind, "title": key, "inputSheets": [{"uid": source}], "isAllDataAnalyzed": True,
                "inputDataSets": [{"uid": f"{source}-{item}"} for item in series], "resultSheets": [{"uid": "table"}]})
            write(f"analyses/{key}/parameters.json", {"analysisClass": kind, "version": "0.0.0", "content": content})
            write(f"analyses/{key}/result_sheets/table.json", {
                "dataSheet": result, "name": title, "graphId": 4 if result == "log" else -1, "isVisible": True})
        write("graphs/plot/sheet.json", {"uid": "plot", "fenID": 4, "title": "Dose response",
                                        "inputDataSets": [f"{key}-{item}" for key in ("log", "curve") for item in series]})
        archive.writestr("graphs/plot/data.bin", saved_viewport(4, pooled=True, concentration_ticks=concentration_ticks))


class ImportedFitFigureTests(unittest.TestCase):
    def test_log10_coordinates_keep_saved_concentration_ticks_after_reopening_and_zoom(self):
        for subdivisions in (False, True):
            with self.subTest(subdivisions=subdivisions), TemporaryDirectory() as folder:
                path = Path(folder) / "linked.pzt"
                chained_fixture(path, concentration_ticks=subdivisions)
                project = Project()
                project.load(path)
                saved = Path(folder) / "linked.alab"
                project.save(saved)
                project.load(saved)
                graph = project.runs[-1]
                self.assertIs(graph.options[FIT_GRAPH_TICKS], subdivisions)
                self.assertEqual(refresh(project, [graph]), [])
                figure = graph.result.figure
                axes, = figure.axes
                self.assertEqual(axes.get_xscale(), "linear")
                np.testing.assert_array_equal(axes.get_xticks(), np.arange(-8., 1.))
                self.assertEqual([tick.get_text() for tick in axes.get_xticklabels()],
                                 [f"$10^{{{value}}}$" for value in range(-8, 1)])
                expected = ([exponent + log10(factor) for exponent in range(-8, 0) for factor in range(2, 10)]
                            if subdivisions else [])
                np.testing.assert_allclose(axes.xaxis.get_minorticklocs(), expected)
                style = {**graph.style, "axis": {**graph.style["axis"], "x": {
                    **graph.style["axis"]["x"], "min": -7., "max": -5.}}}
                apply_style(figure, style)
                np.testing.assert_array_equal(axes.get_xticks(), [-7., -6., -5.])
                self.assertEqual([tick.get_text() for tick in axes.get_xticklabels()], ["$10^{-7}$", "$10^{-6}$", "$10^{-5}$"])
                np.testing.assert_allclose(axes.xaxis.get_minorticklocs(), [value for value in expected if -7 < value < -5])
                axes.set_xlim(-1000., 1000.)
                self.assertEqual(len(axes.xaxis.get_minorticklocs()), 0)

    def test_pooled_fit_runs_after_transform_and_drives_the_saved_graph(self):
        from analisi.replicate_fit import MERGE_REPLICATES
        from analisi import stats

        with TemporaryDirectory() as folder:
            path = Path(folder) / "linked.pzt"
            chained_fixture(path)
            project = Project()
            project.load(path)
            transform, fit, graph = project.runs
            self.assertNotIn(FIT_GRAPH_TICKS, graph.options)
            self.assertTrue(fit.options[MERGE_REPLICATES])
            self.assertEqual((fit.source.analysis_id, fit.source.table), (transform.uid, "Transformed data"))
            self.assertEqual((graph.source.analysis_id, graph.source.table), (fit.uid, FIT_GRAPH_POINTS))
            self.assertNotIn("Imported graph · Dose response", project.tables)
            with patch.object(stats, "nonlinear", wraps=stats.nonlinear) as count:
                self.assertEqual(refresh(project, [graph]), [])
                self.assertEqual(count.call_count, 1)
            points = graph.result.tables["Saved XY coordinates"]
            lines = points.query('Geometry == "line"')
            self.assertEqual(lines.groupby("Series").size().to_dict(), {"Control": 17, "Treated ": 15})
            original = fit.result.tables["Parameters: Treated "].copy()
            control = fit.result.tables["Parameters: Control"].copy()

            snapshot = Path(folder) / "linked.alab"
            project.save(snapshot)
            project.load(snapshot)
            transform, fit, graph = project.runs
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertEqual(refresh(project, [graph]), [])
            pd.testing.assert_frame_equal(graph.result.tables["Saved XY coordinates"], points)
            self.assertEqual(graph.result.figure.axes[0].get_xlim(), (-8., 0.))
            self.assertEqual(graph.result.figure.axes[0].get_ylim(), (0., 120.))
            self.assertEqual(refresh(project, project.paste(fit.title, 3, 1, [["29"]])), [])
            pd.testing.assert_frame_equal(fit.result.tables["Parameters: Control"], control)
            self.assertFalse(fit.result.tables["Parameters: Treated "].equals(original))
            self.assertFalse(graph.result.tables["Saved XY coordinates"].equals(points))

    def test_transformed_view_from_a_different_calculation_stays_archived(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "unmatched.pzt"
            chained_fixture(path, changed_transform=True)
            project = Project()
            project.load(path)
            self.assertIn("Imported graph · Dose response", project.tables)
            self.assertNotIn("Nonlinear regression", [run.method for run in project.runs])

    def test_imported_parameter_band_reads_the_current_confidence_limits(self):
        x = np.arange(-8., 0.)
        y = 10 + 90 / (1 + 10 ** (-4.2 - x)) + np.array([-.2, .5, 1, -.4, -.1, 0, .3, -.2])
        frame = pd.DataFrame({"X": x, "Y": y})
        options = {
            "X": "X", "Y columns": ["Y"], "Model": LOG_DOSE_MODEL, "Parameter confidence level (%)": 90.,
            FIT_INTERVAL_BAND: {"title": "Imported dose response", "color": "#d4d4d4",
                                "limits": [[-9., 0.], [0., 120.]]},
        }
        project = Project()
        project.add_tables({"Dose": frame})
        run = project.candidate("Dose", "Nonlinear regression", options)
        project.add_result(run, analyse(run.method, frame, run.options))
        revised = {key: value for key, value in options.items() if key != FIT_INTERVAL_BAND}
        candidate = project.candidate("Dose", run.method, revised, index=0)
        self.assertEqual(candidate.options[FIT_INTERVAL_BAND], options[FIT_INTERVAL_BAND])
        for offset in (0., 5.):
            edited = frame.copy()
            edited.loc[3, "Y"] += offset
            result = analyse(candidate.method, edited, candidate.options)
            parameters = next(table for title, table in result.tables.items() if title.startswith("Parameters:"))
            expected = parameters.loc["Log EC50", ["CI 90% low", "CI 90% high"]]
            axes, = result.figure.axes
            patch, = axes.patches
            self.assertEqual(patch.get_gid(), "linked-parameter-interval")
            np.testing.assert_allclose([patch.get_x(), patch.get_x() + patch.get_width()], expected, rtol=0, atol=1e-14)
            self.assertEqual(axes.get_xlim(), (-9., 0.))
            self.assertEqual(axes.get_ylim(), (0., 120.))
        combined = analyse(candidate.method, frame.assign(Z=y + 5), {**candidate.options, "Y columns": ["Y", "Z"]})
        self.assertFalse(any(artist.get_gid() == "linked-parameter-interval"
                             for axes in combined.figure.axes for artist in axes.patches))

    def test_graph_uses_one_fit_and_follows_changes_across_roundtrip(self):
        from analisi import stats

        with TemporaryDirectory() as folder:
            path = Path(folder) / "fit.prismt"
            fixture(path)
            project = Project()
            project.load(path)
            fit, graph = project.runs
            self.assertTrue(graph.options[FIT_GRAPH])
            self.assertEqual(graph.source.table, FIT_GRAPH_POINTS)
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertEqual(fit.options[FIT_GRAPH_SPEC]["samples"], 12)
            self.assertNotIn("Imported graph · Original plot", project.tables)
            with patch.object(stats, "nonlinear", wraps=stats.nonlinear) as count:
                self.assertEqual(refresh(project, [graph]), [])
                self.assertEqual(count.call_count, 1)
            original = graph.result.tables["Saved XY coordinates"]
            lines = original.query('Geometry == "line"')
            np.testing.assert_array_equal(lines["X"], np.linspace(.1, 30, 12))
            self.assertEqual(len(original), 18)
            self.assertEqual(graph.result.figure.axes[0].get_ylabel(), "Signal")
            options = {name: value for name, value in fit.options.items() if name != FIT_GRAPH_SPEC}
            edited = project.candidate(fit.title, fit.method, options, index=0)
            self.assertEqual(edited.options[FIT_GRAPH_SPEC], fit.options[FIT_GRAPH_SPEC])
            name = Path(folder) / "fit.alab"
            project.save(name)
            reopened = Project()
            reopened.load(name)
            fit, graph = reopened.runs
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertEqual(refresh(reopened, [graph]), [])
            np.testing.assert_array_equal(graph.result.tables["Saved XY coordinates"]["Y"], original["Y"])
            self.assertEqual(refresh(reopened, reopened.paste(fit.title, 5, 0, [["50"]])), [])
            after = graph.result.tables["Saved XY coordinates"].query('Geometry == "line"')
            np.testing.assert_array_equal(after["X"], np.linspace(.1, 50, 12))
            self.assertNotEqual(after["Y"].tolist(), lines["Y"].tolist())

    def test_unmatched_id_or_custom_grid_keeps_the_archived_graph(self):
        for settings in ({"graph_id": 5}, {"shifted_grid": True}):
            with self.subTest(settings=settings), TemporaryDirectory() as folder:
                path = Path(folder) / "fit.prismt"
                fixture(path, **settings)
                project = Project()
                project.load(path)
                fit, graph = project.runs
                self.assertNotIn(FIT_GRAPH_SPEC, fit.options)
                self.assertIsNone(graph.source)
                self.assertIn("Imported graph · Original plot", project.tables)

    def test_import_keeps_fit_and_drawing_ranges_independent_in_linked_graph(self):
        for include_outside in (False, True):
            with self.subTest(include_outside=include_outside), TemporaryDirectory() as folder:
                path = Path(folder) / "bounded.prismt"
                fixture(path, fit_bounds=(.4, 10.), curve_bounds=(.2, 20.), include_outside=include_outside)
                project = Project()
                project.load(path)
                fit, graph = project.runs
                self.assertEqual(graph.source.analysis_id, fit.uid)
                self.assertEqual([fit.options[key] for key in (*rr.FIT_FIELDS, *rr.CURVE_FIELDS)],
                                 [.4, 10., .2, 20., 12])
                self.assertEqual(fit.options.get(rr.SHOW_OUTSIDE, False), include_outside)
                self.assertEqual(refresh(project, [graph]), [])
                coords = graph.result.tables["Saved XY coordinates"]
                curve = coords.query('Geometry == "line"')
                np.testing.assert_array_equal(curve["X"], fit.result.figure.axes[0].lines[0].get_xdata())
                self.assertEqual((curve["X"].iloc[0], curve["X"].iloc[-1]), (.2, 20.))
                self.assertEqual(len(coords.query('Geometry == "points"')), 6 if include_outside else 4)
                fitted = fit.result.tables["Parameters: All"].copy()

                fit.options.update({rr.CURVE_MIN: .3, rr.CURVE_MAX: 25., rr.CURVE_POINTS: 7})
                saved = Path(folder) / "bounded.alab"
                project.save(saved)
                reopened = Project()
                reopened.load(saved)
                fit, graph = reopened.runs
                self.assertEqual(refresh(reopened, [graph]), [])
                points = graph.result.tables["Saved XY coordinates"]
                curve = points.query('Geometry == "line"')
                self.assertEqual(len(curve), 7)
                self.assertEqual((curve["X"].iloc[0], curve["X"].iloc[-1]), (.3, 25.))
                np.testing.assert_array_equal(curve["X"], fit.result.figure.axes[0].lines[0].get_xdata())
                self.assertEqual(refresh(reopened, reopened.paste(fit.title, 0, 1, [["5"]])), [])
                pd.testing.assert_frame_equal(fit.result.tables["Parameters: All"], fitted)
                if include_outside:
                    self.assertEqual(graph.result.tables["Saved XY coordinates"].query("X == 0.1")["Y"].tolist(), [5.])

    def test_graph_viewport_round_trips_and_remains_linked_to_the_fit(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "fit.prismt"
            fixture(path, binary_graph=saved_viewport(4))
            project = Project()
            project.load(path)
            fit, graph = project.runs
            self.assertEqual(refresh(project, [graph]), [])
            original = graph.result.tables["Saved XY coordinates"]
            snapshot = Path(folder) / "fit.alab"
            project.save(snapshot)
            project.load(snapshot)
            fit, graph = project.runs
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertEqual(refresh(project, project.paste(fit.title, 5, 0, [["50"]])), [])
            axes, = graph.result.figure.axes
            self.assertEqual(axes.get_xscale(), "log")
            self.assertEqual(axes.get_xlim(), (.01, 100.))
            self.assertEqual(axes.get_ylim(), (0., 120.))
            np.testing.assert_array_equal(axes.get_yticks(), [0., 30., 60., 90., 120.])
            self.assertFalse(graph.result.tables["Saved XY coordinates"].equals(original))

            fixture(path, binary_graph=saved_viewport(7))
            project = Project()
            project.load(path)
            fit, graph = project.runs
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertFalse(graph.style)
