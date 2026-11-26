"""Independent legend edits must never cross native panel boundaries."""
from copy import deepcopy
import unittest

from matplotlib.figure import Figure
import pandas as pd

from analisi.graph_legend import apply_legend_options, collect_legend_entries, legend_entry_key
from analisi.normality import normality


class LegendPanelIdentityTests(unittest.TestCase):
    def test_equal_display_labels_keep_their_keys_when_reversed(self):
        figure = Figure()
        axes = figure.subplots()
        axes.plot([0, 1], [0, 1], label="First")
        axes.plot([0, 1], [1, 0], label="Second")
        legend = axes.legend()
        keys = [entry.key for entry in collect_legend_entries(figure)]
        apply_legend_options(figure, {"reverse": True, "labels": dict.fromkeys(keys, "Replica")})
        texts = legend.get_texts()
        self.assertEqual([text.get_text() for text in texts], ["Replica", "Replica"])
        self.assertEqual([legend_entry_key(figure, legend, text) for text in texts], keys[::-1])

    def test_duplicate_figure_legend_labels_have_distinct_editor_captions(self):
        fig = Figure()
        ax = fig.subplots()
        first, = ax.plot([0, 1], [0, 1])
        second, = ax.plot([0, 1], [1, 0])
        fig.legend([first], ["Same"])
        fig.legend([second], ["Same"])
        entries = collect_legend_entries(fig)
        self.assertEqual(len({entry.key for entry in entries}), 2)
        self.assertEqual(len({entry.display_name for entry in entries}), 2)

    def test_duplicate_extra_legend_labels_have_distinct_editor_captions(self):
        fig = Figure()
        ax = fig.subplots()
        first, = ax.plot([0, 1], [0, 1])
        second, = ax.plot([0, 1], [1, 0])
        ax.add_artist(ax.legend([first], ["Same"]))
        ax.legend([second], ["Same"])
        entries = collect_legend_entries(fig)
        self.assertEqual(len({entry.key for entry in entries}), 2)
        self.assertEqual(len({entry.display_name for entry in entries}), 2)

    def test_same_named_series_in_two_panels_can_be_renamed_independently(self):
        fig = Figure()
        for ax in fig.subplots(1, 2):
            ax.plot([0, 1], [0, 1], label="Reference")
            ax.legend()
        entries = collect_legend_entries(fig)
        self.assertEqual(len({entry.key for entry in entries}), 2)
        self.assertEqual(len({entry.display_name for entry in entries}), 2)
        apply_legend_options(fig, {"labels": {entries[0].key: "First only"}})
        self.assertEqual([ax.get_legend().get_texts()[0].get_text() for ax in fig.axes],
                         ["First only", "Reference"])
        apply_legend_options(fig, {"labels": {entries[1].key: "Second only"}})
        self.assertEqual([ax.get_legend().get_texts()[0].get_text() for ax in fig.axes],
                         ["Reference", "Second only"])

    def test_qq_panel_identity_survives_removing_other_distribution_and_copy(self):
        data = pd.DataFrame({"Value": [1.2, 2.3, 3.1, 4.4, 5., 6.2, 7.1]})
        options = {"Variables": ["Value"], "Distribution": "Both", "Q–Q plot": True,
                   "Q–Q variable": "Value", "Q–Q reference line": True}
        both = normality(data, options).figure
        entries = collect_legend_entries(both)
        self.assertEqual(len({entry.key for entry in entries}), 4)
        log_entry = next(entry for entry in entries
                         if entry.scope == "qq:lognormal" and entry.label == "Fitted reference")
        style = {"labels": {log_entry.key: "Log model only"}, "reverse": True}
        apply_legend_options(both, style)
        by_panel = {ax._trama_qq_panel: [text.get_text() for text in ax.get_legend().get_texts()]
                    for ax in both.axes}
        self.assertIn("Log model only", by_panel["lognormal"])
        self.assertNotIn("Log model only", by_panel["normal"])
        one = normality(data, {**options, "Distribution": "Lognormal"}).figure
        self.assertIn(log_entry.key, [entry.key for entry in collect_legend_entries(one)])
        apply_legend_options(one, style)
        copied = deepcopy(one)
        self.assertIn("Log model only", [text.get_text() for text in copied.axes[0].get_legend().get_texts()])
        apply_legend_options(copied, {})
        self.assertNotIn("Log model only", [text.get_text() for text in copied.axes[0].get_legend().get_texts()])
        self.assertIn("Log model only", [text.get_text() for text in one.axes[0].get_legend().get_texts()])
