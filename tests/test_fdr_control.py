"""False-discovery control: family adjustment, declared families, and the result sheets.

The frozen numbers in tests/data/fdr_control/families.json are synthetic. They were
cross-checked with an independent decimal procedure; this file does not import that oracle.
"""
import json
import math
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

from analisi import operations
from analisi.fdr_control import (
    BH, BKY, BY, EMPTY_REASON, ERR_CELLS, ERR_FAMILIES, ERR_FAMILY_COUNT,
    ERR_LEVEL, ERR_METHOD, ERR_OVERLAP, ERR_P_COUNT, ERR_PLOT,
    ERR_PLOT_FAMILIES, ERR_SCOPE, FAMILY_COLUMNS, FDR_METHOD, LEVEL,
    MAX_CELLS, MAX_FAMILIES, MAX_PLOT_FAMILIES, METHOD, P_COLUMNS, PLOT, POOLED, SCOPE,
    SCOPE_EACH, SCOPE_POOL, STATUS_MISSING_FAMILY, STATUS_MISSING_P, STATUS_USED,
    adjust_family, analysis, format_fdr_error, validate_request,
)
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, analyse

FIXTURES = json.loads((Path(__file__).parent / "data" / "fdr_control" / "families.json").read_text())
REL = 2e-12
ABS = 2e-14


def _options(**changes):
    base = {P_COLUMNS: ["P"]}
    base.update(changes)
    return base


def _close(actual, expected):
    actual = list(actual)
    expected = list(expected)
    if len(actual) != len(expected):
        return False
    return all(math.isclose(float(left), float(right), rel_tol=REL, abs_tol=ABS)
               for left, right in zip(actual, expected))


def _settings(result):
    table = result.tables["Settings"]
    return dict(zip(table["Setting"], table["Value"], strict=True))


class FamilyMathTests(unittest.TestCase):
    def test_frozen_families_match_within_the_verifier_tolerance(self):
        self.assertEqual(len(FIXTURES), 27)
        for row in FIXTURES:
            with self.subTest(name=row["name"]):
                result = adjust_family(row["p"], row["method"], row["q"])
                expected = row["expected"]
                self.assertTrue(_close(result["adjusted"], expected["adjusted"]), row["name"])
                self.assertEqual(result["rejected"], expected["rejected"])
                self.assertEqual(result["r1"], expected["r1"])
                self.assertEqual(result["m0"], expected["m0"])
                self.assertTrue(_close(result["stage_alphas"], expected["stage_alphas"]))

    def test_boundary_inclusion_rejects_both_points(self):
        result = adjust_family([0.025, 0.05], "bh", 0.05)
        self.assertEqual(result["rejected"], [True, True])
        self.assertTrue(_close(result["adjusted"], [0.05, 0.05]))

    def test_tied_values_keep_input_order_and_share_the_decision(self):
        result = adjust_family([0.04, 0.01, 0.04], "bh", 0.05)
        self.assertEqual(result["order"], [1, 0, 2])
        self.assertEqual(result["adjusted"][0], result["adjusted"][2])
        self.assertEqual(result["rejected"][0], result["rejected"][2])

    def test_a_later_rank_can_make_an_earlier_point_a_discovery(self):
        # Rank 1 fails its own threshold. Rank 3 passes, so step-up rejects every rank through 3.
        result = adjust_family([0.03, 0.04, 0.045], "bh", 0.05)
        self.assertEqual(result["rejected"], [True, True, True])
        self.assertGreater(0.03, result["stage_alphas"][-1] * 1 / 3)

    def test_adaptive_bky_reports_the_stage_one_estimate(self):
        result = adjust_family([0.001, 0.003, 0.01, 0.06, 0.2, 0.8], "bky", 0.05)
        self.assertEqual(result["r1"], 3)
        self.assertEqual(result["m0"], 3)
        self.assertEqual(sum(result["rejected"]), 4)
        self.assertEqual(len(result["stage_alphas"]), 2)

    def test_bky_does_not_divide_when_stage_one_rejects_everything(self):
        result = adjust_family([0.001, 0.002, 0.003, 0.004], "bky", 0.05)
        self.assertEqual(result["r1"], 4)
        self.assertEqual(result["m0"], 0)
        self.assertEqual(result["rejected"], [True, True, True, True])
        self.assertTrue(all(value > 0 for value in result["adjusted"]))
        self.assertEqual(len(result["stage_alphas"]), 1)

    def test_bky_stops_when_stage_one_rejects_nothing(self):
        result = adjust_family([0.4, 0.6, 1.0], "bky", 0.05)
        self.assertEqual((result["r1"], result["m0"]), (0, 3))
        self.assertEqual(result["rejected"], [False, False, False])
        self.assertEqual(len(result["stage_alphas"]), 1)

    def test_bh_and_by_leave_the_adaptive_estimate_empty(self):
        for method in ("bh", "by"):
            result = adjust_family([0.01, 0.2], method, 0.05)
            self.assertIsNone(result["r1"])
            self.assertIsNone(result["m0"])
            self.assertEqual(len(result["stage_alphas"]), 1)

    def test_rejects_an_unknown_method_a_bad_level_and_a_bad_family(self):
        with self.assertRaisesRegex(ValueError, "Unknown FDR method"):
            adjust_family([0.1], "holm", 0.05)
        for level in (0, 1, True, float("nan"), float("inf"), "0.05"):
            with self.assertRaisesRegex(ValueError, "fraction"):
                adjust_family([0.1], "bh", level)
        for values in ((), [True], [1.1], [float("inf")], ["no"]):
            with self.assertRaisesRegex(ValueError, "Invalid p family"):
                adjust_family(values, "bh", 0.05)


class ResultTests(unittest.TestCase):
    def test_duplicate_index_uses_the_original_table_position(self):
        frame = pd.DataFrame({"P": [0.01, 0.03, 0.04, 0.2, None], "G": ["a", "a", "b", "b", "b"]},
                             index=[99, 99, 5, 5, 5])
        original = frame.copy(deep=True)
        result = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"], SCOPE: SCOPE_EACH, FDR_METHOD: BH}))
        pd.testing.assert_frame_equal(frame, original)
        table = result.tables["FDR results"]
        self.assertEqual(list(table), [
            "Source row", "Variable", "G", "p", "Adjusted p", "Discovery", "Status", "Rank", "Threshold"])
        self.assertEqual(table["Source row"].tolist(), [1, 2, 3, 4, 5])
        self.assertTrue(_close(table["Adjusted p"].iloc[:4], [0.02, 0.03, 0.08, 0.2]))
        self.assertEqual(table["Discovery"].iloc[:4].tolist(), [True, True, False, False])
        self.assertEqual(table["Status"].iloc[4], STATUS_MISSING_P)
        self.assertTrue(pd.isna(table["Adjusted p"].iloc[4]))
        self.assertTrue(pd.isna(table["Discovery"].iloc[4]))
        self.assertTrue(pd.isna(table["Rank"].iloc[4]))
        self.assertIsNone(result.figure)
        self.assertNotIn("Source label", table.columns)
        families = result.tables["FDR families"]
        self.assertEqual(families["m"].tolist(), [2, 2])
        self.assertTrue(families["R1"].isna().all())
        self.assertTrue(pd.isna(families["Stage 2"]).all())

    def test_defaults_are_each_column_benjamini_hochberg_five_percent_and_no_plot(self):
        result = analysis(pd.DataFrame({"P": [0.01, 0.2]}), {P_COLUMNS: ["P"]})
        settings = _settings(result)
        self.assertEqual(settings["FDR method"], BH)
        self.assertEqual(settings["Family scope"], SCOPE_EACH)
        self.assertEqual(settings["Desired FDR (%)"], 5.0)
        self.assertEqual(settings["q"], 0.05)
        self.assertEqual(settings["Family columns"], "(none)")
        self.assertIs(settings["Show diagnostic plot"], False)
        self.assertEqual(settings["Comparison"], "inclusive (<=)")
        self.assertIn("does not test", settings["Dependence"])
        self.assertIn("not q-values", settings["Requested level"])
        self.assertNotIn("BKY m0", settings)
        self.assertEqual(result.tables["FDR families"]["Family"].tolist(), ["All rows · P"])
        self.assertIsNone(result.figure)

    def test_group_column_and_source_order_puts_missing_families_last(self):
        frame = pd.DataFrame({
            "G": ["b", "a", None],
            "P_A": [0.1, 0.3, 0.4],
            "P_B": [0.2, None, 0.5],
        })
        table = analysis(frame, _options(**{
            P_COLUMNS: ["P_B", "P_A"], FAMILY_COLUMNS: ["G"], SCOPE: SCOPE_EACH,
        })).tables["FDR results"]
        self.assertEqual(table["Source row"].tolist(), [1, 1, 2, 2, 3, 3])
        self.assertEqual(table["Variable"].tolist(), ["P_B", "P_A", "P_B", "P_A", "P_B", "P_A"])
        self.assertEqual(table["Status"].tolist(), [
            STATUS_USED, STATUS_USED, STATUS_MISSING_P, STATUS_USED,
            STATUS_MISSING_FAMILY, STATUS_MISSING_FAMILY])
        self.assertTrue(all(pd.isna(value) for value in table["G"].tolist()[4:]))

    def test_pool_combines_columns_and_each_column_keeps_them_separate(self):
        frame = pd.DataFrame({"P_A": [0.01, 0.04], "P_B": [0.02, 0.03]})
        pooled = analysis(frame, _options(**{P_COLUMNS: ["P_A", "P_B"], SCOPE: SCOPE_POOL}))
        separate = analysis(frame, _options(**{P_COLUMNS: ["P_A", "P_B"], SCOPE: SCOPE_EACH}))
        pooled_families = pooled.tables["FDR families"]
        separate_families = separate.tables["FDR families"]
        self.assertEqual(pooled_families["m"].tolist(), [4])
        self.assertEqual(pooled_families["Variable"].tolist(), [POOLED])
        self.assertEqual(pooled_families["Family"].tolist(), ["All rows"])
        self.assertEqual(separate_families["m"].tolist(), [2, 2])
        self.assertEqual(separate_families["Family"].tolist(), ["All rows · P_A", "All rows · P_B"])

    def test_integer_and_text_levels_stay_distinct_and_literal_na_is_a_level(self):
        frame = pd.DataFrame({"P": [0.01, 0.02, 0.03, 0.04], "G": [1, "1", "NA", "  "]})
        table = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"]})).tables["FDR families"]
        self.assertEqual(table["Family"].tolist()[:3], ["G=1 · P", "G='1' · P", "G='NA' · P"])
        results = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"]})).tables["FDR results"]
        self.assertEqual(results["Status"].iloc[3], STATUS_MISSING_FAMILY)
        self.assertEqual(results["G"].tolist()[:3], [1, "1", "NA"])

    def test_missing_family_wins_over_missing_p_but_invalid_p_is_rejected_first(self):
        frame = pd.DataFrame({"P": [None, "  "], "G": [None, " "]})
        table = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"]})).tables["FDR results"]
        self.assertEqual(table["Status"].tolist(), [STATUS_MISSING_FAMILY, STATUS_MISSING_FAMILY])
        settings = _settings(analysis(frame, _options(**{FAMILY_COLUMNS: ["G"]})))
        self.assertEqual(settings["Ignored missing family"], 2)
        self.assertEqual(settings["Ignored missing p"], 0)
        invalid = pd.DataFrame({"P": ["abc", True, float("inf"), 1.1, -0.01], "G": [None, None, None, None, None]})
        for value in invalid["P"]:
            with self.assertRaises(FieldError) as caught:
                analysis(pd.DataFrame({"P": [value], "G": [None]}), _options(**{FAMILY_COLUMNS: ["G"]}))
            self.assertEqual(caught.exception.field, P_COLUMNS)
            self.assertIn("not a finite p", str(caught.exception))

    def test_zero_and_one_are_usable_p_values(self):
        table = analysis(pd.DataFrame({"P": [0, 1, np.int64(0), np.float64(1.0)]}), _options()).tables["FDR results"]
        self.assertEqual(table["Status"].tolist(), [STATUS_USED] * 4)
        self.assertEqual(table["p"].tolist(), [0.0, 1.0, 0.0, 1.0])

    def test_empty_family_does_not_call_the_procedure(self):
        frame = pd.DataFrame({"P": [0.01, None], "G": ["a", "b"]})
        with patch("analisi.fdr_control.adjust_family", wraps=adjust_family) as called:
            result = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"], PLOT: True}))
        self.assertEqual(called.call_count, 1)
        self.assertEqual(list(called.call_args.args[0]), [0.01])
        families = result.tables["FDR families"]
        self.assertEqual(families["Reason"].tolist(), ["", EMPTY_REASON])
        self.assertEqual(families["m"].tolist(), [1, 0])
        self.assertIsNotNone(result.figure)

    def test_no_used_p_returns_statuses_and_no_figure(self):
        frame = pd.DataFrame({"P": [None, " "], "G": ["a", None]})
        with patch("analisi.fdr_control.adjust_family") as called:
            result = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"], PLOT: True}))
        called.assert_not_called()
        self.assertIsNone(result.figure)
        table = result.tables["FDR results"]
        self.assertEqual(table["Status"].tolist(), [STATUS_MISSING_P, STATUS_MISSING_FAMILY])
        self.assertEqual(_settings(result)["Figure"], "No used p values, so there is no diagnostic plot.")
        self.assertEqual(result.tables["FDR families"]["Reason"].iloc[0], EMPTY_REASON)

    def test_bky_sheet_records_both_stages_and_the_m0_note(self):
        frame = pd.DataFrame({"P": [0.001, 0.003, 0.01, 0.06, 0.2, 0.8]})
        result = analysis(frame, _options(**{FDR_METHOD: BKY, LEVEL: 10}))
        row = result.tables["FDR families"].iloc[0]
        self.assertEqual(row["q"], 0.1)
        self.assertEqual(int(row["R1"]), adjust_family(frame["P"].tolist(), "bky", 0.1)["r1"])
        self.assertEqual(int(row["m0"]), adjust_family(frame["P"].tolist(), "bky", 0.1)["m0"])
        self.assertEqual(len(result.tables["FDR families"]["Stage 1"].dropna()), 1)
        settings = _settings(result)
        self.assertIn("stage-1 estimate", settings["BKY m0"])
        self.assertEqual(settings["q"], 0.1)
        by = analysis(frame, _options(**{FDR_METHOD: BY}))
        self.assertNotIn("BKY m0", _settings(by))
        self.assertTrue(by.tables["FDR families"]["R1"].isna().all())

    def test_first_appearance_order_is_not_alphabetical(self):
        frame = pd.DataFrame({"P": [0.2, 0.01, 0.3], "G": ["c", "a", "b"]})
        labels = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"]})).tables["FDR families"]["Family"]
        self.assertEqual(labels.tolist(), ["G='c' · P", "G='a' · P", "G='b' · P"])

    def test_limits_name_the_field_and_do_not_call_the_procedure(self):
        wide = pd.DataFrame({f"P{i}": [0.01] for i in range(25)})
        with self.assertRaises(FieldError) as caught:
            analysis(wide, {P_COLUMNS: list(wide.columns)})
        self.assertEqual((caught.exception.field, str(caught.exception)), (P_COLUMNS, ERR_P_COUNT))
        families = [f"G{i}" for i in range(5)]
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1]}), _options(**{FAMILY_COLUMNS: families}))
        self.assertEqual(str(caught.exception), ERR_FAMILY_COUNT)
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1]}), _options(**{FAMILY_COLUMNS: ["P"]}))
        self.assertEqual((caught.exception.field, str(caught.exception)), (FAMILY_COLUMNS, ERR_OVERLAP))
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1], "Status": ["a"]}), _options(**{FAMILY_COLUMNS: ["Status"]}))
        self.assertEqual(caught.exception.field, FAMILY_COLUMNS)
        self.assertIn("reserved", str(caught.exception))
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1]}), _options(**{SCOPE: "Together"}))
        self.assertEqual(str(caught.exception), ERR_SCOPE)
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1]}), _options(**{FDR_METHOD: "Holm"}))
        self.assertEqual(str(caught.exception), ERR_METHOD)
        for level in (0, 100, float("nan"), True, "5"):
            with self.assertRaises(FieldError) as caught:
                analysis(pd.DataFrame({"P": [0.1]}), _options(**{LEVEL: level}))
            self.assertEqual((caught.exception.field, str(caught.exception)), (LEVEL, ERR_LEVEL))
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1]}), _options(**{PLOT: "yes"}))
        self.assertEqual((caught.exception.field, str(caught.exception)), (PLOT, ERR_PLOT))
        with self.assertRaises(FieldError) as caught:
            analysis(pd.DataFrame({"P": [0.1]}), _options(**{P_COLUMNS: ["Q"]}))
        self.assertEqual(caught.exception.field, P_COLUMNS)
        self.assertIn("not in the table", str(caught.exception))
        duplicate = pd.DataFrame([[0.1, 0.2]], columns=["P", "P"])
        with self.assertRaises(FieldError) as caught:
            analysis(duplicate, _options())
        self.assertIn("more than once", str(caught.exception))

        too_many = pd.DataFrame({"P": np.full(MAX_CELLS + 1, 0.01)})
        many_families = pd.DataFrame({"P": np.full(MAX_FAMILIES + 1, 0.01),
                                      "G": [f"g{i}" for i in range(MAX_FAMILIES + 1)]})
        plotted = pd.DataFrame({"P": np.full(MAX_PLOT_FAMILIES + 1, 0.01),
                                "G": [f"g{i}" for i in range(MAX_PLOT_FAMILIES + 1)]})
        with patch("analisi.fdr_control.adjust_family") as called:
            with self.assertRaises(FieldError) as cells:
                analysis(too_many, _options())
            with self.assertRaises(FieldError) as groups:
                analysis(many_families, _options(**{FAMILY_COLUMNS: ["G"]}))
            with self.assertRaises(FieldError) as plots:
                analysis(plotted, _options(**{FAMILY_COLUMNS: ["G"], PLOT: True}))
        called.assert_not_called()
        self.assertEqual((cells.exception.field, str(cells.exception)), (P_COLUMNS, ERR_CELLS))
        self.assertEqual((groups.exception.field, str(groups.exception)), (FAMILY_COLUMNS, ERR_FAMILIES))
        self.assertEqual((plots.exception.field, str(plots.exception)), (PLOT, ERR_PLOT_FAMILIES))
        self.assertIsNone(validate_request(pd.DataFrame({"P": [0.01, 0.2]}), _options()))

    def test_two_hundred_thousand_values_stay_one_family(self):
        frame = pd.DataFrame({"P": np.full(MAX_CELLS, 0.04)})
        families = analysis(frame, _options()).tables["FDR families"]
        self.assertEqual(int(families["m"].iloc[0]), MAX_CELLS)
        self.assertGreater(int(families["Discoveries"].iloc[0]), 0)

    def test_legacy_holm_adjustment_is_unchanged(self):
        frame = pd.DataFrame({"p": [0.01, 0.03, 0.2]})
        original = frame.copy(deep=True)
        result = analyse("Adjust a stack of p values", frame, {"p value": "p", "Correction": "Holm"})
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(list(result.tables), ["Adjusted p values"])
        self.assertIsNone(result.figure)
        pd.testing.assert_frame_equal(result.tables["Adjusted p values"], operations.adjust_p(frame, "p", "holm"))
        self.assertNotIn(METHOD, GRAPH_METHODS)

    def test_english_field_error_uses_the_catalogued_message(self):
        text = format_fdr_error(FieldError(LEVEL, ERR_LEVEL))
        self.assertEqual(text, f"{LEVEL}: {ERR_LEVEL}")
        self.assertIsNone(format_fdr_error(ValueError("other")))
        self.assertIsNone(format_fdr_error(FieldError("Response", ERR_LEVEL)))


class FigureTests(unittest.TestCase):
    def _figure(self, values, **options):
        return analysis(pd.DataFrame({"P": values}), _options(**{PLOT: True, **options})).figure

    def test_markers_encode_the_decision_and_keep_a_zero(self):
        figure = self._figure([0.0, 0.2])
        axis = figure.axes[0]
        self.assertEqual(axis.get_yscale(), "linear")
        self.assertLess(axis.get_ylim()[0], 0)
        labels = {artist.get_gid(): artist for artist in axis.get_children() if artist.get_gid()}
        self.assertEqual(set(labels), {"fdr-threshold-0", "fdr-discovery-0", "fdr-other-0"})
        self.assertEqual(labels["fdr-threshold-0"].get_color(), "#0f6b4c")
        self.assertEqual(labels["fdr-threshold-0"].get_marker(), "none")
        discovered = labels["fdr-discovery-0"].get_offsets()
        self.assertIn(0.0, discovered[:, 1].tolist())
        self.assertEqual(mcolors.to_hex(labels["fdr-discovery-0"].get_facecolor()[0]), "#1f4e79")
        self.assertEqual(mcolors.to_hex(labels["fdr-other-0"].get_edgecolor()[0]), "#9a3412")
        self.assertTrue(all(artist.get_rasterized() is not True for artist in labels.values()))
        buffer = StringIO()
        figure.savefig(buffer, format="svg")
        svg = buffer.getvalue()
        self.assertIn('id="fdr-threshold-0"', svg)
        self.assertIn('id="fdr-discovery-0"', svg)
        self.assertNotIn("<image", svg)

    def test_a_single_point_uses_a_visible_threshold_marker(self):
        figure = self._figure([0.01])
        line = next(artist for artist in figure.axes[0].get_children() if artist.get_gid() == "fdr-threshold-0")
        self.assertEqual(line.get_marker(), "s")
        self.assertEqual(figure.get_layout_engine().__class__.__name__, "ConstrainedLayoutEngine")

    def test_more_than_four_panels_use_three_columns(self):
        frame = pd.DataFrame({"P": [0.01, 0.02, 0.03, 0.04, 0.05], "G": list("abcde")})
        figure = analysis(frame, _options(**{FAMILY_COLUMNS: ["G"], PLOT: True})).figure
        visible = [axis for axis in figure.axes if axis.get_visible()]
        hidden = [axis for axis in figure.axes if not axis.get_visible()]
        self.assertEqual(len(visible), 5)
        self.assertEqual(len(hidden), 1)
        self.assertEqual(visible[0].get_subplotspec().get_gridspec().ncols, 3)


if __name__ == "__main__":
    unittest.main()
