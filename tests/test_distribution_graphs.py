from pathlib import Path
import tempfile
import unittest

from matplotlib.colors import to_rgb
import numpy as np
import pandas as pd

from analisi.data import Dataset, load_workspace, save_project
from analisi.distribution_graphs import MAX_POINTS
from analisi.presentation import apply_style, graph_groups, validate_graph_style, validated_style
from analisi.processing import FieldError
from analisi.workbench import METHODS, analyse

METHOD = "Box / violin plot"


def run(frame, **options):
    return analyse(METHOD, frame, {"Input": "Single response", "Style": "Box", **options})


def lines(result):
    axes = result.figure.axes[0]
    return [np.asarray(line.get_ydata(), dtype=float) for line in axes.lines]


def all_ordinates(result):
    """Value coordinates of every point marker: outlier symbols and scatter points (not whisker ends)."""
    axes = result.figure.axes[0]
    values = [y for line in axes.lines if line.get_linestyle() == "None" and line.get_marker() not in (None, "None", "")
              for y in np.asarray(line.get_ydata(), dtype=float)]
    for collection in axes.collections:
        offsets = np.asarray(collection.get_offsets())
        if offsets.size:
            values.extend(offsets[:, 1])
    return np.array(values)


class QuartileOracles(unittest.TestCase):
    def test_tukey_whiskers_end_on_observations(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8, 30]})
        result = run(frame, Response="v")
        row = result.tables["Group summary"].iloc[0]
        self.assertEqual(list(result.tables["Group summary"].columns[:3]), ["Group", "N", "Median"])
        self.assertEqual((row["Group"], row["N"], row["Median"]), ("All", 9, 5))
        self.assertEqual((row["Q1"], row["Q3"], row["Minimum"], row["Maximum"]), (2.5, 7.5, 1, 30))
        self.assertEqual((row["Lower whisker"], row["Upper whisker"], row["Outside whiskers"]), (1, 8, 1))
        drawn = lines(result)
        self.assertTrue(any(np.allclose(data, [2.5, 1]) for data in drawn))
        self.assertTrue(any(np.allclose(data, [7.5, 8]) for data in drawn))
        # The outlier is plotted exactly once and the box does not extend to it.
        self.assertEqual(int((all_ordinates(result) == 30).sum()), 1)
        plotted = result.tables["Plotted observations"]
        self.assertEqual(plotted[["Row", "Value", "Role"]].values.tolist(), [[9, 30.0, "Outside whiskers"]])

    def test_min_to_max_reaches_the_extreme(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8, 30]})
        row = run(frame, Response="v", Whiskers="Min to max").tables["Group summary"].iloc[0]
        self.assertEqual((row["Lower whisker"], row["Upper whisker"], row["Outside whiskers"]), (1, 30, 0))

    def test_value_exactly_on_the_fence_is_inside_on_both_sides(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 15]
        upper = run(pd.DataFrame({"v": values}), Response="v").tables["Group summary"].iloc[0]
        self.assertEqual((upper["Q1"], upper["Q3"], upper["Upper whisker"], upper["Outside whiskers"]),
                         (2.5, 7.5, 15, 0))
        mirrored = run(pd.DataFrame({"v": [-x for x in values]}), Response="v")
        lower = mirrored.tables["Group summary"].iloc[0]
        self.assertEqual((lower["Q1"], lower["Q3"], lower["Lower whisker"], lower["Outside whiskers"]),
                         (-7.5, -2.5, -15, 0))
        self.assertNotIn("Plotted observations", mirrored.tables)

    def test_percentile_whiskers(self):
        result = run(pd.DataFrame({"v": range(1, 21)}), Response="v", Whiskers="10–90")
        row = result.tables["Group summary"].iloc[0]
        self.assertAlmostEqual(row["Lower whisker"], 2.1)
        self.assertAlmostEqual(row["Upper whisker"], 18.9)
        self.assertEqual(sorted(result.tables["Plotted observations"]["Value"]), [1, 2, 19, 20])
        short = run(pd.DataFrame({"v": range(1, 7)}), Response="v", Whiskers="10–90")
        row = short.tables["Group summary"].iloc[0]
        self.assertEqual((row["Lower whisker"], row["Upper whisker"], row["Outside whiskers"]), (1, 6, 0))

    def test_every_percentile_option_matches_the_weibull_rule(self):
        data = np.array([3.2, 0.5, 9.9, 4.4, 1.1, 7.0, 2.8, 5.5, 6.1, 12.0, 0.2])
        for label, percent in (("5–95", 5), ("2.5–97.5", 2.5), ("1–99", 1)):
            row = run(pd.DataFrame({"v": data}), Response="v", Whiskers=label).tables["Group summary"].iloc[0]
            low, high = np.percentile(data, [percent, 100 - percent], method="weibull")
            self.assertAlmostEqual(row["Lower whisker"], low)
            self.assertAlmostEqual(row["Upper whisker"], high)
        row = run(pd.DataFrame({"v": data}), Response="v").tables["Group summary"].iloc[0]
        q1, median, q3 = np.percentile(data, [25, 50, 75], method="weibull")
        self.assertAlmostEqual(row["Q1"], q1)
        self.assertAlmostEqual(row["Median"], median)
        self.assertAlmostEqual(row["Q3"], q3)

    def test_all_observations_mode_marks_each_point_once(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8, 30]})
        result = run(frame, Response="v", Whiskers="Min to max with all observations")
        plotted = result.tables["Plotted observations"]
        self.assertEqual(len(plotted), 9)
        self.assertEqual(int((all_ordinates(result) == 30).sum()), 1)
        self.assertTrue((plotted["Role"] == "Overlay").all())

    def test_overlay_keeps_outliers_distinct_from_overlay_points(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8, 30]})
        result = run(frame, Response="v", **{"Overlay observations": True, "Point placement": "Centered"})
        plotted = result.tables["Plotted observations"]
        self.assertEqual(plotted["Role"].value_counts().to_dict(), {"Overlay": 8, "Outside whiskers": 1})
        self.assertEqual(int((all_ordinates(result) == 30).sum()), 1)

    def test_few_observations_show_median_and_range(self):
        result = run(pd.DataFrame({"v": [5, 7, 22]}), Response="v")
        row = result.tables["Group summary"].iloc[0]
        self.assertEqual((row["N"], row["Median"], row["Minimum"], row["Maximum"]), (3, 7, 5, 22))
        self.assertTrue(np.isnan(row["Q1"]) and np.isnan(row["Q3"]))
        self.assertEqual((row["Lower whisker"], row["Upper whisker"], row["Outside whiskers"]), (5, 22, 0))
        self.assertIn("median and range", row["Note"])
        two = run(pd.DataFrame({"v": [4, 9]}), Response="v").tables["Group summary"].iloc[0]
        self.assertEqual((two["N"], two["Median"], two["Minimum"], two["Maximum"]), (2, 6.5, 4, 9))

    def test_zero_iqr_collapses_the_box(self):
        row = run(pd.DataFrame({"v": [3, 3, 3, 3, 3]}), Response="v").tables["Group summary"].iloc[0]
        self.assertEqual((row["Q1"], row["Q3"], row["Lower whisker"], row["Upper whisker"], row["Median"]),
                         (3, 3, 3, 3, 3))
        spiky = run(pd.DataFrame({"v": [3, 3, 3, 3, 3, 3, 3, 9]}), Response="v").tables["Group summary"].iloc[0]
        self.assertEqual((spiky["Q1"], spiky["Q3"], spiky["Upper whisker"], spiky["Outside whiskers"]), (3, 3, 3, 1))


class ViolinOracles(unittest.TestCase):
    def violin(self, frame, **options):
        return analyse(METHOD, frame, {"Input": "Single response", "Style": "Violin", **options})

    def polygon(self, result):
        axes = result.figure.axes[0]
        return np.concatenate([path.vertices for collection in axes.collections
                               if collection.__class__.__name__ == "FillBetweenPolyCollection"
                               for path in collection.get_paths()])

    def test_symmetric_density_and_support(self):
        frame = pd.DataFrame({"v": [-2, -1, 0, 1, 2]})
        result = self.violin(frame, Response="v")
        density = result.tables["Violin density"]
        self.assertEqual(density["Value"].iloc[0], -2)
        self.assertEqual(density["Value"].iloc[-1], 2)
        np.testing.assert_allclose(density["Density"], density["Density"].to_numpy()[::-1], atol=1e-12)
        np.testing.assert_allclose(density["Half-width"], density["Half-width"].to_numpy()[::-1], atol=1e-12)
        vertices = self.polygon(result)
        self.assertEqual((vertices[:, 1].min(), vertices[:, 1].max()), (-2, 2))
        row = result.tables["Group summary"].iloc[0]
        self.assertEqual((row["Median"], row["N"], row["Minimum"], row["Maximum"]), (0, 5, -2, 2))
        # Scott: h = 5 ** (-1/5) * sample SD (sqrt(2.5)) for the default multiplier.
        self.assertAlmostEqual(row["Bandwidth"], 5 ** -.2 * np.sqrt(2.5))

    def test_density_values_match_the_gaussian_sum(self):
        frame = pd.DataFrame({"v": [-2, -1, 0, 1, 2]})
        density = self.violin(frame, Response="v").tables["Violin density"]
        h = 5 ** -.2 * np.sqrt(2.5)
        y = density["Value"].to_numpy()[57]
        expected = sum(np.exp(-.5 * ((y - x) / h) ** 2) for x in (-2, -1, 0, 1, 2)) / (5 * h * np.sqrt(2 * np.pi))
        self.assertAlmostEqual(density["Density"].iloc[57], expected, places=12)

    def test_bandwidth_multiplier_changes_density_only(self):
        frame = pd.DataFrame({"v": [-2, -1, 0, 1, 2]})
        base = self.violin(frame, Response="v")
        wide = self.violin(frame, Response="v", **{"Bandwidth multiplier": 2.0})
        a, b = base.tables["Violin density"], wide.tables["Violin density"]
        np.testing.assert_array_equal(a["Value"], b["Value"])
        self.assertFalse(np.allclose(a["Density"], b["Density"]))
        keep = ["N", "Median", "Q1", "Q3", "Minimum", "Maximum"]
        pd.testing.assert_frame_equal(base.tables["Group summary"][keep], wide.tables["Group summary"][keep])
        self.assertAlmostEqual(wide.tables["Group summary"]["Bandwidth"].iloc[0],
                               2 * base.tables["Group summary"]["Bandwidth"].iloc[0])

    def test_median_and_quartile_lines_follow_the_violin_width(self):
        frame = pd.DataFrame({"v": [1, 2, 2, 3, 3, 3, 4, 4, 5, 9]})
        result = self.violin(frame, Response="v")
        density = result.tables["Violin density"]
        row = result.tables["Group summary"].iloc[0]
        axes = result.figure.axes[0]
        segments = np.concatenate([c.get_segments() for c in axes.collections
                                   if c.__class__.__name__ == "LineCollection"])
        for level in (row["Median"], row["Q1"], row["Q3"]):
            reach = np.interp(level, density["Value"], density["Half-width"])
            match = [s for s in segments if np.isclose(s[0, 1], level) and np.isclose(s[1, 1], level)]
            self.assertEqual(len(match), 1)
            self.assertAlmostEqual(match[0][0, 0], 1 - reach)
            self.assertAlmostEqual(match[0][1, 0], 1 + reach)

    def test_equal_maximum_width_for_every_group(self):
        frame = pd.DataFrame({"a": [1, 2, 3, 4, 5, 6.5, 8], "b": [10, 10.5, 11, 40, 41, 42, 43]})
        density = self.violin(frame, Input="Separate columns", Variables=["a", "b"]).tables["Violin density"]
        self.assertTrue(np.allclose(density.groupby("Group")["Half-width"].max(), .4))

    def test_constant_group_uses_a_fallback_without_hurting_others(self):
        frame = pd.DataFrame({"flat": [3, 3, 3, 3, 3], "good": [1, 2, 4, 7, 11]})
        result = self.violin(frame, Input="Separate columns", Variables=["flat", "good"])
        summary = result.tables["Group summary"]
        self.assertIn("constant", summary["Note"].iloc[0])
        self.assertEqual(summary["Note"].iloc[1], "")
        self.assertEqual(set(result.tables["Violin density"]["Group"]), {"good"})
        self.assertTrue(np.isnan(summary["Bandwidth"].iloc[0]))
        self.assertGreater(summary["Bandwidth"].iloc[1], 0)
        single = self.violin(pd.DataFrame({"v": [4.0]}), Response="v").tables["Group summary"]
        self.assertIn("one observation", single["Note"].iloc[0])

    def test_invalid_bandwidth_names_the_field(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5]})
        for value in (1e-320, 0, -1, np.inf, np.nan, "abc", True):
            with self.assertRaises(FieldError) as caught:
                self.violin(frame, Response="v", **{"Bandwidth multiplier": value})
            self.assertEqual(caught.exception.field, "Bandwidth multiplier")
        # Box plots do not use the multiplier and ignore a stale value.
        run(frame, Response="v", **{"Bandwidth multiplier": 0})

    def test_jitter_is_repeatable(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7]})
        options = dict(Response="v", **{"Overlay observations": True, "Point placement": "Jitter"})
        first, second = (self.violin(frame, **options).figure.axes[0].collections[-1].get_offsets().tolist()
                         for _ in range(2))
        self.assertEqual(first, second)


class DataRoles(unittest.TestCase):
    def test_columns_keep_sheet_order_and_independent_missing_cells(self):
        frame = pd.DataFrame({"Late": [9, 8, 7, 6, 5.5, 5], "Early": [1, 2, 3, 4, np.nan, 6],
                              "Skip": [1, 1, 1, 1, 1, 1], "Masked": [10, np.nan, 12, 14, 15, 16]})
        result = run(frame, Input="Separate columns", Variables=["Masked", "Late", "Early"])
        summary = result.tables["Group summary"].set_index("Group")
        self.assertEqual(list(summary.index), ["Late", "Early", "Masked"])
        self.assertEqual(summary["N"].to_dict(), {"Late": 6, "Early": 5, "Masked": 5})
        self.assertEqual(summary.loc["Early", ["Q1", "Median", "Q3"]].tolist(), [1.5, 3.0, 5.0])
        self.assertEqual(summary.loc["Masked", ["Q1", "Median", "Q3"]].tolist(), [11.0, 14.0, 15.5])
        self.assertEqual(summary.loc["Late", ["Q1", "Median", "Q3"]].tolist(), [5.375, 6.5, 8.25])

    def test_groups_keep_order_of_first_appearance_and_all_is_just_a_name(self):
        frame = pd.DataFrame({"y": [5, 1, 9, 2, 8, 3, 7, 4], "g": ["b", "All", "b", "All", "é", "All", "é", "b"]})
        result = run(frame, Response="y", Group="g")
        summary = result.tables["Group summary"]
        self.assertEqual(summary["Group"].tolist(), ["b", "All", "é"])
        self.assertEqual(summary["N"].tolist(), [3, 3, 2])
        self.assertEqual(summary["Median"].tolist(), [5, 2, 7.5])
        self.assertEqual(result.figure.axes[0].get_xticklabels()[1].get_text(), "All")

    def test_row_order_does_not_change_statistics_or_density(self):
        rng = np.random.default_rng(7)
        frame = pd.DataFrame({"y": rng.normal(size=60), "g": np.repeat(["x", "y", "z"], 20)})
        shuffled = frame.sample(frac=1, random_state=3).reset_index(drop=True)
        for style in ("Box", "Violin"):
            a = analyse(METHOD, frame, {"Input": "Single response", "Response": "y", "Group": "g", "Style": style})
            b = analyse(METHOD, shuffled, {"Input": "Single response", "Response": "y", "Group": "g", "Style": style})
            first, second = (r.tables["Group summary"].set_index("Group").sort_index() for r in (a, b))
            pd.testing.assert_frame_equal(first.drop(columns="Note"), second.drop(columns="Note"))
            if style == "Violin":
                d1 = a.tables["Violin density"].sort_values(["Group", "Value"]).reset_index(drop=True)
                d2 = b.tables["Violin density"].sort_values(["Group", "Value"]).reset_index(drop=True)
                pd.testing.assert_frame_equal(d1, d2)

    def test_source_rows_identify_observations_and_blank_response_rows_are_skipped(self):
        frame = pd.DataFrame({"y": [1, 2, np.nan, 3, 4, 5, 6, 7, 8, 9, 200], "g": list("aaaabbbbbbb")})
        plotted = run(frame, Response="y", Group="g", **{"Overlay observations": True,
                                                         "Point placement": "Centered"}).tables["Plotted observations"]
        self.assertEqual(plotted[plotted["Group"] == "a"]["Row"].tolist(), [1, 2, 4])
        self.assertEqual(plotted[plotted["Role"] == "Outside whiskers"][["Group", "Row"]].values.tolist(), [["b", 11]])

    def test_groups_without_observations_are_omitted_with_a_note(self):
        frame = pd.DataFrame({"y": [1, 2, 3, 4, np.nan, np.nan], "g": list("aaaabb")})
        result = run(frame, Response="y", Group="g")
        self.assertEqual(result.tables["Group summary"]["Group"].tolist(), ["a"])
        self.assertEqual(result.tables["Settings"].loc["Omitted (no observations)", "Value"], "b")

    def test_selection_errors_name_the_field(self):
        frame = pd.DataFrame({"y": [np.nan, np.nan], "g": ["a", "b"], "z": [1, 2], "text": ["a", "b"]})
        cases = ((dict(Response="y"), "Response"), (dict(Input="Separate columns", Variables=["y"]), "Variables"),
                 (dict(Input="Separate columns", Variables=[]), "Variables"),
                 (dict(Response="z", Group="z"), "Group"), (dict(Response="text"), "Response"),
                 (dict(Input="Several"), "Input"), (dict(Response="z", Whiskers="Other"), "Whiskers"))
        for options, field in cases:
            with self.subTest(options=options), self.assertRaises(FieldError) as caught:
                run(frame, **options)
            self.assertEqual(caught.exception.field, field)

    def test_budget_is_reported_on_the_field(self):
        frame = pd.DataFrame({"y": np.arange(MAX_POINTS + 1, dtype=float)})
        with self.assertRaises(FieldError) as caught:
            run(frame, Response="y")
        self.assertEqual(caught.exception.field, "Response")
        many = pd.DataFrame(np.arange(82, dtype=float).reshape(2, 41), columns=[f"c{i}" for i in range(41)])
        with self.assertRaises(FieldError) as caught:
            run(many, Input="Separate columns", Variables=list(many.columns))
        self.assertEqual(caught.exception.field, "Variables")

    def test_recipes_saved_before_the_new_fields_still_run(self):
        frame = pd.DataFrame({"y": [1, 2, 3, 4, 5, 6, 7, 8, 30]})
        recipe = {"Response": "y", "Style": "Box"}
        old_box = analyse(METHOD, frame, recipe)
        self.assertEqual(old_box.tables["Group summary"].columns.tolist(), ["Group", "N", "Median"])
        self.assertTrue(any(data.size == 2 and np.allclose(data, [3, 1]) for data in lines(old_box)))
        self.assertTrue(any(data.size == 2 and np.allclose(data, [7, 8]) for data in lines(old_box)))
        updated = analyse(METHOD, frame, {**recipe, "Input": "Single response"})
        self.assertEqual(updated.tables["Group summary"].at[0, "Q1"], 2.5)
        old_violin = analyse(METHOD, frame, {**recipe, "Style": "Violin"})
        self.assertEqual(list(old_violin.tables), ["Group summary"])
        self.assertEqual(old_violin.tables["Group summary"]["N"].tolist(), [9])
        self.assertEqual(list(METHODS[METHOD])[:2], ["Input", "Response"])


COLUMNS = {"Control": [1, 2, 3, 4, 5, 6, 7, 30.], "Drug A": [4, 5, 6, 7, 8, 9, 10, 11.], "Drug B": [3.] * 8}
SEPARATE = {"Input": "Separate columns", "Variables": list(COLUMNS)}


def edge(group):
    return np.atleast_2d(group.artists[0][0].get_edgecolor())[0][:3].tolist()


def visible(group):
    return [artist.get_visible() for artist, _ in group.artists]


def groups_of(result):
    return {group.key.split(":", 1)[1]: group for group in graph_groups(result.figure.axes[0])}


class GroupFormatTests(unittest.TestCase):
    """Per-group color and visibility, keyed by source identity."""

    def separate(self, columns=None, **options):
        frame = pd.DataFrame(COLUMNS if columns is None else columns)
        return analyse(METHOD, frame, {**SEPARATE, "Variables": list(frame), "Style": "Box", **options})

    def test_group_keys_use_column_names_and_list_artists_in_plot_order(self):
        result = self.separate()
        groups = graph_groups(result.figure.axes[0])
        self.assertEqual([group.key for group in groups],
                         ["box:column:Control", "box:column:Drug A", "box:column:Drug B"])
        self.assertEqual([group.name for group in groups], list(COLUMNS))
        self.assertEqual([group.x for group in groups], [1., 2., 3.])
        # box, two whiskers, two caps, median and the outlier symbols (no overlay)
        self.assertEqual([role for _, role in groups[0].artists], ["fill"] + ["line"] * 5 + ["marker"])
        violin = self.separate(Style="Violin", **{"Overlay observations": True})
        self.assertEqual([group.key for group in graph_groups(violin.figure.axes[0])][0], "violin:column:Control")

    def test_string_and_number_with_the_same_label_stay_distinct(self):
        frame = pd.DataFrame({"Value": [1., 2., 3., 4., 5., 6., 7., 8.],
                              "Arm": pd.Series([1, 1, 1, 1, "1", "1", "1", "1"], dtype=object)})
        result = run(frame, Response="Value", Group="Arm")
        keys = [group.key for group in graph_groups(result.figure.axes[0])]
        self.assertEqual(keys, ["box:category:int:1", "box:category:str:1"])
        style = {"groups": {"box:category:str:1": {"color": "#9b4174"}}}
        apply_style(result.figure, style)
        first, second = graph_groups(result.figure.axes[0])
        self.assertEqual(edge(second), list(to_rgb("#9b4174")))
        self.assertNotEqual(edge(first), list(to_rgb("#9b4174")))
        self.assertEqual(self.keys_without_group(), ["box:all"])

    def keys_without_group(self):
        result = run(pd.DataFrame({"y": [1., 2., 3., 4., 5.]}), Response="y")
        return [group.key for group in graph_groups(result.figure.axes[0])]

    def test_removing_the_first_group_or_reordering_does_not_shift_the_style(self):
        style = {"groups": {"box:column:Drug A": {"color": "#9b4174"}, "box:column:Control": {"visible": False}}}
        full = self.separate()
        apply_style(full.figure, style)
        self.assertEqual(edge(groups_of(full)["column:Drug A"]), list(to_rgb("#9b4174")))
        for columns in ({"Drug A": COLUMNS["Drug A"], "Drug B": COLUMNS["Drug B"]},
                        {"Drug B": COLUMNS["Drug B"], "Drug A": COLUMNS["Drug A"], "Control": COLUMNS["Control"]}):
            result = self.separate(columns)
            apply_style(result.figure, style)
            groups = groups_of(result)
            self.assertEqual(edge(groups["column:Drug A"]), list(to_rgb("#9b4174")))
            self.assertNotEqual(edge(groups["column:Drug B"]), list(to_rgb("#9b4174")))
            if "column:Control" in groups:
                self.assertFalse(any(visible(groups["column:Control"])))
        # Single response: the order of first appearance changes, the style follows the category.
        values = [1., 2., 3., 4., 5., 6., 7., 8.]
        one = pd.DataFrame({"y": values * 2, "g": list("xxxxxxxx") + list("yyyyyyyy")})
        two = pd.DataFrame({"y": values * 2, "g": list("yyyyyyyy") + list("xxxxxxxx")})
        category = {"groups": {"box:category:str:y": {"color": "#9b4174"}}}
        for frame in (one, two):
            result = run(frame, Response="y", Group="g")
            apply_style(result.figure, category)
            groups = groups_of(result)
            self.assertEqual(edge(groups["category:str:y"]), list(to_rgb("#9b4174")))
            self.assertNotEqual(edge(groups["category:str:x"]), list(to_rgb("#9b4174")))

    def test_color_keeps_alpha_and_contrast_and_reaches_every_artist(self):
        result = self.separate(**{"Overlay observations": True, "Show mean": True})
        axes = result.figure.axes[0]
        drug_a = graph_groups(axes)[1]
        alpha, width = drug_a.artists[0][0].get_facecolor()[3], drug_a.artists[0][0].get_linewidth()
        median_width = drug_a.artists[5][0].get_linewidth()
        apply_style(result.figure, {"groups": {"box:column:Drug A": {"color": "#9b4174"}}})
        color = to_rgb("#9b4174")
        box = drug_a.artists[0][0]
        self.assertEqual(list(box.get_facecolor()), [*color, alpha])
        self.assertEqual(list(box.get_edgecolor())[:3], list(color))
        self.assertEqual(box.get_linewidth(), width)
        for artist, role in drug_a.artists[1:6]:
            self.assertEqual(artist.get_color(), "#9b4174")
        self.assertEqual(drug_a.artists[5][0].get_linewidth(), median_width)
        roles = {role: artist for artist, role in drug_a.artists}
        self.assertEqual(roles["marker"].get_markeredgecolor(), "#9b4174")
        self.assertEqual(roles["marker"].get_markerfacecolor(), "white")
        self.assertEqual(list(roles["point"].get_facecolor()[0][:3]), list(color))
        self.assertEqual(list(roles["point"].get_edgecolor()[0][:3]), [1., 1., 1.])
        self.assertEqual(list(roles["mean"].get_edgecolor()[0][:3]), list(color))
        violin = self.separate(Style="Violin", **{"Overlay observations": True})
        group = graph_groups(violin.figure.axes[0])[1]
        alpha = group.artists[0][0].get_facecolor()[0][3]
        apply_style(violin.figure, {"groups": {"violin:column:Drug A": {"color": "#9b4174"}}})
        self.assertEqual(list(group.artists[0][0].get_facecolor()[0]), [*color, alpha])
        self.assertEqual(list(group.artists[1][0].get_edgecolor()[0][:3]), list(color))

    def test_hiding_a_group_hides_all_of_its_artists_and_nothing_else(self):
        for style_name in ("Box", "Violin"):
            result = self.separate(Style=style_name, **{"Overlay observations": True})
            axes, kind = result.figure.axes[0], style_name.lower()
            tables = {name: table.copy() for name, table in result.tables.items()}
            limits = axes.get_xlim(), axes.get_ylim()
            ticks = [label.get_text() for label in axes.get_xticklabels()]
            apply_style(result.figure, {"groups": {f"{kind}:column:Control": {"visible": False}}})
            result.figure.canvas.draw()
            groups = groups_of(result)
            self.assertFalse(any(visible(groups["column:Control"])), style_name)
            self.assertTrue(all(visible(groups["column:Drug A"])) and all(visible(groups["column:Drug B"])))
            self.assertEqual((axes.get_xlim(), axes.get_ylim()), limits)
            self.assertEqual([label.get_text() for label in axes.get_xticklabels()], ticks)
            for name, table in tables.items():
                pd.testing.assert_frame_equal(result.tables[name], table)
            if style_name == "Box":
                self.assertEqual(result.tables["Group summary"].loc[0, "Outside whiskers"], 1)
                flier, = [artist for artist, role in groups["column:Control"].artists if role == "marker"]
                self.assertIn(30., list(flier.get_ydata()))
                self.assertFalse(flier.get_visible())
            else:
                # The constant group is drawn as a line and can be formatted.
                constant = groups["column:Drug B"]
                self.assertTrue(any(artist.get_linewidth() == 2.2 for artist, role in constant.artists
                                    if role == "line"))
                apply_style(result.figure, {"groups": {"violin:column:Drug B": {"color": "#2b8a73"}}})
                self.assertEqual(list(np.atleast_2d(constant.artists[0][0].get_edgecolor())[0][:3]),
                                 list(to_rgb("#2b8a73")))

    def test_reset_and_recalculation_restore_default_colors_and_limits(self):
        result = self.separate()
        axes = result.figure.axes[0]
        defaults = [edge(group) for group in graph_groups(axes)]
        limits = axes.get_xlim(), axes.get_ylim()
        apply_style(result.figure, {"groups": {"box:column:Control": {"color": "#9b4174", "visible": False}}})
        apply_style(result.figure, {})
        self.assertEqual([edge(group) for group in graph_groups(axes)], defaults)
        self.assertTrue(all(visible(group) for group in graph_groups(axes)))
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), limits)
        # A recalculation with new data starts again from the default palette.
        changed = self.separate({**COLUMNS, "Control": [2, 3, 4, 5, 6, 7, 8, 9.]})
        apply_style(changed.figure, {"groups": {"box:column:Drug A": {"color": "#9b4174"}}})
        apply_style(changed.figure, {})
        self.assertEqual([edge(group) for group in graph_groups(changed.figure.axes[0])], defaults)

    def test_a_group_that_disappears_keeps_its_saved_style_for_its_return(self):
        style = {"groups": {"box:column:Control": {"visible": False}, "box:column:Drug A": {"color": "#9b4174"}}}
        without = self.separate({name: COLUMNS[name] for name in ("Drug A", "Drug B")})
        apply_style(without.figure, style)
        self.assertEqual(edge(groups_of(without)["column:Drug A"]), list(to_rgb("#9b4174")))
        self.assertEqual(style["groups"]["box:column:Control"], {"visible": False})
        back = self.separate()
        apply_style(back.figure, style)
        self.assertFalse(any(visible(groups_of(back)["column:Control"])))

    def test_style_format_accepts_old_styles_and_rejects_bad_group_fields(self):
        validated_style({"title": "Old", "series": {"line:1:Trend": {"color": "#112233"}}})
        validated_style({"groups": {"box:column:Control": {"color": "#112233", "visible": False}}})
        for bad in ({"groups": {"box:column:A": {"width": 2}}},
                    {"groups": {"box:column:A": {"color": "not a color"}}},
                    {"groups": {"box:column:A": {"visible": "no"}}},
                    {"groups": {"bar:column:A": {"visible": False}}},
                    {"groups": {"box:": {"visible": False}}},
                    {"groups": []}):
            with self.assertRaises(ValueError, msg=bad):
                validated_style(bad)
        result = self.separate()
        validate_graph_style(result.figure.axes[0], {"groups": {"box:column:Missing": {"visible": False}}})

    def test_recipes_from_before_the_new_fields_keep_geometry_and_have_no_groups(self):
        frame = pd.DataFrame({"y": [1, 2, 3, 4, 5, 6, 7, 8, 30]})
        old = analyse(METHOD, frame, {"Response": "y", "Style": "Box"})
        before = [np.asarray(line.get_ydata(), dtype=float).tolist() for line in old.figure.axes[0].lines]
        self.assertEqual(graph_groups(old.figure.axes[0]), [])
        apply_style(old.figure, {"title": "Old", "groups": {"box:all": {"visible": False}}})
        self.assertEqual([np.asarray(line.get_ydata(), dtype=float).tolist() for line in old.figure.axes[0].lines], before)
        self.assertTrue(any(data == [3., 1.] or data == [3.0, 1.0] for data in before if len(data) == 2))

    def test_group_styles_survive_saving_and_reopening_a_project(self):
        style = {"groups": {"box:column:Control": {"visible": False}, "box:column:Drug A": {"color": "#9b4174"}}}
        data = Dataset(pd.DataFrame(COLUMNS))
        data.analyses.append((METHOD, {**SEPARATE, "Style": "Box"}))
        data.graph_styles[0] = style
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.alab"
            save_project(path, {"Groups": data})
            reopened, _ = load_workspace(path)
        self.assertEqual(reopened["Groups"].graph_styles[0], style)


if __name__ == "__main__":
    unittest.main()
