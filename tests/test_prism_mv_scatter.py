from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from matplotlib.colors import to_rgba
import numpy as np

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.prism_mv_scatter import APPEARANCE
from analisi.prism_mv_scatter_smoke import COLORS, PLOT, archive_fixture
from analisi.prism_restore import SAVED_XY
from analisi.workbench import analyse

class SavedCategoricalScatterTests(unittest.TestCase):
    def test_view_uses_exact_ids_and_saves_editable_coordinates(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "project.prismt"
            archive_fixture(source)
            self.assertEqual(list(load_tables(source)), ["Original"])
            tables = load_tables(source, restore_prism=True)
            self.assertNotIn("Graph unavailable", tables["Original"].attrs["import_warnings"][0])
            points = Dataset(tables[PLOT])
            path = Path(folder) / "roundtrip.alab"
            save_project(path, {PLOT: points})
            reopened = load_project(path)[PLOT]
            self.assertEqual(reopened.analyses, points.analyses)
            method, options = reopened.analyses[0]
            self.assertEqual(method, SAVED_XY)
            self.assertEqual(options[APPEARANCE]["palette"], COLORS)
            frame = reopened.frame()
            self.assertEqual(frame["Series"].tolist(), ["_Run B", "Run $A", "Run $A"])
            frame.loc[1, "X"] = 4.0
            figure = analyse(method, frame, options).figure
            ax, = figure.axes
            np.testing.assert_allclose(ax.collections[0].get_offsets(), [[4, 6], [5, 2]])
            np.testing.assert_allclose(ax.collections[1].get_offsets(), [[2, 5]])
            for artist, color in zip(ax.collections, COLORS.values(), strict=True):
                np.testing.assert_allclose(artist.get_facecolors()[0], to_rgba(color))
                np.testing.assert_allclose(artist.get_sizes(), [25])
                np.testing.assert_allclose(artist.get_linewidths(), [.4])
            self.assertEqual(ax.get_ylim(), (10, 0))
            self.assertEqual(ax.get_xlim(), (-1, 7))
            self.assertEqual(ax.get_xlabel(), "Dose $")
            np.testing.assert_allclose(ax.get_xticks(), [0, 2, 4, 6])
            np.testing.assert_allclose(ax.get_yticks(), [0, 2.5, 5, 7.5, 10])
            legend = ax.get_legend()
            self.assertEqual([item.get_text() for item in legend.get_texts()], list(COLORS))
            self.assertFalse(legend.get_texts()[0].get_parse_math())
            svg = Path(folder) / "saved.svg"
            figure.savefig(svg)
            self.assertIn("#339966", svg.read_text())

    def test_unsupported_graphs_keep_the_original_warning(self):
        for change in (
            {"dataSheet": "missing"},
            {"gdoTypesExt": {"defaults": ["symbols", "confidence ellipses"]}},
            {"xVariables": ["scatter-y"]},
            {"xVariables": ["not-a-dataset"]},
        ):
            with self.subTest(change=change), TemporaryDirectory() as folder:
                source = Path(folder) / "project.prismt"
                archive_fixture(source, change=change)
                views = load_tables(source, restore_prism=True)
                self.assertNotIn(PLOT, views)
                self.assertIn("Graph unavailable for Grouped scatter", views["Original"].attrs["import_warnings"][0])
