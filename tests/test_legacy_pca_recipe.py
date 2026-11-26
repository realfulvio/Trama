"""Compatibility checks for saved, recalculable PCA recipes in ZIP projects."""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from matplotlib import rcParams
from matplotlib.colors import to_hex
import numpy as np
import pandas as pd

from analisi.analysis_chain import evaluate_graph
from analisi.data import Dataset, load_project, load_tables, save_project, validate_analysis_links
from analisi.kmeans_options import SELECTION
from analisi import ellipse_workbench, exploration, pca_overlays, pca_parallel_archive, pca_retention
from analisi.pca_graphs import BIPLOT, COORDINATES, GRAPH, SAVED_VIEWPORT, VERTICAL
from analisi.legacy_recipes import restore_recipe
from analisi.legacy_pca_view import saved_parallel_reference
from analisi.legacy_pca_smoke import INPUT, SOURCE_NAME, sample, write_project
from analisi.workbench import analyse
from tests.test_legacy_recipes import source


METHOD = "Principal component analysis"
def fixture():
    frame, content = sample()
    return source("PCA", "0.0.0", content, frame, INPUT)


def add_score_graph(path, *, level=90., linked=True, fill=True, viewport=False, marker_shape="circleFill"):
    frame, _ = sample()
    frame.loc[2, "Signal (2)"] = 2.4
    with ZipFile(path) as reader:
        members = {name: reader.read(name) for name in reader.namelist()}
    doc = json.loads(members["document.json"])
    doc["sheets"]["graphs"] = ["scatter"]
    analysis = json.loads(members["analyses/pca/sheet.json"])
    analysis.update(uid="pca", resultSheets=[{"uid": "score-view", "title": "PC scores"}], graphs=[
        {"id": 7, "settings": {"uid": "scatter", "graph": {"dataSheet": "score"}}},
    ])

    def legend(colors, bounds=None):
        children = [{"title": {"text": {"string": label}}, "symbolFillColor": color}
                    for label, color in zip(("First", "Second"), colors, strict=True)]
        for entry, color in zip(children, bounds or ("", ""), strict=True):
            entry["symbolBorderColor"] = color
        return {"@class": "CategoricalSymbolsLegend", "children": children}

    markers = ("#0077cc80", "#ee992280")
    faces = ("#0077cc40", "#ee992240")
    edges = ("#0077ccff", "#ee9922ff")
    graph = {
        "uid": "scatter", "settingsSource": "pca" if linked else "other", "analysisSettingsID": 7,
        "graph": {"@class": "MVGraph", "dataSheet": "score", "xVariables": ["pc1"], "yVariables": ["pc2"],
                  "gdoTypesExt": {"defaults": ["symbols", "confidence ellipses"]},
                  "gdoSettings": {"symbols": {"@class": "BubblesFigure::Settings", "colorVariable": "groups",
                                              "sizeEvaluator": {"@class": "SymbolSizeEvaluator", "symbolSize": 3.0},
                                              "rowSymbolSettings": {"common": {"symbolShape": marker_shape,
                                                  "symbolBorderColor": "#12345680", "symbolBorderThickness": 1.25}},
                                              "colormap": {"colors": dict(enumerate(markers))}}},
                  "gdoSettingsExt": {"confidence ellipses": {
                      "@class": "ConfidenceEllipsesFigure::Settings", "groupingVariable": "groups",
                      "confidenceLevel": level, "isFillEnabled": fill,
                      "colormap": {"colors": dict(enumerate(faces))},
                      "borderColormap": {"colors": dict(enumerate(edges))},
                  }},
                  "legends": [legend(markers), legend(faces, edges)]},
    }
    if viewport:
        def fixed_axis(title, orientation, low, high, start, step, reversed_=False):
            return {"orientation": orientation, "title": {"isVisible": True, "text": {"string": title}},
                    "segments": [{"@class": "LinearAxisSegment", "isLowerLimitFixed": True,
                                  "isUpperLimitFixed": True, "isIntervalFixed": True,
                                  "lowerLimit": low, "upperLimit": high, "startTicksValue": start,
                                  "interval": step, "isReversed": reversed_, "customTicks": [
                                      {"@class": "CustomAxisTick", "value": 0.0, "tickType": "none", "labelText": "",
                                       "gridLine": {"isVisible": True, "orderOfDrawing": "under", "strokeStyle": "dot",
                                                    "strokeColor": "#12345680", "strokeThickness": 1.25}},
                                  ]}]}

        graph["graph"].update(
            title={"isVisible": True, "text": {"string": "Score $ overview"}},
            axisX=fixed_axis("PC1", "horizontal", -6., 6., -5., 5.),
            axisY=fixed_axis("PC2", "vertical", -4., 4., -4., 2., True),
        )
    records = {"document.json": doc, "analyses/pca/sheet.json": analysis,
               "analyses/pca/result_sheets/score-view.json": {"name": "PC scores", "dataSheet": "score",
                                                              "isVisible": True},
               "graphs/scatter/sheet.json": graph, "data/sheets/score/sheet.json": {"table": {
                   "uid": "scores", "format": "multivariable", "dataFormat": "y_single",
                   "dataSets": ["pc1", "pc2", "groups"],
               }},
               **{f"data/sets/{uid}.json": {"title": label} for uid, label in
                  (("pc1", "PC1"), ("pc2", "PC2"), ("groups", "Cohort"))}}
    members.update({key: json.dumps(value) for key, value in records.items()})
    members["data/tables/values/data.csv"] = frame.to_csv(index=False, header=False)
    members["data/tables/scores/data.csv"] = frame[["Signal", "Baseline", "Cohort"]].to_csv(
        index=False, header=False)
    with ZipFile(path, "w") as writer:
        for key, value in members.items():
            writer.writestr(key, value)



def add_saved_loadings(path, loadings):
    """Attach the result sheet using the same metadata as saved multivariable projects."""
    with ZipFile(path) as reader:
        members = {name: reader.read(name) for name in reader.namelist()}
    analysis = json.loads(members["analyses/pca/sheet.json"])
    analysis.update(uid="pca")
    analysis["resultSheets"].append({"uid": "loadings-view", "title": "Loadings"})
    columns = {"loadings-variable": "Var"}
    columns.update({f"loadings-{name}": name for name in loadings.columns})
    records = {"analyses/pca/sheet.json": analysis,
               "analyses/pca/result_sheets/loadings-view.json": {"name": "Loadings", "dataSheet": "loadings",
                                                                 "isVisible": True},
               "data/sheets/loadings/sheet.json": {"table": {"uid": "loadings-values", "format": "multivariable",
                   "dataFormat": "y_single", "dataSets": list(columns)}},
               **{f"data/sets/{key}.json": {"title": value} for key, value in columns.items()}}
    members.update({key: json.dumps(value) for key, value in records.items()})
    members["data/tables/loadings-values/data.csv"] = loadings.to_csv(index=True, header=False)
    with ZipFile(path, "w") as writer:
        for key, value in members.items():
            writer.writestr(key, value)


class LegacyPCARecipeTests(unittest.TestCase):
    def test_saved_parallel_reference_follows_data_and_settings(self):
        frame, _ = sample()
        variables = list(frame.columns[:3])
        parts, _, _ = exploration.pca(frame, variables)
        options = {
            "Variables": variables, "Standardize": True, "Graph display": "Scree",
            pca_retention.SELECTION: pca_retention.PARALLEL, pca_retention.PERCENTILE: 95,
            pca_retention.SIMULATIONS: 120, pca_retention.SEED: 2718,
        }
        name = "Eigenvalue (from Parallel Analysis)"
        observed = parts["Eigenvalue"].to_numpy()
        summary = pd.DataFrame({
            "Row title": list(parts.index), "Eigenvalue (from data) [Center]": observed,
            f"{name} [Center]": [1.50, 1.01, .49], f"{name} [Lower]": [.31, .12, .09],
            f"{name} [Upper]": [.45, .19, .23],
        })
        analysis = {"uid": "pca", "resultSheets": [{"title": "Eigenvalues", "uid": "parallel"}]}
        with ZipFile(BytesIO(), "w") as archive:
            archive.writestr("analyses/pca/result_sheets/parallel.json",
                             json.dumps({"name": "Eigenvalues", "dataSheet": "reference"}))
            options[pca_parallel_archive.ARCHIVE] = saved_parallel_reference(
                archive, analysis, frame, {"reference": summary}, options)
        restored = analyse(METHOD, frame, options)
        selection = restored.tables[pca_retention.SELECTION_SHEET]
        np.testing.assert_array_equal(selection["Random mean"], summary[f"{name} [Center]"])
        np.testing.assert_array_equal(selection["Random lower percentile"],
                                      summary[f"{name} [Center]"] - summary[f"{name} [Lower]"])
        np.testing.assert_array_equal(selection["Random percentile"],
                                      summary[f"{name} [Center]"] + summary[f"{name} [Upper]"])
        axes, = restored.figure.axes
        self.assertIn("trama-pca-parallel-interval", {artist.get_gid() for artist in axes.collections})
        mean, = [artist for artist in axes.collections if artist.get_gid() == "trama-pca-parallel-mean"]
        np.testing.assert_array_equal(mean.get_offsets()[:, 1], selection["Random mean"])

        updated = frame.copy()
        updated.loc[0, variables[0]] += .2
        for data, overrides in ((updated, {}), (frame, {pca_retention.SEED: 10}),
                                (frame, {pca_retention.PERCENTILE: 85}), (frame, {pca_retention.SAVE: True})):
            with self.subTest(overrides=overrides):
                result = analyse(METHOD, data, {**options, **overrides})
                settings = result.tables[pca_retention.SETTINGS_SHEET]
                self.assertIn("PCG64", settings.at[0, "Rule"])
                self.assertEqual(pca_retention.PARALLEL_SHEET in result.tables, bool(overrides.get(pca_retention.SAVE)))

    def test_archived_loadings_preserve_the_direction_of_recalculated_components(self):
        frame, _ = sample()
        variables = frame.columns[:3].tolist()
        parts, axes, scores = exploration.pca(frame, variables)
        directions = axes.mul(np.sqrt(parts["Eigenvalue"]), axis="columns")
        directions.loc[:, "PC1"] *= -1
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.prismt"
            write_project(source)
            add_saved_loadings(source, directions.iloc[::-1])
            tables = {title: Dataset(data) for title, data in load_tables(source, restore_legacy=True).items()}
            saved = Path(directory) / "reopened.alab"
            save_project(saved, tables)
            reopened = load_project(saved)[SOURCE_NAME]
            method, options = reopened.analyses[0]
            result = analyse(method, reopened.frame(), options)
            pd.testing.assert_frame_equal(result.tables["Explained variance"], parts)
            np.testing.assert_allclose(result.tables["Scores"]["PC1"], -scores["PC1"], rtol=1e-12)
            np.testing.assert_allclose(result.tables["Eigenvectors"]["PC1"], -axes["PC1"], rtol=1e-12)
            np.testing.assert_allclose(result.tables[COORDINATES]["Horizontal"], -scores["PC1"], rtol=1e-12)
            np.testing.assert_allclose(result.tables["Scores"]["PC2"], scores["PC2"], rtol=1e-12)

            raw = analyse(method, reopened.frame(), {**options, "Standardize": False})
            _, _, raw_scores = exploration.pca(frame, variables, standardize=False)
            pd.testing.assert_frame_equal(raw.tables["Scores"], raw_scores)

            from trama_qt.project import Project

            project = Project()
            project.load(saved)
            run = project.runs[0]
            # A dialog sends only the visible analysis settings when changing a component axis.
            from analisi.pca_graphs import SAVED_DIRECTIONS, HORIZONTAL

            visible = {key: value for key, value in run.options.items() if key != SAVED_DIRECTIONS}
            candidate = project.candidate(run.title, method, {**visible, HORIZONTAL: 3}, index=0)
            self.assertEqual(candidate.options[SAVED_DIRECTIONS], run.options[SAVED_DIRECTIONS])
    def test_score_graph_recovers_level_and_palette_on_the_recalculable_recipe(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "overlay.prismt"
            write_project(archive)
            add_score_graph(archive)
            data = {title: Dataset(frame) for title, frame in load_tables(archive, restore_legacy=True).items()}
            native = Path(directory) / "roundtrip.alab"
            save_project(native, data)
            reopened = load_project(native)[SOURCE_NAME]
            method, options = reopened.analyses[0]
            self.assertEqual(options[pca_overlays.LEVEL], 90.)
            self.assertEqual(options[pca_overlays.GROUPING], pca_overlays.BY_POINTS)
            result = analyse(method, reopened.frame(), options)
            contours = result.tables[pca_overlays.SHEET]
            self.assertEqual(contours["Group"].tolist(), ["First", "Second"])
            self.assertEqual(contours["Status"].tolist(), ["Drawn", "Drawn"])
            axes = result.figure.axes[0]
            self.assertEqual([to_hex(item.get_facecolors()[0], keep_alpha=True) for item in axes.collections],
                             ["#0077cc80", "#ee992280"])
            for item in axes.collections:
                np.testing.assert_array_equal(item.get_sizes(), [9.0])
                self.assertEqual(item.get_linewidths()[0], 1.25)
                self.assertEqual(to_hex(item.get_edgecolors()[0], keep_alpha=True), "#12345680")
            self.assertEqual([to_hex(item.get_facecolor(), keep_alpha=True) for item in axes.patches
                              if item.get_facecolor()[3]], ["#0077cc40", "#ee992240"])
            appearance = options[pca_overlays.SAVED_APPEARANCE]
            bad = {**options, pca_overlays.SAVED_APPEARANCE: {
                **appearance, "marker_style": {**appearance["marker_style"], "size": 0}}}
            for other in (bad, {**options, GRAPH: BIPLOT}):
                points = analyse(method, reopened.frame(), other).figure.axes[0].collections
                for item in points:
                    np.testing.assert_array_equal(item.get_sizes(), [rcParams["lines.markersize"] ** 2])

    def test_unknown_marker_keeps_the_ellipse_and_default_marker_size(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "overlay.prismt"
            write_project(path)
            add_score_graph(path, marker_shape="unknown")
            data = Dataset(load_tables(path, restore_legacy=True)[SOURCE_NAME])
            method, options = data.analyses[0]
            self.assertNotIn("marker_style", options[pca_overlays.SAVED_APPEARANCE])
            result = analyse(method, data.frame(), options)
            self.assertEqual(result.tables[pca_overlays.SHEET]["Status"].tolist(), ["Drawn", "Drawn"])
            for item in result.figure.axes[0].collections:
                np.testing.assert_array_equal(item.get_sizes(), [rcParams["lines.markersize"] ** 2])

    def test_imported_score_ellipses_show_the_dispersion_of_each_group(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "overlay.prismt"
            write_project(archive)
            add_score_graph(archive, level=90.)
            dataset = Dataset(load_tables(archive, restore_legacy=True)[SOURCE_NAME])
            method, options = dataset.analyses[0]
            self.assertEqual(options[pca_overlays.KIND], ellipse_workbench.DATA_ELLIPSE)
            result = analyse(method, dataset.frame(), options)
            coords = result.tables[COORDINATES]
            lines = [line for line in result.figure.axes[0].lines if len(line.get_xdata()) == 181]
            groups = result.tables[pca_overlays.SHEET]["Group"]
            for group, line in zip(groups, lines, strict=True):
                values = coords.loc[coords["Color group"] == group, ["Horizontal", "Vertical"]].to_numpy()
                centered = np.column_stack((line.get_xdata(), line.get_ydata())) - values.mean(axis=0)
                distances = np.einsum("ij,jk,ik->i", centered, np.linalg.inv(np.cov(values, rowvar=False)), centered)
                np.testing.assert_allclose(distances, -2 * np.log(.1), rtol=1e-8, atol=0)

    def test_imported_score_viewport_is_saved_for_the_original_components(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "viewport.prismt"
            write_project(archive)
            add_score_graph(archive, viewport=True)
            native = Path(directory) / "viewport.alab"
            tables = {name: Dataset(frame) for name, frame in load_tables(archive, restore_legacy=True).items()}
            save_project(native, tables)
            loaded = load_project(native)[SOURCE_NAME]
            method, options = loaded.analyses[0]
            self.assertEqual(options[SAVED_VIEWPORT]["components"], [1, 2])
            axes = analyse(method, loaded.frame(), options).figure.axes[0]
            self.assertEqual(axes.get_xlim(), (-6., 6.))
            self.assertEqual(axes.get_ylim(), (4., -4.))
            self.assertEqual(axes.get_xticks().tolist(), [-5., 0., 5.])
            self.assertEqual(axes.get_yticks().tolist(), [-4., -2., 0., 2., 4.])
            self.assertEqual((axes.get_xlabel(), axes.get_ylabel()), ("PC1", "PC2"))
            self.assertEqual(axes.get_title(), "Score $ overview")
            self.assertFalse(axes.title.get_parse_math())
            for line in axes.lines[:2]:
                self.assertEqual(line.get_linestyle(), ":")
                self.assertEqual(line.get_linewidth(), 1.25)
                self.assertEqual(to_hex(line.get_color(), keep_alpha=True), "#12345680")
            for changed in ({VERTICAL: 3}, {GRAPH: BIPLOT},
                            {SAVED_VIEWPORT: {**options[SAVED_VIEWPORT], "x": {"step": 0}}}):
                with self.subTest(changed=changed):
                    axes = analyse(method, loaded.frame(), {**options, **changed}).figure.axes[0]
                    self.assertNotEqual(axes.get_xlim(), (-6., 6.))
                    self.assertNotEqual(axes.get_title(), "Score $ overview")

    def test_unmatched_or_invalid_graph_leaves_the_pca_recipe_available(self):
        for settings in ({"linked": False}, {"level": True}, {"level": 100}):
            with self.subTest(settings=settings), TemporaryDirectory() as directory:
                archive = Path(directory) / "overlay.prismt"
                write_project(archive)
                add_score_graph(archive, **settings)
                dataset = Dataset(load_tables(archive, restore_legacy=True)[SOURCE_NAME])
                method, options = dataset.analyses[0]
                self.assertEqual(method, METHOD)
                self.assertNotIn(pca_overlays.KIND, options)

    def test_score_graph_can_restore_the_border_without_the_fill(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "outline.prismt"
            write_project(archive)
            add_score_graph(archive, fill=False)
            dataset = Dataset(load_tables(archive, restore_legacy=True)[SOURCE_NAME])
            method, options = dataset.analyses[0]
            axes = analyse(method, dataset.frame(), options).figure.axes[0]
            self.assertFalse(axes.patches)
            self.assertEqual([to_hex(line.get_color()) for line in axes.lines if len(line.get_xdata()) > 2],
                             ["#0077cc", "#ee9922"])

    def test_clustered_data_input_uses_the_live_assignment_table_and_survives_roundtrip(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "chain.prismt"
            write_project(archive, clustered=True)
            data = {title: Dataset(frame) for title, frame in load_tables(archive, restore_legacy=True).items()}
            raw = data["Raw"]
            self.assertEqual([method for method, _ in raw.analyses], [SELECTION, METHOD])
            parent, child = (raw.analysis_ids[slot] for slot in range(2))
            self.assertEqual(raw.analysis_sources[1].analysis_id, parent)
            self.assertEqual(raw.analysis_sources[1].table, "Assignments by k")
            self.assertEqual(raw.analyses[1][1]["Color groups by"], "Cluster (k=2)")
            snapshot = data["Imported result · Saved assignments · Clustered data"]
            self.assertFalse(snapshot.analyses)
            self.assertIn("2 clusters", snapshot.frame())
            out = Path(directory) / "roundtrip.alab"
            save_project(out, data)
            reopened = load_project(out)
            self.assertEqual(reopened["Raw"].analysis_sources, raw.analysis_sources)
            graph = validate_analysis_links(reopened)
            self.assertEqual(graph.affected([parent]), [parent, child])

            def compute():
                source = reopened["Raw"]
                recipes = dict(zip((parent, child), source.analyses, strict=True))
                values = evaluate_graph(graph, graph.order, {parent: source.frame()}, {},
                                        lambda identifier, frame: analyse(recipes[identifier][0], frame, recipes[identifier][1]))
                self.assertIsNone(values[child].error)
                return values[child].result.tables["Explained variance"].iloc[0]["Eigenvalue"]

            first = compute()
            reopened["Raw"].raw.iat[0, 0] = 20.0
            self.assertNotEqual(compute(), first)

    def test_clustered_view_with_different_row_order_stays_a_pca_snapshot(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "reordered.prismt"
            write_project(archive, clustered=True, reorder_rows=True)
            data = {title: Dataset(frame) for title, frame in load_tables(archive, restore_legacy=True).items()}
            self.assertEqual([method for method, _ in data["Raw"].analyses], [SELECTION])
            snapshot = data["Imported result · Saved assignments · Clustered data"]
            self.assertEqual(snapshot.analyses[0][0], METHOD)
            self.assertFalse(snapshot.analysis_sources)

    def test_primary_input_resolves_columns_by_identity_and_keeps_options(self):
        recipe = restore_recipe(*fixture())
        self.assertIsNotNone(recipe)
        uid, method, options = recipe
        self.assertEqual((uid, method), ("source", METHOD))
        self.assertEqual(options["Variables"], ["Signal", "Signal (2)", "Baseline"])
        self.assertEqual(options["Color groups by"], "Cohort")
        self.assertEqual(options["Graph display"], "Scores")
        self.assertEqual(options["Selection"], "Parallel analysis")
        self.assertEqual(options["Parallel seed"], 2718)
        self.assertEqual(options["Parallel simulations"], 120)
        self.assertEqual(options["Parallel percentile (%)"], 95.0)
        self.assertTrue(options["Report transformed data"])
        self.assertTrue(options["Variable contributions"])
        self.assertTrue(options["Report variable matrix"])
        self.assertFalse(options["Observation contributions"])

    def test_saved_result_input_roundtrips_and_recalculates_after_edit(self):
        name = SOURCE_NAME
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pca.prism"
            write_project(path)
            data = {title: Dataset(frame) for title, frame in load_tables(path, restore_legacy=True).items()}
            self.assertFalse(data["Raw"].analyses)
            self.assertEqual(data[name].analyses[0][0], METHOD)
            self.assertEqual(data[name].table_format, "Imported result snapshot")
            out = Path(directory) / "roundtrip.alab"
            save_project(out, data)
            restored = load_project(out)[name]
            self.assertEqual(restored.analyses, data[name].analyses)
            method, options = restored.analyses[0]
            before = analyse(method, restored.frame(mask_excluded=True), options)
            self.assertEqual(len(before.tables["PC graph coordinates"]), 8)
            self.assertEqual(set(before.tables["PC graph coordinates"]["Color group"]), {"First", "Second"})
            self.assertEqual(before.tables["PCA selection settings"].iloc[0]["Seed"], 2718)
            restored.raw.iloc[0, 0] = 3.0
            after = analyse(method, restored.frame(mask_excluded=True), options)
            self.assertNotEqual(before.tables["Explained variance"].iloc[0]["Eigenvalue"],
                                after.tables["Explained variance"].iloc[0]["Eigenvalue"])

    def test_unsupported_settings_keep_the_archive_without_native_recipe(self):
        cases = (
            ("calc", "transform", "UNRECOGNIZED"),
            ("calc", "parallelAnalysis", {"percentileLevel": 95., "simulationCount": 120}),
            ("calc", "regression", {"run": True}),
            ("graph", "loadingPlot", True),
            ("report", "transformedData", "true"),
        )
        for section, field, value in cases:
            with self.subTest(section=section, field=field):
                sheet, parameters, sources = fixture()
                params = deepcopy(parameters)
                params["content"][section][field] = value
                self.assertIsNone(restore_recipe(sheet, params, sources))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cached-view.prism"
            write_project(path, cached_format="view")
            data = load_tables(path, restore_legacy=True)
            archived = data[SOURCE_NAME]
            self.assertNotIn("legacy_recipes", archived.attrs)
            self.assertEqual(len(archived), 8)
