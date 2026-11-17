"""Oracles for the geometry of native column and grouped charts."""
from io import BytesIO, StringIO
import unittest

from matplotlib.collections import LineCollection
from matplotlib.container import ErrorbarContainer
import numpy as np
import pandas as pd

from analisi.category_graphs import GROUPED_OPTIONS, category_graph, default_grouped_input
from analisi.data import Dataset
from analisi.presentation import apply_style, graph_series


class CategoryGraphTests(unittest.TestCase):
    def test_columns_bars_and_sample_confidence_intervals(self):
        frame = pd.DataFrame({"Control": [1., 2., 3., None], "Treatment": [2., 4., 6., 8.]})
        result = category_graph(frame, {"Variables": list(frame), "Graph style": "Bars",
                                        "Interval": "Confidence interval", "Confidence level (%)": 95})
        table = result.tables["Graph data"]
        self.assertEqual(table["N"].tolist(), [3, 4])
        np.testing.assert_allclose(table["Mean"], [2., 5.])
        np.testing.assert_allclose(table["Upper"] - table["Mean"], [2.4841377117, 4.1085205135], rtol=1e-9)
        axis, = result.figure.axes
        self.assertEqual([patch.get_height() for patch in axis.patches], [2., 5.])
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], list(frame))
        handles = [series for series in graph_series(axis) if series.kind == "bar"]
        self.assertEqual(len(handles), 2)
        apply_style(result.figure, {"series": {handles[0].key: {"color": "#356547"}}})
        self.assertNotEqual(axis.patches[0].get_facecolor(), axis.patches[1].get_facecolor())

    def test_floating_ranges_preserve_negative_values_and_show_each_point(self):
        frame = pd.DataFrame({"A": [-3., -2., 2., None], "B": [-2., -2., 1., 2.]})
        result = category_graph(frame, {"Variables": list(frame), "Graph style": "Floating range",
                                        "Overlay observations": True, "Interval": "unavailable"})
        table = result.tables["Graph data"]
        np.testing.assert_array_equal(table[["Lower", "Upper"]].to_numpy(), [[-3., 2.], [-2., 2.]])
        axis, = result.figure.axes
        self.assertEqual([(p.get_y(), p.get_height()) for p in axis.patches], [(-3., 5.), (-2., 4.)])
        offsets = axis.collections[-1].get_offsets()
        self.assertEqual(offsets[:, 1].tolist(), [-2., -2., 1., 2.])
        self.assertLess(offsets[0, 0], offsets[1, 0])
        out = BytesIO()
        result.figure.savefig(out, format="svg")
        self.assertIn(b"<svg", out.getvalue())

    def test_matched_rows_never_bridge_missing_values(self):
        frame = pd.DataFrame({"Week 1": [1., 2., None], "Week 2": [2., None, 3.], "Week 3": [3., 4., 5.]})
        data = Dataset(frame, excluded={(0, 1)}).frame(mask_excluded=True)
        result = category_graph(data, {"Variables": list(frame), "Graph style": "Before and after"})
        axis, = result.figure.axes
        collection = next(item for item in axis.collections if isinstance(item, LineCollection))
        np.testing.assert_array_equal(collection.get_segments(), [[[1., 3.], [2., 5.]]])
        self.assertEqual(result.tables["Graph data"]["N"].tolist(), [2, 1, 3])

    def test_grouped_respects_native_roles_and_exclusions(self):
        frame = pd.DataFrame({"Visit": [1, 2, 3], "Baseline [1]": [2., 4., None], "Baseline [2]": [4., 6., None],
                              "Follow-up [1]": [6., 8., None], "Follow-up [2]": [8., None, None]})
        frame.attrs["worksheet_roles"] = {"x": [], "y": [["Baseline [1]", "Baseline [2]"],
                                                          ["Follow-up [1]", "Follow-up [2]"]]}
        dataset = Dataset(frame, excluded={(0, 2)})
        options = {"Variables": list(frame), "Graph style": "Bars", "Interval": "SEM"}
        result = category_graph(dataset.frame(mask_excluded=True), options, grouped=True)
        table = result.tables["Graph data"]
        self.assertEqual(table["Row"].tolist(), ["1", "2", "1", "2"])
        self.assertEqual(table["Group"].tolist(), ["Baseline", "Baseline", "Follow-up", "Follow-up"])
        self.assertEqual(table["N"].tolist(), [1, 2, 2, 1])
        np.testing.assert_allclose(table["Mean"], [2., 5., 7., 8.])
        np.testing.assert_allclose(table["Upper"], [np.nan, 6., 8., np.nan], equal_nan=True)
        axis, = result.figure.axes
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ["1", "2"])
        self.assertLess(axis.patches[0].get_x(), axis.patches[2].get_x())
        overlaid = category_graph(dataset.frame(mask_excluded=True),
                                 {**options, "Placement of groups": "Superimposed"}, grouped=True).figure.axes[0]
        self.assertEqual(overlaid.patches[0].get_x(), overlaid.patches[2].get_x())

    def test_single_grouped_row_uses_group_labels(self):
        frame = pd.DataFrame({"Row title": ["Trial 1"], "A [1]": [2.], "A [2]": [4.], "B [1]": [7.]})
        result = category_graph(frame, {"Variables": list(frame)}, grouped=True)
        axis, = result.figure.axes
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ["A", "B"])
        self.assertIsNone(axis.get_legend())

    def test_rejects_invalid_intervals_and_presummarized_replicates(self):
        frame = pd.DataFrame({"A": [1., 2., 9.]})
        for options, message in [
            ({"Center": "Median", "Interval": "SEM"}, "for a median"),
            ({"Interval": "Confidence interval", "Confidence level (%)": 100}, "strictly between"),
            ({"Graph style": "Before and after"}, "at least two"),
        ]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                category_graph(frame, {"Variables": list(frame), **options})
        frame.columns = ["A [Mean]"]
        with self.assertRaisesRegex(ValueError, "raw replicate"):
            category_graph(frame, {"Variables": list(frame)}, grouped=True)


def _csv(text):
    return pd.read_csv(StringIO(text))


def _whiskers(axis):
    """Return (x, lower, upper) for each drawn error bar, in series order."""
    found = []
    for container in axis.containers:
        if isinstance(container, ErrorbarContainer):
            collection, = container.lines[2]
            found.append([(start[0], *sorted((start[1], stop[1]))) for start, stop in collection.get_segments()])
    return found


SUMMARIES = {"Input": "Precomputed summaries"}
A1 = """Row title,Control [Mean],Control [SD],Control [N],Treated [Mean],Treated [SD],Treated [N]
Day 1,10,2,4,15,3,9
Day 2,20,4,16,18,2,4
Day 3,30,,25,,,
"""
A2 = """Row title,A [Center],A [Minus],A [Plus],B [Mean],B [Lower],B [Upper]
First,4,1,3,8,6,13
Second,5,0,2,9,9,9
Third,6,1,,10,,11
"""


class GroupedSummaryTests(unittest.TestCase):
    def graph(self, frame, **options):
        names = options.pop("names", [name for name in frame if name != "Row title"])
        return category_graph(frame, {"Variables": names, **SUMMARIES, **options}, grouped=True)

    def test_sd_and_sem_derived_from_sd_and_n(self):
        frame = _csv(A1)
        for error, control, treated in [("SD", [(8, 12), (16, 24)], [(12, 18), (16, 20)]),
                                        ("SEM", [(9, 11), (19, 21)], [(14, 16), (17, 19)])]:
            with self.subTest(error=error):
                result = self.graph(frame, **{"Summary error": error})
                axis, = result.figure.axes
                np.testing.assert_allclose([patch.get_height() for patch in axis.patches], [10, 20, 30, 15, 18],
                                           atol=1e-10)
                first, second = _whiskers(axis)
                np.testing.assert_allclose([pair[1:] for pair in first], control, atol=1e-10)
                np.testing.assert_allclose([pair[1:] for pair in second], treated, atol=1e-10)
                self.assertEqual(len(first), 2)  # 30 stays visible without a whisker.
                self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ["Day 1", "Day 2", "Day 3"])
                self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()], ["Control", "Treated"])
                table = result.tables["Graph data"]
                self.assertTrue(np.isnan(table.loc[2, "Lower"]) and table.loc[2, "Estimate"] == 30)
        frame.loc[0, "Control [N]"] = 16
        first, _ = _whiskers(self.graph(frame, **{"Summary error": "SEM"}).figure.axes[0])
        np.testing.assert_allclose(first[0][1:], (9.5, 10.5), atol=1e-10)

    def test_entered_sem_and_both_asymmetric_forms(self):
        frame = _csv(A2)
        axis, = self.graph(frame, names=["A [Center]", "A [Minus]", "A [Plus]"],
                           **{"Summary error": "Distances from estimate (minus/plus)"}).figure.axes
        whiskers, = _whiskers(axis)
        np.testing.assert_allclose([pair[1:] for pair in whiskers], [(3, 7), (5, 7)], atol=1e-10)
        np.testing.assert_allclose([patch.get_height() for patch in axis.patches], [4, 5, 6], atol=1e-10)
        axis, = self.graph(frame, names=["B [Mean]", "B [Lower]", "B [Upper]"], **{
            "Summary error": "Limits on axis (lower/upper)", "Graph style": "Center and interval"}).figure.axes
        whiskers, = _whiskers(axis)
        np.testing.assert_allclose([pair[1:] for pair in whiskers], [(6, 13), (9, 9)], atol=1e-10)
        np.testing.assert_allclose(axis.collections[0].get_offsets()[:, 1], [8, 9, 10], atol=1e-10)
        with self.assertRaisesRegex(ValueError, r"A has no \[Lower\] and \[Upper\]") as raised:
            self.graph(frame, **{"Summary error": "Limits on axis (lower/upper)"})
        self.assertEqual(raised.exception.field, "Summary error")
        frame.loc[0, "B [Lower]"] = 9
        with self.assertRaisesRegex(ValueError, "First, B: the limits 9 and 13 must contain the estimate 8"):
            self.graph(frame, names=["B [Mean]", "B [Lower]", "B [Upper]"],
                       **{"Summary error": "Limits on axis (lower/upper)"})
        direct = pd.DataFrame({"C [Mean]": [12.], "C [SEM]": [.75]})
        axis, = self.graph(direct, **{"Summary error": "SEM"}).figure.axes
        whiskers, = _whiskers(axis)
        np.testing.assert_allclose(whiskers[0][1:], (11.25, 12.75), atol=1e-10)
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ["C"])
        self.assertIsNone(axis.get_legend())

    def test_summary_values_are_validated_by_row_series_and_field(self):
        base = {"Row title": ["R1", "R2"], "S [Mean]": [5., 6.], "S [SD]": [1., 1.], "S [N]": [4., 9.]}
        cases = [
            ("S [SD]", ["x", 1.], "SD", 'R1, S: "S \\[SD\\]" must be a finite number'),
            ("S [SD]", [np.inf, 1.], "SD", 'R1, S: "S \\[SD\\]" must be a finite number'),
            ("S [SD]", [1., -1.], "SD", 'R2, S: "S \\[SD\\]" must be zero or positive'),
            ("S [N]", [4., 2.5], "SEM", 'R2, S: "S \\[N\\]" must be a whole number of at least 2'),
            ("S [N]", [0., 9.], "SEM", 'R1, S: "S \\[N\\]" must be a whole number of at least 2'),
            ("S [Mean]", [1e308, 6.], "SD", "R1, S: the interval exceeds the numeric range"),
        ]
        for column, values, error, message in cases:
            with self.subTest(column=column, values=values):
                frame = pd.DataFrame({**base, column: values})
                if column == "S [Mean]":
                    frame["S [SD]"] = [1e308, 1.]
                with self.assertRaisesRegex(ValueError, message) as raised:
                    self.graph(frame, **{"Summary error": error})
                self.assertEqual(raised.exception.field, "Variables")
        zero = self.graph(pd.DataFrame({**base, "S [SD]": [0., None]}), **{"Summary error": "SD"})
        whiskers, = _whiskers(zero.figure.axes[0])
        self.assertEqual(whiskers, [(0., 5., 5.)])  # Zero is a valid zero-width error.
        empty_n = self.graph(pd.DataFrame({**base, "S [N]": [4., None]}), **{"Summary error": "SEM"})
        whiskers, = _whiskers(empty_n.figure.axes[0])
        self.assertEqual(len(whiskers), 1)
        np.testing.assert_allclose([patch.get_height() for patch in empty_n.figure.axes[0].patches], [5, 6])
        without_n = pd.DataFrame({key: value for key, value in base.items() if key != "S [N]"})
        with self.assertRaisesRegex(ValueError, r"S has no \[SEM\] subcolumn or \[SD\] and \[N\]") as raised:
            self.graph(without_n, **{"Summary error": "SEM"})
        self.assertEqual(raised.exception.field, "Summary error")
        with self.assertRaisesRegex(ValueError, r'S needs "S \[N\]"'):
            self.graph(pd.DataFrame(base), names=["S [Mean]", "S [SD]"], **{"Summary error": "SEM",
                                                                         "SEM source": "SD / √N"})

    def test_series_are_resolved_from_exact_suffixes(self):
        frame = pd.DataFrame({"Row title": ["A", "B"], "North [Mean]": [4., 5.], "North [SEM] notes": [1., 1.],
                              "Control [Mean]": [1., 2.], "Control [SD]": [.5, .5],
                              "Control [Mean] (2)": [3., 4.], "Control [SD] (2)": [1., 1.]})
        with self.assertRaisesRegex(ValueError, '"North \\[SEM\\] notes" is not a summary subcolumn'):
            self.graph(frame)
        with self.assertRaisesRegex(ValueError, r"North has no \[SEM\]"):
            self.graph(frame, names=["North [Mean]"], **{"Summary error": "SEM"})
        names = ["Control [SD] (2)", "Control [Mean]", "Control [SD]", "Control [Mean] (2)"]
        result = self.graph(frame, names=names, **{"Summary error": "SD"})
        axis, = result.figure.axes
        self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()], ["Control", "Control (2)"])
        first, second = _whiskers(axis)
        np.testing.assert_allclose([pair[1:] for pair in second], [(2, 4), (3, 5)])
        keys = [series.key for series in graph_series(axis) if series.kind == "bar"]
        self.assertEqual(len(set(keys)), 2)
        with self.assertRaisesRegex(ValueError, r'Control needs "Control \[SD\]"'):
            self.graph(frame, names=["Control [Mean]"], **{"Summary error": "SD"})
        ambiguous = pd.DataFrame({"X [Mean]": [1.], "X [Center]": [1.]})
        with self.assertRaisesRegex(ValueError, 'X: "X \\[Mean\\]" and "X \\[Center\\]" both provide'):
            self.graph(ambiguous)
        roles = pd.DataFrame({"Day": ["1"], "Dose [Mean]": [2.], "Dose [SD]": [1.], "Other [Mean]": [3.]})
        roles.attrs["worksheet_roles"] = {"x": [], "y": [["Dose [Mean]", "Dose [SD]"], ["Other [Mean]"]]}
        table = category_graph(roles, {"Variables": list(roles)[1:], **SUMMARIES, "Summary error": "None"},
                               grouped=True).tables["Graph data"]
        self.assertEqual(table["Group"].tolist(), ["Dose", "Other"])
        self.assertEqual(table["Row"].tolist(), ["1", "1"])

    def test_raw_only_options_are_rejected_for_summaries_and_old_recipes_stay_raw(self):
        frame = _csv(A1)
        for options, field in [({"Graph style": "Individual points"}, "Graph style"),
                               ({"Graph style": "Floating range"}, "Graph style"),
                               ({"Overlay observations": True}, "Overlay observations"),
                               ({"Center": "Median"}, "Center"),
                               ({"Interval": "SD"}, "Interval")]:
            with self.subTest(options=options), self.assertRaises(ValueError) as raised:
                self.graph(frame, **options)
            self.assertEqual(raised.exception.field, field)
        with self.assertRaisesRegex(ValueError, "raw replicate"):
            category_graph(frame, {"Variables": list(frame)[1:]}, grouped=True)
        replicates = pd.DataFrame({"A [1]": [1.], "A [2]": [2.]})
        with self.assertRaisesRegex(ValueError, "is a raw replicate"):
            self.graph(replicates)
        self.assertEqual(GROUPED_OPTIONS["Input"][0], "Raw replicates")

    def test_old_grouped_recipes_keep_their_geometry(self):
        frame = pd.DataFrame({"Row title": ["Week 1", "Week 2", "Week 3", None],
                              "Control [1]": [4.1, 4.7, None, None], "Control [2]": [4.4, None, 5.5, None],
                              "Treatment [1]": [5.6, 7.1, 8.2, None], "Treatment [2]": [5.9, 7.6, 8.7, None]})
        # Recorded from release 0.23.0 before the Input and stacked options existed.
        axis, = category_graph(frame, {"Variables": list(frame), "Graph style": "Bars", "Interval": "SEM"},
                               grouped=True).figure.axes
        np.testing.assert_allclose([(p.get_x(), p.get_width(), p.get_height()) for p in axis.patches][:2],
                                   [(-.3572, .3344, 4.25), (.6428, .3344, 4.7)], atol=1e-10)
        axis, = category_graph(frame, {"Variables": list(frame), "Graph style": "Floating range",
                                       "Placement of groups": "Superimposed", "Overlay observations": True},
                               grouped=True).figure.axes
        self.assertEqual([p.get_x() for p in axis.patches], [-.28, .72, 1.72] * 2)
        self.assertEqual([len(points.get_offsets()) for points in axis.collections], [4, 6])


B1 = """Row title,A,B,C,D
North,2,-3,5,-1
South,-2,4,,1
East,0,0,0,0
"""
B2 = """Row title,A [1],A [2],B [1],B [2],C [1],C [2]
North,1,3,4,8,2,2
South,3,,0,0,7,
Zero,0,0,0,0,0,0
Empty,,,,,,
"""


def _segments(axis):
    """Map (center x, series) to (bottom, top) for each stacked rectangle."""
    segments = {}
    for container in axis.containers:
        for patch in container.patches:
            center = round(patch.get_x() + patch.get_width() / 2, 10)
            segments[center, container.get_label()] = (patch.get_y(), patch.get_y() + patch.get_height())
    return segments


class GroupedStackTests(unittest.TestCase):
    def test_stacks_keep_positive_and_negative_totals_apart(self):
        frame = _csv(B1)
        result = category_graph(frame, {"Variables": list(frame)[1:], "Placement of groups": "Stacked"}, grouped=True)
        axis, = result.figure.axes
        segments = _segments(axis)
        self.assertEqual(segments, {
            (0, "A"): (0, 2), (0, "B"): (0, -3), (0, "C"): (2, 7), (0, "D"): (-3, -4),
            (1, "A"): (0, -2), (1, "B"): (0, 4), (1, "D"): (4, 5),
            (2, "A"): (0, 0), (2, "B"): (0, 0), (2, "C"): (0, 0), (2, "D"): (0, 0),
        })
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ["North", "South", "East"])
        self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()], list("ABCD"))
        self.assertFalse(_whiskers(axis))
        with self.assertRaisesRegex(ValueError, "North, B: 100% stacked bars need values of zero or more") as raised:
            category_graph(frame, {"Variables": list(frame)[1:], "Placement of groups": "100% stacked"}, grouped=True)
        self.assertEqual(raised.exception.field, "Placement of groups")

    def test_percent_stacks_normalize_each_row_center(self):
        frame = _csv(B2)
        options = {"Variables": list(frame)[1:], "Placement of groups": "100% stacked", "Center": "Mean"}
        result = category_graph(frame, options, grouped=True)
        axis, = result.figure.axes
        table = result.tables["Graph data"].set_index(["Row", "Group"])
        np.testing.assert_allclose(table.loc["North", "Mean"], [2, 6, 2], atol=1e-10)
        np.testing.assert_allclose(table.loc["North", "Percent"], [20, 60, 20], atol=1e-10)
        np.testing.assert_allclose(table.loc["North", "Bottom"], [0, 20, 80], atol=1e-10)
        np.testing.assert_allclose(table.loc["South", "Mean"], [3, 0, 7], atol=1e-10)
        np.testing.assert_allclose(table.loc["South", "Percent"], [30, 0, 70], atol=1e-10)
        segments = _segments(axis)
        self.assertEqual(sorted(x for x, _ in segments), [0] * 3 + [1] * 3)
        np.testing.assert_allclose([segments[1, name][1] - segments[1, name][0] for name in "ABC"], [30, 0, 70])
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ["North", "South", "Zero", "Empty"])
        self.assertEqual(axis.get_ylim(), (0, 100))
        self.assertIn("%", axis.get_ylabel())
        single = category_graph(frame.iloc[:1], options, grouped=True).figure.axes[0]
        self.assertEqual({round(p.get_x() + p.get_width() / 2, 10) for p in single.patches}, {0})
        self.assertEqual(len(single.patches), 3)
        self.assertEqual([label.get_text() for label in single.get_xticklabels()], ["North"])
        frame.loc[0, "A [2]"] = 7
        table = category_graph(frame, options, grouped=True).tables["Graph data"].set_index(["Row", "Group"])
        np.testing.assert_allclose(table.loc["North", "Mean"], [4, 6, 2], atol=1e-10)
        np.testing.assert_allclose(table.loc["North", "Percent"], [100 / 3, 50, 100 / 6], atol=1e-10)
        self.assertAlmostEqual(table.loc["North", "Percent"].sum(), 100, delta=1e-10)
        for values, expected in [([1e308, 1e308], [50, 50]), ([1e307, 2e307], [100 / 3, 200 / 3])]:
            huge = pd.DataFrame({"A [Mean]": [values[0]], "B [Mean]": [values[1]]})
            table = category_graph(huge, {"Variables": list(huge), **SUMMARIES, "Placement of groups": "100% stacked"},
                                   grouped=True).tables["Graph data"]
            np.testing.assert_allclose(table["Percent"], expected, atol=1e-10)

    def test_summary_detection_and_out_of_range_plot(self):
        frame = pd.DataFrame({"Row title": [1], "A [Mean]": [0.], "A [Lower]": [-1e308], "A [Upper]": [1e308]})
        self.assertEqual(default_grouped_input(frame), SUMMARIES["Input"])
        with self.assertRaisesRegex(ValueError, "interval exceeds the numeric range"):
            category_graph(frame, {"Variables": list(frame)[1:], **SUMMARIES, "Summary error": "Limits on axis (lower/upper)"},
                           grouped=True)
        signed = pd.DataFrame({"A": [-1e308], "B": [1e308]})
        with self.assertRaisesRegex(ValueError, "stacked totals exceed the numeric range"):
            category_graph(signed, {"Variables": list(signed), "Placement of groups": "Stacked"}, grouped=True)

    def test_percent_stacks_explain_rows_without_a_total(self):
        frame = pd.DataFrame({"Row title": ["Zero", None], "A": [0., None], "B": [0., None]})
        with self.assertRaisesRegex(ValueError, "No row has a positive total"):
            category_graph(frame, {"Variables": ["A", "B"], "Placement of groups": "100% stacked"}, grouped=True)

    def test_summaries_stack_and_legend_survives_gaps_in_first_row(self):
        frame = pd.DataFrame({"Row title": ["R1", "R2"], "A [Mean]": [None, 2.], "A [SD]": [1., 1.],
                              "B [Mean]": [3., 4.], "C [Mean]": [None, 1.]})
        result = category_graph(frame, {"Variables": list(frame)[1:], **SUMMARIES,
                                        "Placement of groups": "Stacked"}, grouped=True)
        axis, = result.figure.axes
        self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()], ["A", "B", "C"])
        segments = _segments(axis)
        self.assertEqual(segments[1, "C"], (6, 7))
        self.assertEqual(segments[0, "B"], (0, 3))
        colors = {container.get_label(): container.patches[0].get_facecolor() for container in axis.containers}
        self.assertEqual(len(set(colors.values())), 3)

    def test_stacks_reject_intervals_points_and_logarithmic_values(self):
        frame, summaries = _csv(B2), _csv(A1)
        base = {"Variables": list(frame)[1:], "Placement of groups": "Stacked"}
        summary_base = {**base, **SUMMARIES, "Variables": list(summaries)[1:]}
        for data, options, field in [(frame, {**base, "Interval": "SD"}, "Interval"),
                                     (frame, {**base, "Graph style": "Individual points"}, "Placement of groups"),
                                     (frame, {**base, "Overlay observations": True}, "Overlay observations"),
                                     (summaries, {**summary_base, "Summary error": "SD"}, "Summary error")]:
            with self.subTest(options=options), self.assertRaises(ValueError) as raised:
                category_graph(data, options, grouped=True)
            self.assertEqual(raised.exception.field, field)
        figure = category_graph(frame, base, grouped=True).figure
        with self.assertRaisesRegex(ValueError, "cannot use a logarithmic scale"):
            apply_style(figure, {"yscale": "log"})
        with self.assertRaisesRegex(ValueError, "cannot use a probability scale"):
            apply_style(figure, {"yscale": "probability %"})
        apply_style(figure, {"title": "Composition", "ylabel": "Amount"})
        self.assertEqual(figure.axes[0].get_title(), "Composition")
        out = BytesIO()
        figure.savefig(out, format="svg")
        self.assertGreaterEqual(out.getvalue().count(b'id="patch_'), 7)
