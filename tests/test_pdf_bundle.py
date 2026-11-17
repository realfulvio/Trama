import json
from math import isclose
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from matplotlib.figure import Figure
import numpy as np
import pypdfium2 as pdfium
from pypdfium2 import raw

from analisi.figure_export import MAX_BUNDLE_PAGES, export_pdf_bundle, plan_pdf_bundle
from analisi.presentation import compose_layout

FIXTURE = json.loads((Path(__file__).parent / "data" / "pdf_bundle" / "bundle.json").read_text(encoding="utf-8"))


def graphs():
    out = []
    for case in FIXTURE["pages"]:
        figure = Figure(figsize=case["size"])
        axes = figure.add_subplot()
        axes.plot(*zip(*case["points"]), color="#c0392b", label="series")
        axes.set_title(case["title"], fontsize=9)
        axes.legend()
        out.append(figure)
    return out


def state(figures):
    return [(tuple(f.get_size_inches()), f.dpi, f.canvas, [a.get_xlim() for a in f.axes]) for f in figures]


def pages(path):
    found = []
    with pdfium.PdfDocument(path) as document:
        for i in range(len(document)):
            page = document[i]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                finally:
                    textpage.close()
                images = len(list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])))
                found.append((page.get_size(), text, images))
            finally:
                page.close()
    return found


class BundleEngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "bundle.Pdf"
        self.graphs = graphs()
        self.figures = self.graphs + [compose_layout(FIXTURE["layout_title"], 2, self.graphs)]

    def tearDown(self):
        self.folder.cleanup()

    def test_fixture_sizes_order_and_content(self):
        before = state(self.figures)
        for key, settings in (("expected_original", {}), ("expected_resized", {"width_mm": FIXTURE["width_mm"]})):
            plans = export_pdf_bundle(self.figures, self.path, {"format": "pdf", **settings})
            self.assertEqual([plan["format"] for plan in plans], ["pdf"] * 3)
            found = pages(self.path)
            for (size, text, images), want, title in zip(found, FIXTURE[key], ["BETA", "ALPHA", "LAYOUT"], strict=True):
                self.assertTrue(all(isclose(a, b, abs_tol=.02) for a, b in zip(size, want)), (title, size))
                self.assertIn(title, text)
                self.assertEqual(images > 0, title == "LAYOUT", title)
            self.assertEqual(state(self.figures), before)

    def test_single_page(self):
        self.graphs[1].axes[0].set_title("ALPHA – città")
        plans = export_pdf_bundle(self.graphs[1:2], self.path, {"format": "pdf"})
        self.assertEqual(len(plans), 1)
        found = pages(self.path)
        self.assertEqual(len(found), 1)
        self.assertIn("ALPHA – città", found[0][1])

    def test_layout_panels_keep_text_paths_and_only_source_images(self):
        from analisi.layout_pdf import PdfLayoutPage

        self.graphs[1].axes[0].imshow([[0, 1], [1, 0]], extent=(1, 2, 1, 2), alpha=.5)
        self.graphs[1].axes[0].set_title("ALPHA città")
        before = state(self.graphs)
        layout = PdfLayoutPage("Layout – città", 2, tuple(self.graphs))
        export_pdf_bundle([self.graphs[0], layout], self.path, {"width_mm": 127, "transparent": True})
        graph, page = pages(self.path)
        self.assertIn("BETA", graph[1])
        self.assertNotIn("ALPHA", graph[1])
        self.assertAlmostEqual(page[0][0], 360, delta=.02)
        self.assertAlmostEqual(page[0][1], 360 * 3.6 / 8.4, delta=.02)
        for text in ("Layout – città", "BETA", "ALPHA città", "series"):
            self.assertIn(text, " ".join(page[1].split()))
        self.assertEqual(page[2], 1)
        with pdfium.PdfDocument(self.path) as document:
            panel_page = document[1]
            try:
                paths = list(panel_page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH], max_depth=8))
                self.assertGreater(len(paths), 10)
                bitmap = panel_page.render(scale=2, force_bitmap_format=raw.FPDFBitmap_BGRA,
                                           fill_color=(0, 0, 0, 0))
                try:
                    image = bitmap.to_pil()
                    self.assertEqual(image.getpixel((0, 0))[3], 0)
                    rgba = np.asarray(image, dtype=np.int16)
                    self.assertGreater(np.count_nonzero((rgba[:, :, 0] > rgba[:, :, 1] + 45)
                                                        & (rgba[:, :, 3] > 100)), 30)
                finally:
                    bitmap.close()
            finally:
                panel_page.close()
        self.assertEqual(state(self.graphs), before)

    def test_layout_render_error_leaves_existing_pdf_intact(self):
        from analisi.layout_pdf import PdfLayoutPage

        layout = PdfLayoutPage("Panels", 2, tuple(self.graphs))
        export_pdf_bundle([layout], self.path, {})
        original = self.path.read_bytes()
        before = state(self.graphs)
        with patch.object(self.graphs[1], "savefig", side_effect=OSError("synthetic panel failure")):
            with self.assertRaisesRegex(OSError, "synthetic panel failure"):
                export_pdf_bundle([layout], self.path, {"width_mm": 100})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(state(self.graphs), before)

    def test_page_limits_and_destination(self):
        for figures, path, settings in (([], self.path, {}), ([self.graphs[0]] * (MAX_BUNDLE_PAGES + 1), self.path, {}),
                                        (self.graphs, self.path.with_suffix(".png"), {}),
                                        (self.graphs, self.path, {"format": "png"}),
                                        ([self.graphs[0], None], self.path, {})):
            with self.subTest(pages=len(figures), suffix=path.suffix, settings=settings), self.assertRaises(ValueError):
                export_pdf_bundle(figures, path, settings)
        self.assertFalse(self.path.exists())
        plans = export_pdf_bundle([self.graphs[0]] * MAX_BUNDLE_PAGES, self.path, {})
        self.assertEqual(len(plans), MAX_BUNDLE_PAGES)
        self.assertEqual(len(pages(self.path)), MAX_BUNDLE_PAGES)

    def test_homonymous_pages_stay_distinct(self):
        first, second = graphs()[:2]
        for figure in (first, second):
            figure.axes[0].set_title("Same name")
        second.axes[0].set_xlabel("second page")
        export_pdf_bundle([second, first], self.path, {}, names=["Graph · Same name"] * 2)
        found = pages(self.path)
        self.assertIn("second page", found[0][1])
        self.assertNotIn("second page", found[1][1])

    def test_width_incompatible_with_one_page(self):
        tall = Figure(figsize=(1, 10))
        tall.add_subplot().plot([0, 1])
        with self.assertRaisesRegex(ValueError, r"Page 2 \(“Graph · Tall”\).*Height"):
            export_pdf_bundle([self.graphs[0], tall], self.path, {"width_mm": 60}, names=["Graph · Wide", "Graph · Tall"])
        with self.assertRaisesRegex(ValueError, "Page 1"):
            plan_pdf_bundle([(1, 1)], {"width_mm": 5})
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_transparency(self):
        calls = []
        original = Figure.savefig

        def spy(figure, *args, **kwargs):
            calls.append(kwargs.get("transparent"))
            return original(figure, *args, **kwargs)

        with patch.object(Figure, "savefig", spy):
            export_pdf_bundle(self.graphs, self.path, {})
            export_pdf_bundle(self.graphs, self.path, {"transparent": True})
        self.assertEqual(calls, [False, False, True, True])
        with self.assertRaises(ValueError):
            export_pdf_bundle(self.graphs, self.path, {"transparent": "yes"})

    def test_save_error_keeps_existing_file_and_figures(self):
        export_pdf_bundle(self.figures, self.path, {})
        before, figures = self.path.read_bytes(), state(self.figures)
        with patch.object(self.graphs[1], "savefig", side_effect=OSError("synthetic page failure")), \
                self.assertRaises(OSError):
            export_pdf_bundle(self.figures, self.path, {"width_mm": 76.2})
        with patch("analisi.figure_export._verify_pdf", side_effect=ValueError("short PDF")), self.assertRaises(ValueError):
            export_pdf_bundle(self.figures, self.path, {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(state(self.figures), figures)
        with self.assertRaises(OSError):
            export_pdf_bundle(self.graphs, Path(self.folder.name) / "missing" / "out.pdf", {})


class BundleDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Tk unavailable: {error}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def run_dialog(self, entries, action, excluded=()):
        from analisi.pdf_bundle_dialog import PdfBundleDialog

        seen = {}

        def drive():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, PdfBundleDialog))
            if not dialog.winfo_viewable():
                self.root.after(20, drive)
                return
            try:
                # Windows can deliver the initial focus/selection events after the timer fires.
                # Settle mapping and focus before simulating user selection; preserve every assertion.
                dialog.listbox.focus_force()
                dialog.update()
                seen["result"] = action(dialog)
            except Exception as error:  # re-raised after the modal loop ends
                seen["error"] = error
            finally:
                if dialog.winfo_exists():
                    dialog.cancel()

        self.root.after(100, drive)
        dialog = PdfBundleDialog(self.root, entries, excluded)
        if "error" in seen:
            raise seen["error"]
        return dialog.result, seen.get("result")

    def entries(self):
        from analisi.pdf_bundle_dialog import BundleEntry

        return [BundleEntry(("graph", 0), "Graph", "Same", (2, 1)), BundleEntry(("graph", 3), "Graph", "Same", (1, 2)),
                BundleEntry(("layout", 0), "Layout", "Panels", (8.4, 3.6), True)]

    def test_reorder_and_homonyms(self):
        def action(dialog):
            self.assertIn("1 page", dialog.summary.cget("text"))
            self.assertEqual(dialog.listbox.get(0, "end"), ("Graph · Same", "Graph · Same (2)", "Layout · Panels"))
            dialog.listbox.selection_clear(0, "end")
            dialog.listbox.selection_set(1, 2)
            dialog.move(-1)
            self.assertEqual([e.ref for e in dialog.selected()], [("graph", 3), ("layout", 0)])
            self.assertIn("2 pages", dialog.summary.cget("text"))
            self.assertIn("Sheets with embedded images", dialog.note.cget("text"))
            self.assertIn("Panels", dialog.note.cget("text"))
            dialog.move(-1)  # already at the top: no change
            self.assertEqual(dialog.order, [1, 2, 0])
            dialog.listbox.selection_clear(0, "end")
            dialog.listbox.selection_set(0)
            dialog.listbox.event_generate("<<ListboxSelect>>")
            dialog.update()
            self.assertNotIn("Sheets with embedded images", dialog.note.cget("text"))
            dialog.listbox.selection_set(2)
            dialog.ok()

        result, _ = self.run_dialog(self.entries(), action, ["Not calculated, so not listed: Old."])
        self.assertEqual(result, {"refs": [("graph", 3), ("graph", 0)], "settings": {"format": "pdf", "transparent": False}})

    def test_invalid_choices_keep_dialog_open(self):
        def action(dialog):
            self.assertIn("Not calculated", dialog.note.cget("text"))
            dialog.listbox.selection_clear(0, "end")
            self.assertFalse(dialog.validate())
            self.assertIn("Select at least one", dialog.summary.cget("text"))
            dialog.listbox.selection_set(0, 2)
            dialog.width.set("abc")
            self.assertFalse(dialog.validate())
            dialog.width.set("40")  # 40 mm suits both graphs, but the layout would be 17.1 mm high
            self.assertFalse(dialog.validate())
            self.assertIn("Layout · Panels", dialog.summary.cget("text"))
            dialog.width.set("76,2")
            dialog.transparent.set(True)
            self.assertTrue(dialog.validate())
            return "checked"

        result, seen = self.run_dialog(self.entries(), action, ["Not calculated, so not listed: Old."])
        self.assertIsNone(result)
        self.assertEqual(seen, "checked")

    def test_italian_dialog_preserves_sheet_references(self):
        from analisi import i18n

        def action(dialog):
            self.assertEqual(dialog.title(), "Esporta più fogli in PDF")
            self.assertEqual(dialog.up.cget("text"), "Sposta su")
            self.assertEqual(dialog.down.cget("text"), "Sposta giù")
            self.assertEqual(dialog.listbox.get(0), "Grafico · Same")
            self.assertIn("1 pagina", dialog.summary.cget("text"))
            dialog.listbox.selection_clear(0, "end")
            self.assertFalse(dialog.validate())
            self.assertIn("Seleziona almeno", dialog.summary.cget("text"))
            dialog.listbox.selection_set(1, 2)
            dialog.move(-1)
            self.assertIn("2 pagine", dialog.summary.cget("text"))
            self.assertIn("Fogli con immagini incorporate", dialog.note.cget("text"))
            dialog.width.set("abc")
            self.assertFalse(dialog.validate())
            self.assertIn("millimetri", dialog.summary.cget("text"))
            dialog.width.set("76,2")
            dialog.ok()

        original_language = i18n.active_language()
        try:
            i18n.set_language("it")
            result, _ = self.run_dialog(self.entries(), action)
        finally:
            i18n.set_language(original_language)
        self.assertEqual(result["refs"], [("graph", 3), ("layout", 0)])


class LayoutSizeTests(unittest.TestCase):
    def test_listed_layout_size_matches_composition(self):
        figures = graphs()
        for columns, count in ((1, 1), (2, 2), (2, 3), (3, 7)):
            composed = compose_layout("L", columns, (figures * 4)[:count])
            rows = -(-count // columns)
            self.assertEqual(tuple(composed.get_size_inches()), (4.2 * columns, 3.2 * rows + .4))


if __name__ == "__main__":
    unittest.main()
