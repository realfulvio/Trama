"""Unit tests for the two-factor interaction plot engine, styling, i18n, and exports."""
import io
import math
from pathlib import Path
import statistics
import unittest

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from analisi import i18n
from analisi.category_order import WORKSHEET_ORDERS
from analisi.field_error import FieldError
from analisi.interaction_plot import (
    CELLS_SHEET,
    CI,
    COLUMNS,
    CONFIDENCE_LEVEL,
    ERROR_BARS,
    ERROR_PREFIX,
    METHOD,
    NONE,
    RESPONSE,
    SD,
    SEM,
    SERIES_FACTOR,
    SETTINGS_SHEET,
    X_FACTOR,
    check_options,
    compute_interaction_cells,
    interaction_plot,
    style_after_parameter_change,
    visibility,
)
from analisi.presentation import apply_style, compose_layout, graph_series
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse


FIXTURE = Path(__file__).resolve().parent / "data" / "interaction_plot" / "interaction.csv"


def _fixture():
    return pd.read_csv(FIXTURE, keep_default_na=False)


def _base_options(**overrides):
    return {
        RESPONSE: "Response",
        X_FACTOR: "Dose",
        SERIES_FACTOR: "Group",
        ERROR_BARS: CI,
        CONFIDENCE_LEVEL: 95.0,
        **overrides,
    }


class InteractionPlotCatalogueTests(unittest.TestCase):
    def test_registration_and_relative_order_preserved(self):
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GROUPS["Graphing"])
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(GROUPS["Graphing"][-1], METHOD)
        # Existing items keep their exact relative order before the new entry.
        self.assertEqual(GROUPS["Graphing"][-2], "Forest plot")
        self.assertEqual(GROUPS["Graphing"][0], "Scatter / confidence ellipse")


class InteractionPlotStatisticsTests(unittest.TestCase):
    def test_fixture_statistics_for_all_modes_and_confidence_levels(self):
        frame = _fixture()
        expected_cells = {
            ("Low", "Control $"): [2.0, 4.0, 6.0],
            ("Low", "Treatment"): [6.0, 10.0],
            ("Mid", "Control $"): [5.0, 7.0],
            ("Mid", "Treatment"): [],
            ("High", "Control $"): [9.0],
            ("High", "Treatment"): [12.0, 12.0],
        }
        for mode, level in ((CI, 95.0), (CI, 90.0), (NONE, 95.0), (SD, 95.0), (SEM, 95.0)):
            with self.subTest(mode=mode, level=level):
                result = analyse(METHOD, frame, _base_options(**{ERROR_BARS: mode, CONFIDENCE_LEVEL: level}))
                table = result.tables[CELLS_SHEET]
                self.assertEqual(list(table.columns), COLUMNS)
                rows = list(table.itertuples(index=False, name=None))
                self.assertEqual(len(rows), 6)
                for (x_lvl, s_lvl, n, mean, sd, sem, lower, upper), ((ex, es), vals) in zip(
                    rows, expected_cells.items(), strict=True
                ):
                    self.assertEqual((x_lvl, s_lvl), (ex, es))
                    self.assertEqual(n, len(vals))
                    if n == 0:
                        for col in (mean, sd, sem, lower, upper):
                            self.assertTrue(pd.isna(col))
                    elif n == 1:
                        self.assertAlmostEqual(mean, vals[0])
                        for col in (sd, sem, lower, upper):
                            self.assertTrue(pd.isna(col))
                    else:
                        exp_mean = statistics.mean(vals)
                        exp_sd = statistics.stdev(vals)
                        exp_sem = exp_sd / math.sqrt(n)
                        self.assertAlmostEqual(mean, exp_mean, places=10)
                        self.assertAlmostEqual(sd, exp_sd, places=10)
                        self.assertAlmostEqual(sem, exp_sem, places=10)
                        if mode == NONE:
                            self.assertTrue(pd.isna(lower))
                            self.assertTrue(pd.isna(upper))
                        else:
                            width = (
                                exp_sd if mode == SD
                                else exp_sem if mode == SEM
                                else float(student_t.ppf(0.5 + level / 200.0, df=n - 1)) * exp_sem
                            )
                            self.assertAlmostEqual(lower, exp_mean - width, places=10)
                            self.assertAlmostEqual(upper, exp_mean + width, places=10)

                settings_df = result.tables[SETTINGS_SHEET]
                self.assertIn("Rows used", settings_df.index)
                self.assertEqual(settings_df.loc["Rows used", "Value"], 10)
                self.assertEqual(settings_df.loc["Rows discarded", "Value"], 5)
                if mode == CI:
                    self.assertEqual(settings_df.loc["Confidence level (%)", "Value"], level)
                else:
                    self.assertNotIn("Confidence level (%)", settings_df.index)

    def test_decimal_comma_and_blank_levels_and_level_with_only_blank_response(self):
        frame = pd.DataFrame({
            "Dose": ["Low", "Low", "Mid", "High", "High", " "],
            "Group": ["A", "B", "A", "A", "B", "A"],
            "Response": ["2,5", "4,5", "bad", "7,0", "9,0", "100"],
        })
        result = interaction_plot(frame, _base_options(**{ERROR_BARS: NONE}))
        table = result.tables[CELLS_SHEET]
        # Mid has both factors present even though its only Response is non-numeric -> included with N=0.
        self.assertEqual(list(dict.fromkeys(table["X level"])), ["Low", "Mid", "High"])
        mid_a = table[(table["X level"] == "Mid") & (table["Series"] == "A")].iloc[0]
        self.assertEqual(mid_a["N"], 0)
        self.assertTrue(pd.isna(mid_a["Mean"]))
        low_a = table[(table["X level"] == "Low") & (table["Series"] == "A")].iloc[0]
        self.assertAlmostEqual(low_a["Mean"], 2.5)
        self.assertEqual(result.tables[SETTINGS_SHEET].loc["Rows used", "Value"], 4)
        self.assertEqual(result.tables[SETTINGS_SHEET].loc["Rows discarded", "Value"], 2)

    def test_typed_levels_collision_and_custom_worksheet_order(self):
        frame = pd.DataFrame({
            "Dose": pd.Series([1, 1, "1", "1", 2, 2], dtype=object),
            "Group": ["A", "B", "A", "B", "A", "B"],
            "Response": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
        })
        frame.attrs[WORKSHEET_ORDERS] = {"Dose": ["int:2", "str:1"], "Group": ["str:B", "str:A"]}
        result = interaction_plot(frame, _base_options(**{ERROR_BARS: SEM}))
        table = result.tables[CELLS_SHEET]
        x_ticks = [tick.get_text() for tick in result.figure.axes[0].get_xticklabels()]
        # Priority puts int:2 first, str:1 second, remaining int:1 appended in first-occurrence order.
        self.assertEqual(x_ticks, ["2", "'1'", "1"])
        self.assertEqual(list(dict.fromkeys(table["X level"])), ["2", "'1'", "1"])
        self.assertEqual(list(dict.fromkeys(table["Series"])), ["B", "A"])
        legend_texts = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(legend_texts, ["B", "A"])

    def test_missing_intermediate_x_breaks_line_and_keeps_literal_dollar_labels(self):
        frame = _fixture()
        result = interaction_plot(frame, _base_options())
        ax = result.figure.axes[0]
        self.assertEqual([t.get_text() for t in ax.get_xticklabels()], ["Low", "Mid", "High"])
        self.assertTrue(all(not t.get_parse_math() for t in ax.get_xticklabels()))
        legend = ax.get_legend()
        self.assertEqual([t.get_text() for t in legend.get_texts()], ["Control $", "Treatment"])
        self.assertTrue(all(not t.get_parse_math() for t in legend.get_texts()))
        self.assertFalse(legend.get_title().get_parse_math())

        # Treatment has Low (mean 8.0), Mid (NaN -> gap), High (mean 12.0).
        treat_line = ax.containers[1].lines[0]
        ydata = np.asarray(treat_line.get_ydata(), dtype=float)
        self.assertEqual(len(ydata), 3)
        self.assertAlmostEqual(ydata[0], 8.0)
        self.assertTrue(np.isnan(ydata[1]))
        self.assertAlmostEqual(ydata[2], 12.0)

        # Applying presentation style preserves literal $ text and series identity across reordering.
        style = {
            "series": {"errorbar:1:Control $": {"color": "#cc3311", "marker": "D", "width": 2.4}},
            "legend": "lower right",
        }
        apply_style(result.figure, style)
        self.assertTrue(all(not t.get_parse_math() for t in ax.get_legend().get_texts()))
        self.assertFalse(ax.get_legend().get_title().get_parse_math())
        reordered = frame.iloc[::-1].reset_index(drop=True)
        reordered_res = interaction_plot(reordered, _base_options())
        apply_style(reordered_res.figure, style)
        keys = [s.key for s in graph_series(reordered_res.figure.axes[0])]
        self.assertIn("errorbar:1:Control $", keys)
        ctrl_series = next(s for s in graph_series(reordered_res.figure.axes[0]) if s.key == "errorbar:1:Control $")
        self.assertEqual(ctrl_series.artist.lines[0].get_color(), "#cc3311")

    def test_style_preserved_when_toggling_error_bars_none_vs_active(self):
        frame = _fixture()
        before = _base_options(**{ERROR_BARS: CI})
        after = _base_options(**{ERROR_BARS: NONE})
        style = {
            "series": {"errorbar:1:Control $": {"color": "#112233", "width": 2.2}},
            "legend_options": {"labels": {"errorbar:1:Control $": "Ctrl"}},
        }
        remapped = style_after_parameter_change(style, before, after)
        self.assertIn("line:1:Control $", remapped["series"])
        self.assertIn("line:1:Control $", remapped["legend_options"]["labels"])
        res_none = interaction_plot(frame, after)
        apply_style(res_none.figure, remapped)
        line_series = next(s for s in graph_series(res_none.figure.axes[0]) if s.key == "line:1:Control $")
        self.assertEqual(line_series.artist.get_color(), "#112233")

    def test_vector_export_and_two_panel_layout(self):
        frame = _fixture()
        r1 = interaction_plot(frame, _base_options(**{ERROR_BARS: CI}))
        r2 = interaction_plot(frame, _base_options(**{ERROR_BARS: NONE}))
        svg, pdf, png = io.BytesIO(), io.BytesIO(), io.BytesIO()
        r1.figure.savefig(svg, format="svg")
        r1.figure.savefig(pdf, format="pdf")
        r1.figure.savefig(png, format="png", dpi=100)
        self.assertIn(b"Control $", svg.getvalue())
        self.assertTrue(pdf.getvalue().startswith(b"%PDF"))
        self.assertTrue(png.getvalue().startswith(b"\x89PNG"))
        layout_fig = compose_layout("Comparison", 2, [r1.figure, r2.figure])
        self.assertGreaterEqual(len(layout_fig.axes), 2)


class InteractionPlotValidationAndI18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_validation_errors_and_visibility(self):
        self.assertEqual(visibility(CI), {CONFIDENCE_LEVEL: True})
        for mode in (NONE, SD, SEM):
            self.assertEqual(visibility(mode), {CONFIDENCE_LEVEL: False})

        frame = _fixture()
        bad_cases = (
            ({RESPONSE: ""}, RESPONSE),
            ({RESPONSE: "Missing"}, RESPONSE),
            ({X_FACTOR: "Response"}, X_FACTOR),
            ({SERIES_FACTOR: "Dose"}, SERIES_FACTOR),
            ({SERIES_FACTOR: "Response"}, SERIES_FACTOR),
            ({ERROR_BARS: "BadMode"}, ERROR_BARS),
            ({CONFIDENCE_LEVEL: 0}, CONFIDENCE_LEVEL),
            ({CONFIDENCE_LEVEL: 100}, CONFIDENCE_LEVEL),
            ({CONFIDENCE_LEVEL: -5}, CONFIDENCE_LEVEL),
            ({CONFIDENCE_LEVEL: True}, CONFIDENCE_LEVEL),
            ({CONFIDENCE_LEVEL: "abc"}, CONFIDENCE_LEVEL),
        )
        for overrides, expected_field in bad_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(FieldError) as ctx:
                    check_options(frame, _base_options(**overrides))
                self.assertEqual(ctx.exception.field, expected_field)

        # Invalid confidence level is ignored when Error bars is not Confidence interval.
        check_options(frame, _base_options(**{ERROR_BARS: SD, CONFIDENCE_LEVEL: 150}))

        # Numeric overflow raises FieldError on Response.
        huge = pd.DataFrame({
            "Dose": ["A", "A", "B", "B"],
            "Group": ["G1", "G1", "G2", "G2"],
            "Response": [1e308, -1e308, 1.0, 2.0],
        })
        with self.assertRaises(FieldError) as ctx:
            interaction_plot(huge, _base_options())
        self.assertEqual(ctx.exception.field, RESPONSE)

        # Too few levels / no valid observations.
        one_x = pd.DataFrame({"Dose": ["A", "A"], "Group": ["G1", "G2"], "Response": [1.0, 2.0]})
        with self.assertRaises(FieldError) as ctx:
            check_options(one_x, _base_options())
        self.assertEqual(ctx.exception.field, X_FACTOR)

        no_valid = pd.DataFrame({"Dose": ["A", "B"], "Group": ["G1", "G2"], "Response": ["bad", "inf"]})
        with self.assertRaises(FieldError) as ctx:
            check_options(no_valid, _base_options())
        self.assertEqual(ctx.exception.field, RESPONSE)

    def test_italian_captions_and_error_translations(self):
        i18n.set_language("it")
        self.assertEqual(i18n.ui(METHOD), "Grafico d'interazione")
        self.assertEqual(i18n.ui(X_FACTOR), "Fattore X")
        self.assertEqual(i18n.ui(SERIES_FACTOR), "Fattore delle serie")
        self.assertEqual(i18n.ui(ERROR_BARS), "Barre d'errore")
        self.assertEqual(i18n.ui(CONFIDENCE_LEVEL), "Livello di confidenza")

        frame = _fixture()
        for overrides, expected_fragment in (
            ({X_FACTOR: "Response"}, "diversa da Risposta"),
            ({SERIES_FACTOR: "Dose"}, "diversa da Risposta e Fattore X"),
            ({CONFIDENCE_LEVEL: 100}, "maggiore di 0 e minore di 100"),
        ):
            with self.assertRaises(FieldError) as ctx:
                check_options(frame, _base_options(**overrides))
            translated = i18n.translate_message(str(ctx.exception), ERROR_PREFIX, convert={"field": i18n.ui})
            self.assertIn(expected_fragment, translated)
            self.assertNotIn("{", translated)


if __name__ == "__main__":
    unittest.main()
