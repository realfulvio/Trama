from io import BytesIO
from pathlib import Path
import json
import tempfile
import unittest

from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgb
import numpy as np
import pandas as pd

from analisi.data import Dataset, load_workspace, save_project
from analisi.paired_graphs import (AFTER_ONLY, BEFORE_ONLY, COMPLETE, MAX_PAIRS, MAX_TRACES, trajectory_defaults)
from analisi.presentation import apply_style, graph_groups, validated_style
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data"
BEFORE_AFTER = "Before/after"
TRAJECTORIES = "Subject trajectories"
PAIRS = [{"Before": "Before A", "After": "After A", "Title": "A"},
         {"Before": "Before B", "After": "After B", "Title": ""}]


def before_after_data():
    return pd.read_csv(DATA / "paired-before-after.csv")


def trajectory_data():
    return pd.read_csv(DATA / "paired-trajectories.csv")


def segments(result):
    axes = result.figure.axes[0]
    return {collection.get_gid(): [segment.tolist() for segment in collection.get_segments()]
            for collection in axes.collections if isinstance(collection, LineCollection)}


def points(result):
    axes = result.figure.axes[0]
    return [np.asarray(collection.get_offsets()).tolist() for collection in axes.collections
            if not isinstance(collection, LineCollection)]


def traces(result):
    axes = result.figure.axes[0]
    return {line.get_gid(): np.asarray(line.get_ydata(), dtype=float) for line in axes.lines}


class BeforeAfterTests(unittest.TestCase):
    def run_pairs(self, frame=None, **options):
        frame = before_after_data() if frame is None else frame
        return analyse(BEFORE_AFTER, frame, {"Pairs": PAIRS, "Subject": "Subject", **options})

    def test_catalog_entry(self):
        self.assertIn(BEFORE_AFTER, GROUPS["Graphing"])
        self.assertIn(BEFORE_AFTER, GRAPH_METHODS)
        self.assertEqual(list(METHODS[BEFORE_AFTER]), ["Pairs", "Subject", "Orientation", "Show unpaired observations"])

    def test_fixture_changes_and_summary(self):
        result = self.run_pairs()
        table = result.tables["Pairs"]
        complete = table[table["Status"] == COMPLETE]
        self.assertEqual(complete[complete["Pair"] == "A"]["Change"].tolist(), [3., -1., 0.])
        self.assertEqual(complete[complete["Pair"] == "Before B → After B"]["Change"].tolist(), [2., 4., 2.])
        self.assertEqual(table["Source row"].tolist(), [1, 2, 3, 4, 5] * 2)
        self.assertEqual(table["Subject"].tolist(), ["s1", "s2", "s3", "s4", "s5"] * 2)
        self.assertEqual(table["Status"].tolist()[3:5], [BEFORE_ONLY, AFTER_ONLY])
        self.assertEqual(table["Status"].tolist()[8:10], [AFTER_ONLY, BEFORE_ONLY])
        self.assertTrue(table.loc[table["Status"] != COMPLETE, "Change"].isna().all())
        self.assertEqual(table.loc[table["Status"] != COMPLETE, "Plotted"].unique().tolist(), ["No"])
        summary = result.tables["Pair summary"]
        self.assertEqual(summary["Complete pairs"].tolist(), [3, 3])
        self.assertEqual(summary["Before only"].tolist(), [1, 1])
        self.assertEqual(summary["After only"].tolist(), [1, 1])
        np.testing.assert_allclose(summary["Mean change"], [2 / 3, 8 / 3])
        np.testing.assert_allclose(summary["Median change"], [0., 2.])
        self.assertEqual(summary["Before position"].tolist(), [1., 4.])
        self.assertEqual(summary["After position"].tolist(), [2., 5.])

    def test_segment_ends_in_both_orientations(self):
        vertical = segments(self.run_pairs())
        self.assertEqual(vertical["before-after:1"], [[[1, 1], [2, 4]], [[1, 4], [2, 3]], [[1, 2], [2, 2]]])
        self.assertEqual(vertical["before-after:2"], [[[4, 1], [5, 3]], [[4, 2], [5, 6]], [[4, 4], [5, 6]]])
        horizontal = segments(self.run_pairs(Orientation="Horizontal"))
        self.assertEqual(horizontal["before-after:1"], [[[1, 1], [4, 2]], [[4, 1], [3, 2]], [[2, 1], [2, 2]]])
        self.assertEqual(horizontal["before-after:2"], [[[1, 4], [3, 5]], [[2, 4], [6, 5]], [[4, 4], [6, 5]]])
        axes = self.run_pairs(Orientation="Horizontal").figure.axes[0]
        self.assertEqual([text.get_text() for text in axes.get_yticklabels()],
                         ["Before A", "After A", "Before B", "After B"])
        self.assertGreater(axes.get_ylim()[0], axes.get_ylim()[1])  # The first pair is at the top.

    def test_unpaired_observations_are_isolated_points(self):
        hidden = points(self.run_pairs())
        self.assertEqual(len(hidden), 4)
        shown = self.run_pairs(**{"Show unpaired observations": True})
        axes = shown.figure.axes[0]
        hollow = [tuple(p) for c in axes.collections if not isinstance(c, LineCollection)
                  and tuple(c.get_facecolor()[0]) == (1., 1., 1., 1.) for p in np.asarray(c.get_offsets()).tolist()]
        self.assertEqual(len(points(shown)), len(hidden) + 4)
        self.assertEqual(sorted(hollow), [(1., 5.), (2., 7.), (4., 3.), (5., 8.)])
        self.assertEqual(segments(shown), segments(self.run_pairs()))
        table = shown.tables["Pairs"]
        self.assertEqual(table.loc[table["Status"] != COMPLETE, "Plotted"].unique().tolist(), ["Yes"])

    def test_subject_is_a_label_not_a_key(self):
        frame = before_after_data()
        frame["Subject"] = ["s5", "s5", "s1", "s2", "s3"]
        result = self.run_pairs(frame)
        self.assertEqual(segments(result), segments(self.run_pairs()))
        without = analyse(BEFORE_AFTER, before_after_data(), {"Pairs": PAIRS})
        self.assertNotIn("Subject", without.tables["Pairs"])

    def test_excluded_cell_breaks_its_segment(self):
        data = Dataset(before_after_data())
        data.excluded.add((0, 2))  # s1, After A
        result = self.run_pairs(data.frame(mask_excluded=True))
        self.assertEqual(segments(result)["before-after:1"], [[[1, 4], [2, 3]], [[1, 2], [2, 2]]])
        summary = result.tables["Pair summary"]
        self.assertEqual(summary.loc[0, ["Complete pairs", "Before only", "After only"]].tolist(), [2, 2, 1])
        self.assertAlmostEqual(summary.loc[0, "Mean change"], -.5)

    def test_pairs_are_checked(self):
        frame = before_after_data()
        cases = {
            "empty": [],
            "same column": [{"Before": "Before A", "After": "Before A"}],
            "duplicate": [PAIRS[0], {"Before": "Before A", "After": "After A", "Title": "again"}],
            "reversed": [PAIRS[0], {"Before": "After A", "After": "Before A"}],
            "missing": [{"Before": "Before A", "After": "Gone"}],
            "malformed": ["Before A → After A"],
            "too many": [{"Before": "Before A", "After": "After A", "Title": str(i)} for i in range(MAX_PAIRS + 1)],
        }
        for name, pairs in cases.items():
            with self.subTest(name), self.assertRaises(FieldError) as raised:
                analyse(BEFORE_AFTER, frame, {"Pairs": pairs})
            self.assertEqual(raised.exception.field, "Pairs")
        with self.assertRaisesRegex(FieldError, "repeats pair 1"):
            analyse(BEFORE_AFTER, frame, {"Pairs": cases["duplicate"]})
        text = frame.assign(**{"After A": ["1", "x", "2", None, "3"]})
        with self.assertRaisesRegex(FieldError, "text"):
            analyse(BEFORE_AFTER, text, {"Pairs": PAIRS})
        blank = frame.assign(**{"After A": np.nan, "After B": np.nan})
        with self.assertRaisesRegex(FieldError, "No row has both"):
            analyse(BEFORE_AFTER, blank, {"Pairs": PAIRS})
        with self.assertRaises(FieldError) as raised:
            analyse(BEFORE_AFTER, frame, {"Pairs": PAIRS, "Orientation": "Diagonal"})
        self.assertEqual(raised.exception.field, "Orientation")

    def test_titles_ticks_and_inspector_groups(self):
        result = self.run_pairs()
        axes = result.figure.axes[0]
        self.assertEqual([text.get_text() for text in axes.get_xticklabels()],
                         ["Before A", "After A", "Before B", "After B"])
        titles = [child for child in axes.child_axes]
        self.assertEqual(len(titles), 1)
        self.assertEqual([text.get_text() for text in titles[0].get_xticklabels()], ["A"])
        self.assertEqual(list(titles[0].get_xticks()), [1.5])
        groups = graph_groups(axes)
        self.assertEqual([group.name for group in groups], ["A", "Before B → After B"])
        style = validated_style({"groups": {groups[1].key: {"color": "#112233"}}})
        apply_style(result.figure, style)
        recolored = [c for c in axes.collections if isinstance(c, LineCollection)][1]
        self.assertEqual(tuple(recolored.get_color()[0][:3]), to_rgb("#112233"))


class TrajectoryTests(unittest.TestCase):
    def run_traces(self, frame=None, mode="Replicate subcolumns", **options):
        frame = trajectory_data() if frame is None else frame
        names = [name for name in frame.columns if name != "X"]
        return analyse(TRAJECTORIES, frame, {"Input": mode, "X": "X", "Y columns": names, **options})

    def test_catalog_entry(self):
        self.assertIn(TRAJECTORIES, GROUPS["Graphing"])
        self.assertIn(TRAJECTORIES, GRAPH_METHODS)

    def test_fixture_group_means(self):
        result = self.run_traces(**{"Show group mean": True})
        means = result.tables["Group means"]
        cohort_a = means[means["Group"] == "Cohort A"]
        self.assertEqual(cohort_a["X"].tolist(), [0., 1., 2., 2., 3.])
        np.testing.assert_allclose(cohort_a["Mean"], [9.5, 11, 11.5, 13, 13.5])
        self.assertEqual(cohort_a["N"].tolist(), [2, 1, 2, 2, 2])
        self.assertEqual(cohort_a["Source row"].tolist(), [1, 2, 3, 4, 5])
        cohort_b = means[means["Group"] == "Cohort B"]
        self.assertEqual(cohort_b["N"].tolist(), [1, 1, 0, 1, 1])
        self.assertTrue(np.isnan(cohort_b["Mean"].iat[2]))
        drawn = traces(result)
        np.testing.assert_allclose(drawn["trajectory-mean:Cohort A"], [9.5, 11, 11.5, 13, 13.5])
        np.testing.assert_array_equal(np.isnan(drawn["trajectory-mean:Cohort B"]), [False, False, True, False, False])

    def test_gap_in_one_trace_and_duplicate_x_rows(self):
        result = self.run_traces()
        values = result.tables["Subject values"]
        self.assertEqual(list(values.columns), ["Source row", "Subject", "Group", "X", "Y"])
        b = values[values["Subject"] == "Cohort B [1]"]
        self.assertEqual(b["Source row"].tolist(), [1, 2, 4, 5])
        self.assertEqual(b["X"].tolist(), [0., 1., 2., 3.])
        a1 = values[values["Subject"] == "Cohort A [1]"]
        # Both rows with X = 2 stay, in source order, with their own row number.
        self.assertEqual(a1.loc[a1["X"] == 2, ["Source row", "Y"]].values.tolist(), [[3, 12.], [4, 14.]])
        self.assertEqual(values["Subject"].tolist(), ["Cohort A [1]"] * 5 + ["Cohort A [2]"] * 4 + ["Cohort B [1]"] * 4)
        drawn = traces(result)
        np.testing.assert_array_equal(np.isnan(drawn["trajectory:Cohort B [1]"]), [False, False, True, False, False])
        np.testing.assert_array_equal(np.isnan(drawn["trajectory:Cohort A [2]"]), [False, True, False, False, False])
        line = next(l for l in result.figure.axes[0].lines if l.get_gid() == "trajectory:Cohort A [1]")
        np.testing.assert_array_equal(line.get_xdata(), [0, 1, 2, 2, 3])

    def test_excluded_y_breaks_the_trace_and_the_mean(self):
        data = Dataset(trajectory_data())
        data.excluded.add((3, 1))  # Cohort A [1] on the second row with X = 2
        result = self.run_traces(data.frame(mask_excluded=True), **{"Show group mean": True})
        drawn = traces(result)
        np.testing.assert_array_equal(np.isnan(drawn["trajectory:Cohort A [1]"]), [False, False, False, True, False])
        means = result.tables["Group means"]
        cohort_a = means[means["Group"] == "Cohort A"]
        self.assertEqual(cohort_a["N"].tolist(), [2, 1, 2, 1, 2])
        np.testing.assert_allclose(cohort_a["Mean"], [9.5, 11, 11.5, 12, 13.5])

    def test_missing_x_breaks_every_trace(self):
        data = Dataset(trajectory_data())
        data.excluded.add((1, 0))
        result = self.run_traces(data.frame(mask_excluded=True), **{"Show group mean": True})
        for name, y in traces(result).items():
            self.assertTrue(np.isnan(y[1]), name)
        self.assertNotIn(2, result.tables["Subject values"]["Source row"].tolist())
        self.assertNotIn(2, result.tables["Group means"]["Source row"].tolist())

    def test_separate_columns_match_replicate_coordinates(self):
        replicate = self.run_traces()
        separate = self.run_traces(mode="Separate columns")
        left, right = replicate.tables["Subject values"], separate.tables["Subject values"]
        pd.testing.assert_frame_equal(left.drop(columns="Group"), right.drop(columns="Group"))
        self.assertEqual(right["Group"].unique().tolist(), ["All subjects"])
        colors = {line.get_gid(): line.get_color() for line in replicate.figure.axes[0].lines}
        self.assertEqual(colors["trajectory:Cohort A [1]"], colors["trajectory:Cohort A [2]"])
        self.assertNotEqual(colors["trajectory:Cohort A [1]"], colors["trajectory:Cohort B [1]"])
        colors = {line.get_gid(): line.get_color() for line in separate.figure.axes[0].lines}
        self.assertEqual(len(set(colors.values())), 3)
        legend = replicate.figure.axes[0].get_legend()
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["Cohort A (n = 2)", "Cohort B (n = 1)"])

    def test_line_and_points(self):
        result = self.run_traces(Style="Line and points")
        self.assertTrue(all(line.get_marker() == "o" for line in result.figure.axes[0].lines))
        self.assertTrue(all(line.get_marker() in ("None", None) for line in self.run_traces().figure.axes[0].lines))

    def test_groups_from_worksheet_roles(self):
        frame = pd.DataFrame({"Time": [0., 1., 2.], "a": [1., 2., 3.], "b": [2., 3., 4.], "c": [5., 4., 3.]})
        frame.attrs["worksheet_roles"] = {"x": ["Time"], "y": [["a", "b"], ["c"]]}
        result = analyse(TRAJECTORIES, frame, {"Input": "Replicate subcolumns", "X": "Time", "Y columns": ["c", "a", "b"]})
        values = result.tables["Subject values"]
        self.assertEqual(values.drop_duplicates("Subject")[["Subject", "Group"]].values.tolist(),
                         [["a", "a"], ["b", "a"], ["c", "c"]])
        self.assertEqual(trajectory_defaults(frame), {"Input": "Replicate subcolumns", "X": "Time",
                                                      "Y columns": ["a", "b", "c"]})

    def test_selection_errors(self):
        frame = trajectory_data()
        bad = {
            "empty": {"Y columns": []},
            "x as y": {"Y columns": ["X", "Cohort A [1]"]},
            "repeated": {"Y columns": ["Cohort A [1]", "Cohort A [1]"]},
        }
        for name, options in bad.items():
            with self.subTest(name), self.assertRaises(FieldError) as raised:
                analyse(TRAJECTORIES, frame, {"Input": "Separate columns", "X": "X", **options})
            self.assertEqual(raised.exception.field, "Y columns")
        plain = frame.rename(columns={"Cohort B [1]": "Other"})
        with self.assertRaisesRegex(FieldError, "not a replicate subcolumn"):
            self.run_traces(plain)
        ambiguous = frame.rename(columns={"Cohort B [1]": "Cohort A [1] (2)"})
        with self.assertRaisesRegex(FieldError, "ambiguous"):
            self.run_traces(ambiguous)
        no_x = frame.assign(X=np.nan)
        with self.assertRaises(FieldError) as raised:
            self.run_traces(no_x)
        self.assertEqual(raised.exception.field, "X")
        many = pd.DataFrame({"X": [0., 1.], **{f"S{i}": [1., 2.] for i in range(MAX_TRACES + 1)}})
        with self.assertRaisesRegex(FieldError, str(MAX_TRACES)):
            analyse(TRAJECTORIES, many, {"Input": "Separate columns", "X": "X", "Y columns": list(many.columns[1:])})

    def test_inspector_recolors_a_data_set_and_its_legend(self):
        result = self.run_traces(**{"Show group mean": True})
        axes = result.figure.axes[0]
        groups = graph_groups(axes)
        self.assertEqual([group.name for group in groups], ["Cohort A", "Cohort B"])
        apply_style(result.figure, validated_style({"groups": {groups[0].key: {"color": "#aa0000"}}}))
        colors = {line.get_gid(): to_rgb(line.get_color()) for line in axes.lines}
        for gid in ("trajectory:Cohort A [1]", "trajectory:Cohort A [2]", "trajectory-mean:Cohort A"):
            self.assertEqual(colors[gid], to_rgb("#aa0000"))
        self.assertEqual(to_rgb(axes.get_legend().legend_handles[0].get_color()), to_rgb("#aa0000"))


class PersistenceTests(unittest.TestCase):
    def test_recipes_round_trip_and_export(self):
        before = Dataset(before_after_data(), analyses=[(BEFORE_AFTER, {"Pairs": PAIRS, "Subject": "Subject",
                                                                        "Orientation": "Horizontal",
                                                                        "Show unpaired observations": True})])
        curves = Dataset(trajectory_data(), analyses=[(TRAJECTORIES, {"Input": "Replicate subcolumns", "X": "X",
                                                                     "Y columns": ["Cohort A [1]", "Cohort A [2]",
                                                                                   "Cohort B [1]"],
                                                                     "Show group mean": True})])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paired.alab"
            save_project(path, {"Pairs": before, "Curves": curves})
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["tables"][0]["analyses"][0][1]["Pairs"], PAIRS)
            tables, _ = load_workspace(path)
        for title, dataset in tables.items():
            method, options = dataset.analyses[0]
            result = analyse(method, dataset.frame(mask_excluded=True), options)
            for kind in ("svg", "png"):
                buffer = BytesIO()
                result.figure.savefig(buffer, format=kind)
                self.assertGreater(len(buffer.getvalue()), 1000, (title, kind))
        self.assertEqual(tables["Pairs"].analyses[0][1]["Pairs"], PAIRS)


if __name__ == "__main__":
    unittest.main()
