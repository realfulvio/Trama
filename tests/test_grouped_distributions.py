"""Grouped box and violin plots: cells, positions, identities, legend and sheets."""
import io
import json
from pathlib import Path
import unittest

from matplotlib.colors import to_rgb
import numpy as np
import pandas as pd

from analisi.distribution_graphs import MAX_POINTS
from analisi import i18n
from analisi.grouped_distributions import (CELLS_SHEET, DENSITY_SHEET, GROUPED_DISTRIBUTIONS, MAX_CELLS,
                                           OBSERVATIONS_SHEET, cell_identity, parse_identity, visibility)
from analisi.graph_legend import collect_legend_entries, is_valid_entry_key, typed_group_token
from analisi.presentation import apply_style, graph_groups, validated_style
from analisi.processing import FieldError
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "grouped_distributions"
METHOD = GROUPED_DISTRIBUTIONS
SPLIT = {"Response": "Signal", "Category": "Visit", "Split by": "Treatment", "Style": "Box"}


def fixture():
    return pd.read_csv(DATA / "observations.csv"), json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def grouped(frame, **options):
    return analyse(METHOD, frame, {**SPLIT, **options})


def edge(group):
    return np.atleast_2d(group.artists[0][0].get_edgecolor())[0][:3].tolist()


def legend_colors(axes):
    return [tuple(round(float(v), 6) for v in handle.get_edgecolor()[:3]) for handle in axes.get_legend().legend_handles]


class Fixture(unittest.TestCase):
    def test_cells_and_source_rows_match_the_independent_values(self):
        frame, expected = fixture()
        result = grouped(frame)
        cells = result.tables[CELLS_SHEET]
        self.assertEqual(list(cells.columns[:10]), ["Category", "Series", "N", "Position", "Mean", "Median",
                                                    "Minimum", "Q1", "Q3", "Maximum"])
        self.assertEqual(cells["N"].tolist(), [5, 4, 4, 0])
        for row, want in zip(cells.to_dict("records"), expected["cells"], strict=True):
            for name, value in want.items():
                if value is None:
                    self.assertTrue(pd.isna(row[name]), (name, row))
                elif isinstance(value, str):
                    self.assertEqual(row[name], value)
                else:
                    self.assertAlmostEqual(float(row[name]), value, places=9, msg=name)
        sheet = result.tables[OBSERVATIONS_SHEET]
        self.assertEqual(sheet["Source row"].tolist(), [item["Source row"] for item in expected["observations"]])
        self.assertEqual(sheet["Source row"].tolist(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16])
        self.assertEqual(sheet["Value"].tolist(), [item["Value"] for item in expected["observations"]])
        self.assertTrue(np.allclose(sheet["Position"], [item["Position"] for item in expected["observations"]]))
        self.assertEqual(list(sheet.columns[:5]), ["Source row", "Category", "Series", "Value", "Position"])

    def test_the_empty_slot_exists_in_the_sheet_and_not_on_the_graph(self):
        frame, _ = fixture()
        for style in ("Box", "Violin"):
            result = grouped(frame, Style=style, **{"Overlay observations": True})
            axes = result.figure.axes[0]
            keys = [group.key for group in graph_groups(axes)]
            self.assertEqual(len(keys), 3)
            self.assertEqual([group.x for group in graph_groups(axes)], [.8, 1.2, 1.8])
            self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Drug", "Placebo"])
            # Nothing is drawn around the fourth slot (x = 2.2): the Baseline/Placebo cell is empty.
            for artist in [*axes.lines, *axes.patches, *axes.collections]:
                if hasattr(artist, "get_xydata") and len(artist.get_xydata()):
                    self.assertTrue((np.abs(np.asarray(artist.get_xydata())[:, 0] - 2.2) > .05).all(), artist)
            self.assertEqual(axes.get_xlim(), (.4, 2.6))

    def test_labels_titles_and_categories_stay_literal_text(self):
        frame, _ = fixture()
        frame = frame.rename(columns={"Treatment": "Arm $T$", "Signal": "Signal $s$"})
        result = analyse(METHOD, frame, {"Response": "Signal $s$", "Category": "Visit", "Split by": "Arm $T$",
                                         "Style": "Box"})
        axes = result.figure.axes[0]
        for artist in (axes.title, axes.xaxis.label, axes.yaxis.label, *axes.get_xticklabels(),
                       axes.get_legend().get_title(), *axes.get_legend().get_texts()):
            self.assertFalse(artist.get_parse_math(), artist.get_text())
        self.assertEqual([label.get_text() for label in axes.get_xticklabels()], ["Week $2$", "Baseline"])
        self.assertEqual(axes.get_legend().get_title().get_text(), "Arm $T$")
        self.assertEqual(axes._tramastat_categorical_axes, ("x",))
        self.assertEqual(axes._tramastat_numeric_axes, ("y",))

    def test_unsplit_roles_use_the_row_with_a_missing_split_value(self):
        frame, _ = fixture()
        result = grouped(frame, **{"Split by": ""})
        cells = result.tables[CELLS_SHEET]
        self.assertEqual(cells["N"].tolist(), [9, 5])
        self.assertEqual(cells["Position"].tolist(), [1, 2])
        self.assertEqual(cells["Series"].tolist(), ["", ""])
        self.assertIsNone(result.figure.axes[0].get_legend())
        colors = [edge(group) for group in graph_groups(result.figure.axes[0])]
        self.assertNotEqual(colors[0], colors[1])  # one color per category without a split

    def test_settings_report_omitted_rows_and_the_spatial_rule(self):
        frame, _ = fixture()
        settings = grouped(frame).tables["Settings"]
        text = settings.to_string()
        self.assertIn("Position = 1 + j + 0.8", text)
        omitted = [row for name, row in settings.iterrows() if "omitted" in str(name)]
        self.assertEqual(omitted[0].iloc[0], 3)
        unsplit = grouped(frame, **{"Split by": ""}).tables["Settings"]
        self.assertEqual([row.iloc[0] for name, row in unsplit.iterrows() if "omitted" in str(name)], [2])


class Geometry(unittest.TestCase):
    def test_positions_follow_the_slot_formula(self):
        for series in (1, 2, 3, 5):
            frame = pd.DataFrame({"y": np.arange(2. * series * 4),
                                  "c": ["a", "b"] * (series * 4),
                                  "s": np.repeat(list("pqrstu")[:series], 8)})
            options = {"Response": "y", "Category": "c", "Style": "Box"}
            if series > 1:
                options["Split by"] = "s"
            cells = analyse(METHOD, frame, options).tables[CELLS_SHEET]
            for row in cells.itertuples():
                j, i = (0 if row.Category == "a" else 1), (list("pqrstu").index(row.Series) if series > 1 else 0)
                self.assertAlmostEqual(row.Position, 1 + j + .8 * (i - (series - 1) / 2) / series)

    def test_width_is_shared_by_the_series_of_a_category(self):
        frame = pd.DataFrame({"y": np.arange(16.), "c": list("aa") * 8, "s": list("pq") * 8})
        result = analyse(METHOD, frame, {"Response": "y", "Category": "c", "Split by": "s", "Style": "Violin"})
        box = analyse(METHOD, frame, {"Response": "y", "Category": "c", "Split by": "s", "Style": "Box"})
        widths = [patch.get_path().get_extents().width for patch in box.figure.axes[0].patches]
        self.assertTrue(widths and all(abs(width - .28) < 1e-9 for width in widths), widths)
        density = result.tables[DENSITY_SHEET]
        self.assertTrue((density["Half-width"] <= .2 + 1e-12).all())
        self.assertEqual(density.groupby(["Category", "Series"]).ngroups, 2)
        self.assertEqual(list(density.columns[:3]), ["Category", "Series", "Position"])

    def test_single_group_matches_the_published_box_and_violin_plot(self):
        values = [1., 2., 3., 4., 5., 6., 7., 8., 30.]
        frame = pd.DataFrame({"y": values, "g": ["a"] * 9})
        for style in ("Box", "Violin"):
            old = analyse("Box / violin plot", frame, {"Input": "Single response", "Response": "y", "Group": "g",
                                                       "Style": style, "Overlay observations": True}).tables["Group summary"]
            new = analyse(METHOD, frame, {"Response": "y", "Category": "g", "Style": style,
                                          "Overlay observations": True}).tables[CELLS_SHEET]
            for old_name, new_name in (("N", "N"), ("Median", "Median"), ("Q1", "Q1"), ("Q3", "Q3"),
                                       ("Minimum", "Minimum"), ("Maximum", "Maximum"), ("Mean", "Mean")):
                self.assertEqual(old[old_name].iloc[0], new[new_name].iloc[0], (style, old_name))
            if style == "Box":
                self.assertEqual(old["Upper whisker"].iloc[0], new["Upper whisker"].iloc[0])
            else:
                self.assertEqual(old["Bandwidth"].iloc[0], new["Bandwidth"].iloc[0])

    def test_small_constant_and_coincident_cells(self):
        for style in ("Box", "Violin"):
            for n in (1, 2, 3):
                frame = pd.DataFrame({"y": [3., 3., 3.][:n] + [1., 2., 4.][:n], "c": ["x"] * n + ["y"] * n})
                result = analyse(METHOD, frame, {"Response": "y", "Category": "c", "Style": style,
                                                 "Overlay observations": True})
                cells = result.tables[CELLS_SHEET]
                self.assertEqual(cells["N"].tolist(), [n, n])
                self.assertTrue(cells["Q1"].isna().all() and cells["Q3"].isna().all())
                self.assertEqual(len(graph_groups(result.figure.axes[0])), 2)
        constant = pd.DataFrame({"y": [5.] * 8, "c": ["x"] * 4 + ["y"] * 4})
        for style in ("Box", "Violin"):
            result = analyse(METHOD, constant, {"Response": "y", "Category": "c", "Style": style})
            self.assertEqual(result.tables[CELLS_SHEET]["Median"].tolist(), [5., 5.])
        violin = analyse(METHOD, constant, {"Response": "y", "Category": "c", "Style": "Violin"})
        self.assertNotIn(DENSITY_SHEET, violin.tables)
        self.assertIn("constant values", violin.tables[CELLS_SHEET]["Note"].iloc[0])

    def test_one_category_one_series(self):
        frame = pd.DataFrame({"y": [1., 2., 3., 4., 5.], "c": ["only"] * 5, "s": ["one"] * 5})
        result = analyse(METHOD, frame, {"Response": "y", "Category": "c", "Split by": "s"})
        self.assertEqual(result.tables[CELLS_SHEET]["Position"].tolist(), [1.])
        self.assertEqual([t.get_text() for t in result.figure.axes[0].get_legend().get_texts()], ["one"])

    def test_cell_limit_is_checked_before_drawing(self):
        many = pd.DataFrame({"c": np.arange(MAX_CELLS + 1), "y": np.arange(MAX_CELLS + 1.)})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, many, {"Response": "y", "Category": "c"})
        self.assertEqual(raised.exception.field, "Category")
        product = pd.DataFrame({"c": np.tile(np.arange(5), 9), "s": np.repeat(np.arange(9), 5), "y": np.arange(45.)})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, product, {"Response": "y", "Category": "c", "Split by": "s"})
        self.assertEqual(raised.exception.field, "Split by")
        exact = pd.DataFrame({"c": np.tile(np.arange(5), 8), "s": np.repeat(np.arange(8), 5), "y": np.arange(40.)})
        self.assertEqual(len(analyse(METHOD, exact, {"Response": "y", "Category": "c", "Split by": "s"})
                             .tables[CELLS_SHEET]), 40)

    def test_observation_budget_keeps_the_existing_limit(self):
        frame = pd.DataFrame({"y": np.zeros(MAX_POINTS + 1), "c": "a"})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"Response": "y", "Category": "c"})
        self.assertEqual(raised.exception.field, "Response")


class Fields(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"y": [1., 2., 3., 4.], "c": list("aabb"), "s": list("xyxy"),
                                   "text": ["1", "2", "x", "4"], "inf": [1., np.inf, 2., 3.]})

    def field(self, **options):
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, self.frame, {"Response": "y", "Category": "c", **options})
        return raised.exception.field

    def test_roles_must_be_distinct_columns_and_the_response_numeric(self):
        self.assertEqual(self.field(Category="y"), "Category")
        self.assertEqual(self.field(**{"Split by": "y"}), "Split by")
        self.assertEqual(self.field(**{"Split by": "c"}), "Split by")
        self.assertEqual(self.field(Response="text"), "Response")
        self.assertEqual(self.field(Response="inf"), "Response")
        self.assertEqual(self.field(Response=""), "Response")
        self.assertEqual(self.field(Category=""), "Category")
        self.assertEqual(self.field(Category="missing"), "Category")
        self.assertEqual(self.field(**{"Split by": "missing"}), "Split by")

    def test_style_fields_are_validated_in_the_dispatcher(self):
        self.assertEqual(self.field(Style="Violin", **{"Bandwidth multiplier": -1}), "Bandwidth multiplier")
        self.assertEqual(self.field(Style="Violin", **{"Bandwidth multiplier": float("inf")}), "Bandwidth multiplier")
        self.assertEqual(self.field(Style="Violin", **{"Bandwidth multiplier": float("nan")}), "Bandwidth multiplier")
        self.assertEqual(self.field(Style="Violin", **{"Bandwidth multiplier": "x"}), "Bandwidth multiplier")
        self.assertEqual(self.field(Style="Cone"), "Style")
        self.assertEqual(self.field(Whiskers="Sideways"), "Whiskers")
        self.assertEqual(self.field(**{"Show mean": "yes"}), "Show mean")

    def test_no_complete_row_names_the_response(self):
        frame = pd.DataFrame({"y": [np.nan, 1.], "c": ["a", None]})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"Response": "y", "Category": "c"})
        self.assertEqual(raised.exception.field, "Response")

    def test_visibility_follows_the_published_rules(self):
        self.assertEqual(visibility("Box", "Tukey", False),
                         {"Whiskers": True, "Overlay observations": True, "Point placement": False,
                          "Bandwidth multiplier": False, "Median line": False, "Quartile lines": False})
        self.assertTrue(visibility("Violin", "Tukey", False)["Bandwidth multiplier"])
        self.assertFalse(visibility("Violin", "Tukey", False)["Whiskers"])
        self.assertTrue(visibility("Violin", "Tukey", True)["Point placement"])
        all_points = visibility("Box", "Min to max with all observations", False)
        self.assertTrue(all_points["Point placement"] and not all_points["Overlay observations"])

    def test_the_method_is_published_under_graphing_with_the_dialog_fields(self):
        self.assertIn(METHOD, GROUPS["Graphing"])
        self.assertEqual(list(METHODS[METHOD])[:3], ["Response", "Category", "Split by"])
        self.assertEqual(METHODS[METHOD]["Split by"], "Optional")
        for name in ("Style", "Whiskers", "Overlay observations", "Point placement", "Show mean",
                     "Bandwidth multiplier", "Median line", "Quartile lines"):
            self.assertIn(name, METHODS[METHOD])
        self.assertIn("Box / violin plot", GROUPS["Graphing"])


class Identities(unittest.TestCase):
    def mixed(self):
        categories = pd.Series([1, 1.0, "1", True] * 2, dtype=object)
        return pd.DataFrame({"y": np.arange(8.) * 2, "c": categories, "s": ["p:q", "r%s"] * 4})

    def test_values_with_the_same_text_stay_distinct_levels(self):
        result = grouped(self.mixed(), Response="y", Category="c", **{"Split by": "s"})
        cells = result.tables[CELLS_SHEET]
        self.assertEqual([type(value).__name__ for value in cells["Category"][::2]], ["int", "float", "str", "bool"])
        keys = [group.key for group in graph_groups(result.figure.axes[0])]
        self.assertEqual(len(keys), len(set(keys)))
        names = [group.name for group in graph_groups(result.figure.axes[0])]
        self.assertEqual(len(names), len(set(names)))

    def test_keys_are_reversible_and_delimited(self):
        for category, series in (("str:a:b", "str:c%d"), ("int:1", None), ("str:%3A", "str:/\\|&#")):
            identity = cell_identity(category, series)
            self.assertEqual(parse_identity(identity), (category, series))
            self.assertEqual(identity.count(":"), 1 if series is None else 2)
        result = grouped(self.mixed(), Response="y", Category="c", **{"Split by": "s"})
        for group in graph_groups(result.figure.axes[0]):
            kind, _, identity = group.key.partition(":")
            self.assertEqual(kind, "box")
            category, series = parse_identity(identity)
            self.assertIn(category, {typed_group_token(value) for value in (1, 1.0, "1", True)})
            self.assertIn(series, {"str:p:q", "str:r%s"})
        validated_style({"groups": {group.key: {"color": "#9b4174"} for group in graph_groups(result.figure.axes[0])}})

    def test_keys_and_colors_do_not_depend_on_the_order_of_the_sheet(self):
        frame, _ = fixture()
        shuffled = pd.concat([frame.iloc[8:], frame.iloc[:8]], ignore_index=True)
        first, second = grouped(frame), grouped(shuffled)
        self.assertNotEqual([g.x for g in graph_groups(first.figure.axes[0])],
                            [g.x for g in graph_groups(second.figure.axes[0])])
        first_edges = {group.key: edge(group) for group in graph_groups(first.figure.axes[0])}
        second_edges = {group.key: edge(group) for group in graph_groups(second.figure.axes[0])}
        self.assertEqual(first_edges, second_edges)

    def test_one_color_per_series_shared_by_every_category(self):
        frame, _ = fixture()
        groups = graph_groups(grouped(frame).figure.axes[0])
        drug_week, placebo_week, drug_baseline = (edge(group) for group in groups)
        self.assertEqual(drug_week, drug_baseline)
        self.assertNotEqual(drug_week, placebo_week)

    def test_a_color_stays_with_its_cell_after_rows_change(self):
        frame, _ = fixture()
        key = "box:" + cell_identity("str:Week $2$", "str:Placebo")
        style = {"groups": {key: {"color": "#9b4174"}}}
        full = grouped(frame)
        apply_style(full.figure, style)
        full_groups = {group.key: group for group in graph_groups(full.figure.axes[0])}
        self.assertEqual(edge(full_groups[key]), list(to_rgb("#9b4174")))
        # Drop the first cell, reorder the rows and exclude one observation of another cell.
        reduced = frame[~((frame.Visit == "Week $2$") & (frame.Treatment == "Drug"))].iloc[::-1].copy()
        reduced.loc[reduced.Signal == 7, "Signal"] = np.nan
        result = grouped(reduced)
        apply_style(result.figure, style)
        groups = {group.key: group for group in graph_groups(result.figure.axes[0])}
        self.assertEqual(edge(groups[key]), list(to_rgb("#9b4174")))
        others = [edge(group) for name, group in groups.items() if name != key]
        self.assertTrue(all(color != list(to_rgb("#9b4174")) for color in others))


class Legend(unittest.TestCase):
    def setUp(self):
        self.frame, _ = fixture()

    def key(self, category, series):
        return "box:" + cell_identity(typed_group_token(category), typed_group_token(series))

    def test_one_entry_per_series_with_stable_keys(self):
        result = grouped(self.frame)
        axes = result.figure.axes[0]
        legend = axes.get_legend()
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["Drug", "Placebo"])
        self.assertEqual(legend.get_title().get_text(), "Treatment")
        self.assertTrue(all(is_valid_entry_key(key) for key in legend._tramastat_legend_keys))
        entries = collect_legend_entries(result.figure)
        self.assertEqual([entry.key for entry in entries], ["group:str:Drug", "group:str:Placebo"])
        drug = to_rgb(graph_groups(axes)[0].artists[0][0].get_edgecolor())
        self.assertEqual(legend_colors(axes)[0], tuple(round(float(v), 6) for v in drug))

    def test_symbol_follows_the_first_visible_cell_of_the_series(self):
        result = grouped(self.frame)
        axes = result.figure.axes[0]
        first, second = self.key("Week $2$", "Drug"), self.key("Baseline", "Drug")
        apply_style(result.figure, {"groups": {first: {"color": "#9b4174"}}})
        self.assertEqual(legend_colors(axes)[0], tuple(round(float(v), 6) for v in to_rgb("#9b4174")))
        apply_style(result.figure, {"groups": {first: {"color": "#9b4174", "visible": False},
                                               second: {"color": "#2b8a73"}}})
        self.assertEqual(legend_colors(axes)[0], tuple(round(float(v), 6) for v in to_rgb("#2b8a73")))
        apply_style(result.figure, {})
        self.assertEqual(len(axes.get_legend().get_texts()), 2)

    def test_a_series_without_visible_cells_leaves_the_legend(self):
        result = grouped(self.frame)
        axes = result.figure.axes[0]
        hidden = {self.key("Week $2$", "Placebo"): {"visible": False}}
        apply_style(result.figure, {"groups": hidden})
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Drug"])
        everything = {group.key: {"visible": False} for group in graph_groups(axes)}
        apply_style(result.figure, {"groups": everything})
        self.assertIsNone(axes.get_legend())
        apply_style(result.figure, {})
        self.assertEqual(len(axes.get_legend().get_texts()), 2)

    def test_legend_choices_survive_a_group_edit(self):
        result = grouped(self.frame)
        axes = result.figure.axes[0]
        style = {"legend_size": 11, "groups": {self.key("Week $2$", "Placebo"): {"visible": False}}}
        apply_style(result.figure, style)
        self.assertEqual(axes.get_legend().get_texts()[0].get_fontsize(), 11)
        apply_style(result.figure, {"legend": "hidden", "groups": style["groups"]})
        self.assertIsNone(axes.get_legend())

    def test_the_legend_position_chosen_in_the_style_is_applied(self):
        result = grouped(self.frame)
        axes = result.figure.axes[0]
        outside = axes.get_legend()._loc
        apply_style(result.figure, {"legend": "lower right"})
        legend = axes.get_legend()
        self.assertEqual(legend._loc, 4)
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["Drug", "Placebo"])
        self.assertEqual(legend.get_title().get_text(), "Treatment")
        apply_style(result.figure, {"legend": "lower right", "legend_size": 12})
        self.assertEqual(axes.get_legend().get_texts()[0].get_fontsize(), 12)
        apply_style(result.figure, {})
        self.assertEqual(axes.get_legend()._loc, outside)
        apply_style(result.figure, {"legend": "hidden"})
        self.assertIsNone(axes.get_legend())

    def test_an_unsplit_plot_has_no_legend(self):
        self.assertIsNone(grouped(self.frame, **{"Split by": ""}).figure.axes[0].get_legend())


class Translation(unittest.TestCase):
    """Every message of the engine has an Italian text that keeps worksheet names literal."""

    def setUp(self):
        self.previous = i18n.active_language()
        i18n.set_language("it")
        self.addCleanup(i18n.set_language, self.previous)

    def italian(self, frame, **options):
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"Response": "y", "Category": "c", **options})
        english = str(raised.exception)
        i18n.set_language("en")
        try:
            self.assertEqual(i18n.translate_message(english, "grouped.error.", {"field": i18n.ui}), english)
        finally:
            i18n.set_language("it")
        return english, i18n.translate_message(english, "grouped.error.", {"field": i18n.ui})

    def test_engine_messages_are_translated_and_worksheet_names_stay_literal(self):
        frame = pd.DataFrame({"y": [1., 2., 3., 4.], "c": list("aabb"), "$s$": list("xyxy"), "t": list("abcd")})
        cases = (({"Category": "y"}, "diversa dalla risposta"), ({"Category": ""}, "Scegli una colonna per Categoria"),
                 ({"Category": "zz"}, "colonna esistente"), ({"Split by": "c"}, "diversa da Risposta e Categoria"),
                 ({"Response": "t"}, '"t"'), ({"Style": "Violin", "Bandwidth multiplier": -1}, "maggiore di zero"),
                 ({"Style": "Cone"}, "valore valido"), ({"Show mean": 3}, "sì o no"))
        for options, fragment in cases:
            english, text = self.italian(frame, **options)
            self.assertNotEqual(text, english, options)
            self.assertIn(fragment, text, (options, text))
            self.assertNotIn("{", text, options)
        english, text = self.italian(pd.DataFrame({"y": np.arange(41.), "c": np.arange(41)}))
        self.assertEqual(text, "Traccia fino a 40 celle alla volta (41 categorie × 1 serie).")

    def test_catalog_captions_for_the_dialog(self):
        self.assertEqual(i18n.ui(METHOD), "Distribuzioni raggruppate")
        self.assertEqual((i18n.ui("Category"), i18n.ui("Split by")), ("Categoria", "Dividi per"))
        for field in METHODS[METHOD]:
            self.assertIn(field, i18n.KEY_BY_LABEL, field)


class Export(unittest.TestCase):
    def test_graph_exports_as_vectors_and_the_sheets_use_native_columns(self):
        frame, _ = fixture()
        result = grouped(frame, Style="Violin", **{"Overlay observations": True})
        svg, pdf = io.BytesIO(), io.BytesIO()
        result.figure.savefig(svg, format="svg")
        result.figure.savefig(pdf, format="pdf")
        self.assertIn(b"<path", svg.getvalue())
        self.assertTrue(pdf.getvalue().startswith(b"%PDF"))
        for table in result.tables.values():
            self.assertTrue(table.index.is_unique)
        density = result.tables[DENSITY_SHEET]
        key = density.groupby(["Category", "Series", "Value"]).size()
        self.assertTrue((key == 1).all())


if __name__ == "__main__":
    unittest.main()
