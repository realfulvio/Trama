"""The Qt gallery of graphs and layouts: catalog, search, states, previews, cache and the window flow.

Offscreen. Skipped when PySide6 (or its platform libraries) is not installed.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from uuid import uuid4

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QListView, QStyleOptionViewItem
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "data" / "qt_gallery" / "galleria.alab"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-gallery-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def fixture_project(*, calculated=False):
    """The fixture of the package: three graphs (two XY series and a column graph) and two layouts."""
    from trama_qt.project import Project, compute
    project = Project()
    project.load(FIXTURE)
    if calculated:
        for run in project.runs:
            run.result = compute(run, project.tables[run.title].frame(mask_excluded=True))
    return project


def many_graphs(count):
    """A calculated project with ``count`` graphs of one table."""
    from trama_qt.project import Project, compute
    project = Project()
    project.load(FIXTURE)
    template = project.runs[0]
    frame = project.tables[template.title].frame(mask_excluded=True)
    for number in range(count):
        candidate = project.candidate(template.title, template.method, deepcopy(template.options))
        candidate.label = f"Grafico {number + 1:03d}"
        project.add_result(candidate, compute(candidate, frame))
    return project


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class CatalogTests(unittest.TestCase):
    def test_lists_graphs_then_layouts_with_navigation_references(self):
        from trama_qt.gallery_catalog import catalog
        entries = catalog(fixture_project())
        self.assertEqual([entry.ref for entry in entries],
                         [("graph", 0), ("graph", 1), ("graph", 2), ("layout", 0), ("layout", 1)])
        self.assertEqual([entry.name for entry in entries],
                         ["Calibrazione $ A", "Ripetizione B", "Confronto a colonne", "Piastra 1",
                          "Sintesi laboratorio"])
        self.assertEqual([entry.kind for entry in entries], ["graph"] * 3 + ["layout"] * 2)
        self.assertEqual([entry.panels for entry in entries], [0, 0, 0, 2, 1])

    def test_states_tell_ready_pending_stale_and_failed(self):
        from trama_qt.gallery_catalog import ERROR, PENDING, READY, STALE, catalog
        project = fixture_project()
        self.assertEqual({entry.state for entry in catalog(project)}, {PENDING})
        project = fixture_project(calculated=True)
        self.assertEqual({entry.state for entry in catalog(project)}, {READY})
        project.runs[0].calculation_error = "Updating 1 linked result(s)…"
        states = {entry.ref: entry for entry in catalog(project)}
        self.assertEqual(states[("graph", 0)].state, STALE)
        self.assertEqual(states[("layout", 0)].state, STALE)  # A layout is as current as its panels.
        self.assertEqual(states[("layout", 1)].state, READY)
        self.assertIn("Updating", states[("graph", 0)].detail)
        project.runs[1].result, project.runs[1].calculation_error = None, "Unknown column"
        states = {entry.ref: entry for entry in catalog(project)}
        self.assertEqual(states[("graph", 1)].state, ERROR)
        self.assertEqual(states[("layout", 0)].state, ERROR)
        self.assertEqual(states[("graph", 1)].detail, "Unknown column")

    def test_reading_the_catalog_changes_nothing(self):
        from trama_qt.gallery_catalog import catalog, visible
        project = fixture_project()
        before = [run.result for run in project.runs]
        catalog(project)
        visible(catalog(project), text="Calibrazione")
        self.assertTrue(all(run.result is None for run in project.runs))
        self.assertEqual(before, [None] * 3)
        self.assertFalse(project.dirty)

    def test_search_is_literal_and_ignores_accents_case_and_spaces(self):
        from trama_qt.gallery_catalog import catalog, visible
        entries = catalog(fixture_project())

        def names(text, kind=None):
            return [entry.name for entry in visible(entries, kind, text)]

        self.assertEqual(names("Calibrazione $"), ["Calibrazione $ A"])
        self.assertEqual(names("  calibrazióne    $  "), ["Calibrazione $ A"])
        self.assertEqual(names("$"), ["Calibrazione $ A"])
        self.assertEqual(names("SINTESI"), ["Sintesi laboratorio"])
        self.assertEqual(names(".*"), [])  # Never a pattern.
        self.assertEqual(names("[a-z]+"), [])
        self.assertEqual(len(names("")), 5)
        self.assertEqual(names("a", "layout"), ["Piastra 1", "Sintesi laboratorio"])
        self.assertEqual(names("", "layout"), ["Piastra 1", "Sintesi laboratorio"])
        self.assertEqual(names("Piastra", "graph"), [])

    def test_the_title_stays_literal(self):
        from trama_qt.gallery_catalog import describe
        project = fixture_project()
        project.runs[0].label = "Dose & <b>risposta</b> $1 %s {0}\n'x'"
        self.assertEqual(describe(project, ("graph", 0)).name, project.runs[0].label)

    def test_equal_names_stay_apart(self):
        from trama_qt.gallery_catalog import catalog, visible
        project = fixture_project()
        project.runs[1].label = project.runs[0].label
        entries = catalog(project)
        twins = [entry for entry in entries if entry.name == "Calibrazione $ A"]
        self.assertEqual([(entry.ref, entry.ordinal, entry.total) for entry in twins],
                         [(("graph", 0), 1, 2), (("graph", 1), 2, 2)])
        self.assertEqual([entry.ordinal for entry in entries if entry.name != "Calibrazione $ A"], [0, 0, 0])
        self.assertEqual(len(visible(entries, text="calibrazione $ a")), 2)

    def test_same_sheets_as_the_navigator(self):
        """The window's navigator and the gallery list the same graphs and layouts."""
        from trama_qt.gallery_catalog import catalog
        from trama_qt.window import MainWindow
        _app()
        window = MainWindow()
        window.project = fixture_project()
        window.refresh()
        try:
            from PySide6.QtWidgets import QTreeWidgetItemIterator
            listed = set()
            items = QTreeWidgetItemIterator(window.navigator)
            while (item := items.value()) is not None:
                ref = item.data(0, Qt.ItemDataRole.UserRole)
                if ref and ref[0] in {"graph", "layout", "saved-layout"}:
                    listed.add(tuple(ref))
                items += 1
            self.assertEqual(listed, {entry.ref for entry in catalog(window.project)})
        finally:
            window.project.dirty = False
            window.close()


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class CacheTests(unittest.TestCase):
    def thumb(self, entry, error=None):
        from trama_qt.gallery_thumbs import Thumb
        return Thumb(None, entry.refs, entry.sig, error)

    def test_least_recently_used_previews_go_first(self):
        from trama_qt.gallery_catalog import catalog
        from trama_qt.gallery_thumbs import ThumbnailCache
        entries = catalog(fixture_project(calculated=True))[:3]
        cache = ThumbnailCache(limit=2)
        cache.put(entries[0], self.thumb(entries[0]))
        cache.put(entries[1], self.thumb(entries[1]))
        self.assertIsNotNone(cache.get(entries[0]))  # Used again: the other one is now the oldest.
        cache.put(entries[2], self.thumb(entries[2]))
        self.assertEqual(len(cache), 2)
        self.assertIn(entries[0].ref, cache)
        self.assertNotIn(entries[1].ref, cache)

    def test_a_preview_is_dropped_when_data_style_or_calculation_change(self):
        from trama_qt.gallery_catalog import describe
        from trama_qt.gallery_thumbs import ThumbnailCache
        from trama_qt.project import compute
        project = fixture_project(calculated=True)
        run = project.runs[0]
        cache, ref = ThumbnailCache(), ("graph", 0)
        entry = describe(project, ref)
        cache.put(entry, self.thumb(entry))
        self.assertIsNotNone(cache.get(describe(project, ref)))
        run.style = {"title": "Edited"}  # Format Graph or the Inspector.
        self.assertIsNone(cache.get(describe(project, ref)))
        cache.put(describe(project, ref), self.thumb(describe(project, ref)))
        self.assertIsNotNone(cache.get(describe(project, ref)))
        # A data change recalculates: a new result object, even if it looks the same.
        run.result = compute(run, project.tables[run.title].frame(mask_excluded=True))
        self.assertIsNone(cache.get(describe(project, ref)))
        # Another layout page.
        layout = ("layout", 0)
        cache.put(describe(project, layout), self.thumb(describe(project, layout)))
        project.layouts[0].columns = 1
        self.assertIsNone(cache.get(describe(project, layout)))

    def test_prune_and_clear(self):
        from trama_qt.gallery_catalog import catalog
        from trama_qt.gallery_thumbs import ThumbnailCache
        entries = catalog(fixture_project(calculated=True))
        cache = ThumbnailCache()
        for entry in entries:
            cache.put(entry, self.thumb(entry))
        cache.prune({entries[0].ref, entries[1].ref})
        self.assertEqual(len(cache), 2)
        cache.clear()
        self.assertEqual(len(cache), 0)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def settle(self, service, timeout=20):
        end = time.monotonic() + timeout
        while (service.task is not None or service.queue) and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertIsNone(service.task)
        self.assertFalse(service.queue)

    def service(self, project, busy=lambda: False):
        from trama_qt.gallery_thumbs import ThumbnailService
        service = ThumbnailService(lambda: project, busy)
        self.addCleanup(service.stop)
        return service

    def test_previews_keep_the_proportions_of_the_figure_and_of_the_page(self):
        from trama_qt.gallery_catalog import catalog
        project = fixture_project(calculated=True)
        service = self.service(project)
        entries = catalog(project)
        service.request(entries, (240, 150))
        self.settle(service)
        self.assertEqual(service.drawn, 5)
        graph = service.cache.get(entries[0]).pixmap
        self.assertEqual((graph.width(), graph.height()), (240, 150))  # The graph is 8 × 5 inches.
        page = service.cache.get(entries[3]).pixmap  # "Piastra 1": two panels, 8.4 × 3.6 inches.
        self.assertLessEqual(page.width(), 240)
        self.assertLessEqual(page.height(), 150)
        self.assertAlmostEqual(page.width() / page.height(), 8.4 / 3.6, delta=0.03)
        self.assertNotEqual(page.toImage().pixelColor(5, 5).name(), "")
        self.assertTrue(all(service.cache.get(entry).error is None for entry in entries))

    def test_a_preview_does_not_take_the_canvas_of_a_confirmed_figure(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from trama_qt.gallery_catalog import catalog
        project = fixture_project(calculated=True)
        figure = project.runs[0].result.figure
        canvas = FigureCanvasQTAgg(figure)  # The figure is on a page of the window.
        dpi, size = figure.dpi, tuple(figure.get_size_inches())
        service = self.service(project)
        service.request(catalog(project), (240, 150))
        self.settle(service)
        self.assertIs(figure.canvas, canvas)
        self.assertEqual(figure.dpi, dpi)
        self.assertEqual(tuple(figure.get_size_inches()), size)
        for run in project.runs:  # A figure that no page shows keeps its own canvas as well.
            self.assertIsNotNone(run.result.figure.canvas)

    def test_every_figure_is_drawn_on_the_gui_thread(self):
        from trama_qt import gallery_thumbs
        from trama_qt.gallery_catalog import catalog
        threads = []
        original = gallery_thumbs.figure_image

        def traced(*args):
            threads.append(threading.get_ident())
            return original(*args)

        project = fixture_project(calculated=True)
        service = self.service(project)
        gallery_thumbs.figure_image = traced
        self.addCleanup(setattr, gallery_thumbs, "figure_image", original)
        service.request(catalog(project), (240, 150))
        self.settle(service)
        self.assertGreaterEqual(len(threads), 5)
        self.assertEqual(set(threads), {threading.get_ident()})
        figure = project.runs[0].result.figure
        with ThreadPoolExecutor(max_workers=1) as pool:  # Matplotlib is not thread safe: refused elsewhere.
            with self.assertRaises(RuntimeError):
                pool.submit(original, figure, 100, 60).result()

    def test_nothing_is_drawn_while_a_calculation_runs(self):
        from trama_qt import gallery_thumbs
        from trama_qt.gallery_catalog import catalog
        busy = [True]
        project = fixture_project(calculated=True)
        service = self.service(project, lambda: busy[0])
        service.request(catalog(project), (240, 150))
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertEqual(service.drawn, 0)
        busy[0] = False
        end = time.monotonic() + gallery_thumbs.BUSY_MS / 1000 * 3 + 5
        while service.drawn < 5 and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertEqual(service.drawn, 5)

    def test_sheets_without_a_result_get_no_preview_and_start_no_calculation(self):
        from trama_qt.gallery_catalog import catalog
        project = fixture_project()
        service = self.service(project)
        service.request(catalog(project), (240, 150))
        self.settle(service)
        self.assertEqual((service.drawn, len(service.cache)), (0, 0))
        self.assertTrue(all(run.result is None for run in project.runs))

    def test_a_new_request_forgets_what_scrolled_out_of_sight(self):
        from trama_qt.gallery_catalog import catalog
        project = fixture_project(calculated=True)
        service = self.service(project)
        entries = catalog(project)
        service.request(entries[:3], (240, 150))
        service.request(entries[3:], (240, 150))
        self.settle(service)
        self.assertNotIn(entries[0].ref, service.cache)
        self.assertIn(entries[3].ref, service.cache)
        self.assertIn(entries[4].ref, service.cache)

    def test_a_result_that_changes_while_it_is_drawn_is_not_kept(self):
        from trama_qt.gallery_catalog import catalog
        from trama_qt.project import compute
        project = fixture_project(calculated=True)
        service = self.service(project)
        outdated = []
        service.outdated.connect(lambda: outdated.append(True))
        entries = catalog(project)
        service.request(entries[:1], (240, 150))
        run = project.runs[0]
        run.result = compute(run, project.tables[run.title].frame(mask_excluded=True))  # Recalculated meanwhile.
        self.settle(service)
        self.assertTrue(outdated)
        self.assertEqual(len(service.cache), 0)

    def test_clear_drops_every_preview(self):
        from trama_qt.gallery_catalog import catalog
        project = fixture_project(calculated=True)
        service = self.service(project)
        service.request(catalog(project), (240, 150))
        self.settle(service)
        self.assertEqual(len(service.cache), 5)
        service.clear()
        self.assertEqual(len(service.cache), 0)

    def test_a_figure_that_cannot_be_drawn_leaves_a_card_with_a_reason(self):
        from trama_qt import gallery_thumbs
        from trama_qt.gallery_catalog import catalog
        project = fixture_project(calculated=True)
        service = self.service(project)
        original = gallery_thumbs.figure_image

        def failing(figure, width, height):
            raise ValueError("no drawing")

        gallery_thumbs.figure_image = failing
        self.addCleanup(setattr, gallery_thumbs, "figure_image", original)
        entries = catalog(project)
        service.request(entries[:1], (240, 150))
        self.settle(service)
        thumb = service.cache.get(entries[0])
        self.assertIsNone(thumb.pixmap)
        self.assertIn("no drawing", thumb.error)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class GalleryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from analisi.i18n import active_language, set_language
        from trama_qt.window import MainWindow
        self.language = active_language()
        set_language("en")
        self.addCleanup(set_language, self.language)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.window.error = lambda error: self.fail(f"error shown: {error}")
        self.window.resize(1100, 760)
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def pump(self, seconds=0.5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def settle_previews(self, expected=None, timeout=30):
        gallery = self.window.gallery
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            visible = [entry for entry in gallery.visible_entries() if entry.previewable]
            idle = gallery.service.task is None and not gallery.service.queue and not gallery._scan_timer.isActive()
            if idle and all(gallery.service.cache.get(entry) is not None for entry in visible):
                break
            time.sleep(0.01)
        if expected is not None:
            self.assertEqual(gallery.service.drawn, expected)

    def visit_all_cards(self):
        """Scroll every card into view before checking the total preview count."""
        view = self.window.gallery.view
        for row in range(view.model().rowCount()):
            view.scrollTo(view.model().index(row, 0))
            self.settle_previews()
        view.scrollToTop()
        self.settle_previews()

    def open_fixture(self, *, calculate=False):
        self.window.open_path(FIXTURE)
        self.wait()
        if calculate:
            self.window.refresh_runs(list(self.window.project.runs))
            self.wait()
        self.window.project.dirty = False

    def open_gallery(self):
        self.window.actions["gallery"].trigger()
        self.pump(0.3)
        gallery = self.window.gallery
        self.assertIsNotNone(gallery)
        return gallery

    def test_gallery_opens_from_the_status_bar_and_lists_the_cards(self):
        self.open_fixture()
        action = self.window.actions["gallery"]
        view_menu = self.window.command_menus["View"]
        self.assertIn(action, view_menu.actions())
        self.assertNotIn("gallery", self.window.toolbar.buttons)
        self.assertTrue(self.window.gallery_button.isVisible())
        self.assertIs(self.window.gallery_button.defaultAction(), action)
        self.assertTrue(action.isEnabled())
        before = [run.result for run in self.window.project.runs]
        self.window.gallery_button.click()
        self.pump(0.3)
        gallery = self.window.gallery
        view = self.window.findChild(QListView, "sheetGallery")
        self.assertIs(view, gallery.view)
        self.assertTrue(view.isVisible())
        self.assertEqual(view.model().rowCount(), 5)
        self.assertEqual([tuple(view.model().index(row, 0).data(Qt.ItemDataRole.UserRole)) for row in range(5)],
                         [("graph", 0), ("graph", 1), ("graph", 2), ("layout", 0), ("layout", 1)])
        self.assertEqual(view.model().index(0, 0).data(Qt.ItemDataRole.DisplayRole), "Calibrazione $ A")
        self.assertEqual(gallery.kinds.tabText(0), "All (5)")
        self.assertEqual(gallery.kinds.tabText(1), "Graphs (3)")
        self.assertEqual(gallery.kinds.tabText(2), "Layouts (2)")
        self.assertTrue(all(run.result is a for run, a in zip(self.window.project.runs, before)))
        self.assertTrue(all(run.result is None for run in self.window.project.runs))  # No calculation was asked.
        self.assertFalse(self.window.project.dirty)
        self.assertIn("Not calculated", view.model().index(0, 0).data(Qt.ItemDataRole.ToolTipRole))

    def test_search_enter_opens_the_graph_and_calculates_it_the_ordinary_way(self):
        self.open_fixture()
        gallery = self.open_gallery()
        search = self.window.findChild(QLineEdit, "gallerySearch")
        search.setText("Calibrazione $")
        self.pump(0.2)
        view = gallery.view
        self.assertEqual(view.model().rowCount(), 1)
        found = view.model().index(0, 0)
        self.assertEqual(tuple(found.data(Qt.ItemDataRole.UserRole)), ("graph", 0))
        view.setCurrentIndex(found)
        view.setFocus()
        QTest.keyClick(view, Qt.Key.Key_Return)
        self.wait()
        self.assertIsNone(self.window.gallery)
        self.assertEqual(self.window.selected, ("graph", 0))
        self.assertIsNotNone(self.window.project.runs[0].result.figure)
        self.assertIsNone(self.window.project.runs[1].result)  # Only the opened sheet was calculated.
        self.assertFalse(self.window.project.dirty)

    def test_enter_in_the_search_field_opens_the_first_match(self):
        self.open_fixture()
        gallery = self.open_gallery()
        gallery.search.setFocus()
        QTest.keyClicks(gallery.search, "ripetizione")
        QTest.keyClick(gallery.search, Qt.Key.Key_Return)
        self.wait()
        self.assertEqual(self.window.selected, ("graph", 1))

    def test_a_layout_opens_as_a_layout(self):
        self.open_fixture()
        gallery = self.open_gallery()
        QTest.keyClicks(gallery.search, "sintesi")
        self.pump(0.2)
        index = gallery.view.model().index(0, 0)
        self.assertEqual(tuple(index.data(Qt.ItemDataRole.UserRole)), ("layout", 1))
        gallery.view.setCurrentIndex(index)
        gallery.view.activated.emit(index)
        self.wait()
        self.assertEqual(self.window.selected, ("layout", 1))
        self.assertIsNotNone(self.window.project.layout_figure(self.window.project.layouts[1]))
        self.assertEqual(len(self.window.page.canvases), 1)  # The layout page, with its composed figure.

    def test_double_click_opens_a_card(self):
        self.open_fixture()
        gallery = self.open_gallery()
        view = gallery.view
        index = view.model().index(2, 0)
        point = view.visualRect(index).center()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        self.wait()
        self.assertEqual(self.window.selected, ("graph", 2))

    def test_arrow_keys_move_between_cards(self):
        self.open_fixture()
        gallery = self.open_gallery()
        view = gallery.view
        view.setFocus()
        view.setCurrentIndex(view.model().index(0, 0))
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertEqual(view.currentIndex().row(), 1)
        QTest.keyClick(view, Qt.Key.Key_End)
        self.assertEqual(view.currentIndex().row(), 4)
        QTest.keyClick(view, Qt.Key.Key_Home)
        self.assertEqual(view.currentIndex().row(), 0)

    def test_escape_returns_to_the_worksheet_with_its_selection_and_focus(self):
        self.open_fixture()
        sheet = self.window.sheet
        sheet.setCurrentIndex(sheet.model().index(2, 1))
        sheet.setFocus()
        self.assertEqual(self.window.selected, ("data", "Misure"))
        gallery = self.open_gallery()
        self.assertTrue(gallery.view.hasFocus() or gallery.view.isAncestorOf(self.app.focusWidget()))
        QTest.keyClick(gallery.view, Qt.Key.Key_Escape)
        self.assertIsNone(self.window.gallery)
        self.assertEqual(self.window.selected, ("data", "Misure"))
        self.assertIs(self.window.sheet, sheet)  # The same worksheet, not a rebuilt one.
        self.assertEqual((sheet.currentIndex().row(), sheet.currentIndex().column()), (2, 1))
        self.assertTrue(sheet.isVisible())
        self.assertIs(self.window.focusWidget(), sheet)

    def test_escape_in_the_search_box_goes_back_and_ctrl_f_comes_to_it(self):
        self.open_fixture()
        sheet = self.window.sheet
        sheet.setFocus()
        gallery = self.open_gallery()
        gallery.view.setFocus()
        QTest.keyClick(gallery.view, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(gallery.search.hasFocus())
        QTest.keyClicks(gallery.search, "ab")
        QTest.keyClick(gallery.search, Qt.Key.Key_Backspace)  # Editing keys stay in the box.
        self.assertEqual(gallery.search.text(), "a")
        self.assertIsNotNone(self.window.gallery)
        QTest.keyClick(gallery.search, Qt.Key.Key_Escape)
        self.assertIsNone(self.window.gallery)
        self.assertIs(self.window.sheet, sheet)

    def test_back_button_returns_to_a_graph_with_its_canvas(self):
        self.open_fixture()
        self.window.open_sheet(("graph", 1))
        self.wait()
        gallery = self.open_gallery()
        self.assertEqual(tuple(gallery.current_entry().ref), ("graph", 1))  # The sheet it came from is current.
        self.assertFalse(self.window.actions["recalculate"].isEnabled())  # The gallery shows no sheet.
        self.assertFalse(self.window.gallery_button.isVisible())
        gallery.back.click()
        self.assertIsNone(self.window.gallery)
        self.assertTrue(self.window.gallery_button.isVisible())
        self.assertEqual(self.window.selected, ("graph", 1))
        self.assertEqual(len(self.window.page.canvases), 1)
        self.assertIs(self.window.focusWidget(), self.window.page.canvases[0])
        self.assertTrue(self.window.actions["recalculate"].isEnabled())

    def test_the_gallery_opens_and_closes_from_the_home_page_and_with_the_shortcut_action(self):
        gallery = self.open_gallery()
        self.assertEqual(gallery.model.rowCount(), 0)
        self.assertFalse(gallery.notice.isHidden())
        self.assertIn("Ctrl+G", gallery.notice.text())  # Instructions that work from the keyboard.
        self.assertIn("Esc", gallery.notice.text())
        self.window.actions["gallery"].trigger()  # The same action closes it again.
        self.assertIsNone(self.window.gallery)
        self.assertIsNone(self.window.selected)

    def test_filters_are_view_state_remembered_but_never_saved(self):
        self.open_fixture()
        gallery = self.open_gallery()
        gallery.kinds.setCurrentIndex(2)
        gallery.search.setText("piastra")
        self.pump(0.1)
        self.assertEqual(gallery.model.rowCount(), 1)
        self.assertEqual(gallery.count.text(), "1 of 2 sheets")
        self.assertFalse(self.window.project.dirty)
        gallery.closed.emit()
        again = self.open_gallery()
        self.assertEqual((again.kinds.currentIndex(), again.search.text()), (2, "piastra"))
        self.assertEqual(again.model.rowCount(), 1)
        again.search.setText("zzz")
        self.pump(0.1)
        self.assertEqual(again.model.rowCount(), 0)
        self.assertFalse(again.notice.isHidden())
        self.assertIn("zzz", again.notice.text())
        again.closed.emit()
        self.window.project.dirty = False
        self.assertTrue(self.window.close_project())
        self.window.open_path(FIXTURE)  # A newly opened project starts with empty filters.
        self.wait()
        fresh = self.open_gallery()
        self.assertEqual((fresh.kinds.currentIndex(), fresh.search.text()), (0, ""))
        self.assertFalse(self.window.project.dirty)

    def test_previews_follow_data_and_format_changes_and_recalculation(self):
        self.open_fixture(calculate=True)
        gallery = self.open_gallery()
        self.visit_all_cards()
        entry = next(entry for entry in gallery.entries if entry.ref == ("graph", 0))
        first = gallery.service.cache.get(entry)
        self.assertIsNotNone(first)
        drawn = gallery.service.drawn
        self.assertGreaterEqual(drawn, 5)
        # A changed cell recalculates its analyses while the gallery stays open.
        affected = self.window.project.paste("Misure", 0, 1, [["50"]], "Edit cell")
        self.window.refresh_runs(affected)
        self.wait()
        self.settle_previews()
        entry_after = next(entry for entry in gallery.entries if entry.ref == ("graph", 0))
        second = gallery.service.cache.get(entry_after)
        self.assertIsNotNone(second)
        self.assertIsNot(second, first)
        self.assertNotEqual(first.pixmap.toImage(), second.pixmap.toImage())
        # Format Graph: the same figure with another style.
        run = self.window.project.runs[0]
        style, _ = self.window.project.format_inputs(run)
        style["title"] = "Changed title"
        before = gallery.service.cache.get(entry_after)
        self.assertIsNotNone(before)
        self.window.project.apply_format(run, style)
        self.window.refresh()
        self.settle_previews()
        entry_styled = next(entry for entry in gallery.entries if entry.ref == ("graph", 0))
        third = gallery.service.cache.get(entry_styled)
        self.assertIsNot(third, before)
        self.assertNotEqual(before.pixmap.toImage(), third.pixmap.toImage())

    def test_gallery_does_not_change_the_export_of_a_graph_or_a_layout(self):
        from trama_qt.window import export_graph
        self.open_fixture(calculate=True)
        project = self.window.project
        before_graph, before_layout = self.folder / "graph-before.png", self.folder / "layout-before.png"
        export_graph(project.runs[0].result.figure, before_graph)
        project.export_layout(project.layouts[0], before_layout)
        self.open_gallery()
        self.visit_all_cards()
        self.assertGreaterEqual(self.window.gallery.service.drawn, 5)
        self.window.close_gallery()
        after_graph, after_layout = self.folder / "graph-after.png", self.folder / "layout-after.png"
        export_graph(project.runs[0].result.figure, after_graph)
        project.export_layout(project.layouts[0], after_layout)
        self.assertEqual(before_graph.read_bytes(), after_graph.read_bytes())
        self.assertEqual(before_layout.read_bytes(), after_layout.read_bytes())

    def test_a_failed_calculation_is_a_card_that_says_so_and_opens_normally(self):
        self.open_fixture()
        project = self.window.project
        project.runs[1].options["Y columns"] = ["Missing column"]
        gallery = self.open_gallery()
        QTest.keyClicks(gallery.search, "ripetizione")
        self.pump(0.2)
        index = gallery.view.model().index(0, 0)
        gallery.view.activated.emit(index)  # The ordinary calculation fails: status, not a dialog.
        self.wait()
        self.assertIsNone(project.runs[1].result)
        self.assertTrue(project.runs[1].calculation_error)
        self.assertEqual(self.window.selected, ("graph", 1))
        gallery = self.open_gallery()
        state = {entry.ref: entry.state for entry in gallery.entries}
        self.assertEqual(state[("graph", 1)], "error")
        self.assertEqual(state[("layout", 0)], "error")
        card = next(row for row in range(gallery.model.rowCount())
                    if gallery.model.entry(row).ref == ("graph", 1))
        self.assertIn("Calculation failed", gallery.model.index(card).data(Qt.ItemDataRole.ToolTipRole))
        self.assertIsNone(gallery.model.index(card).data(Qt.ItemDataRole.UserRole + 2))  # No preview to draw.

    def test_the_gallery_disables_drawing_and_history_on_the_hidden_graph(self):
        self.open_fixture(calculate=True)
        window = self.window
        window.open_sheet(("graph", 0))
        self.wait()
        self.assertTrue(window.actions["draw"].isEnabled())
        gallery = self.open_gallery()
        self.assertFalse(window.actions["draw"].isEnabled())
        self.assertFalse(window.actions["undo"].isEnabled())
        with mock.patch.object(window.project, "undo") as undo:
            window.undo()
        undo.assert_not_called()
        gallery.closed.emit()
        self.assertTrue(window.actions["draw"].isEnabled())

    def test_a_new_project_removes_the_gallery_and_its_previews(self):
        self.open_fixture(calculate=True)
        gallery = self.open_gallery()
        self.visit_all_cards()
        service = gallery.service
        self.assertGreaterEqual(len(service.cache), 5)
        self.window.project.dirty = False
        self.window.new_project()
        self.assertIsNone(self.window.gallery)
        self.assertEqual(len(service.cache), 0)
        self.assertEqual(len(service.queue), 0)
        self.assertIsNone(service.task)

    def test_a_gallery_that_outlives_its_project_forgets_the_old_previews(self):
        from trama_qt.gallery import GalleryPage
        project = [fixture_project(calculated=True)]
        page = GalleryPage(lambda: project[0], lambda: False, {"kind": None, "text": ""})
        page.resize(900, 600)
        page.show()
        self.addCleanup(page.dispose)
        end = time.monotonic() + 20
        while len(page.service.cache) < 5 and time.monotonic() < end:
            page.scan()
            self.app.processEvents()
            time.sleep(0.01)
        self.assertEqual(len(page.service.cache), 5)
        project[0] = fixture_project()  # Another project, nothing calculated.
        page.sync()
        self.assertEqual(len(page.service.cache), 0)
        self.assertEqual(page.model.rowCount(), 5)
        self.assertTrue(all(page.model.entry(row).state == "pending" for row in range(5)))

    def test_only_the_visible_cards_are_drawn_and_the_cache_is_bounded(self):
        from trama_qt.gallery import GalleryPage
        project = many_graphs(120)
        page = GalleryPage(lambda: project, lambda: False, {"kind": None, "text": ""})
        page.resize(900, 560)
        page.show()
        self.addCleanup(page.dispose)

        def settle(timeout=30):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                self.pump(0.1)
                shown = [entry for entry in page.visible_entries() if entry.previewable]
                if (page.service.task is None and not page.service.queue and not page._scan_timer.isActive()
                        and all(page.service.cache.get(entry) is not None for entry in shown)):
                    return shown
            self.fail("previews were not drawn")

        shown = settle()
        self.assertTrue(0 < len(shown) < 30, len(shown))
        self.assertLessEqual(page.service.drawn, len(shown))  # Nothing beyond the screen.
        bar = page.view.verticalScrollBar()
        for position in range(0, bar.maximum() + 1, max(1, bar.maximum() // 40)):  # Dragging the scroll bar.
            bar.setValue(position)
            self.app.processEvents()
        bar.setValue(bar.maximum())
        shown = settle()
        self.assertLess(page.service.drawn, 60)  # Scrolling past 120 cards does not draw 120 previews.
        self.assertLessEqual(len(page.service.cache), page.service.cache.limit)
        self.assertTrue(all(page.service.cache.get(entry) is not None for entry in shown))

    def test_italian_and_dark_theme_and_a_small_window(self):
        from analisi.i18n import set_language
        from trama_qt import theme
        set_language("it")
        self.open_fixture(calculate=True)
        self.window.resize(930, 650)
        gallery = self.open_gallery()
        self.assertEqual(gallery.kinds.tabText(1), "Grafici (3)")
        self.assertEqual(gallery.back.text(), "Torna al foglio")
        self.assertEqual(gallery.search.placeholderText(), "Cerca per nome")
        self.assertEqual(gallery.count.text(), "5 di 5 fogli")
        self.settle_previews()
        for dark in (True, False):
            theme.apply(self.app, dark=dark)
            self.pump(0.1)
            image = gallery.grab().toImage()
            self.assertFalse(image.isNull())
            self.assertFalse(gallery.view.horizontalScrollBar().isVisible())
        self.assertGreaterEqual(gallery.view.viewport().width(), gallery.view.itemDelegate().sizeHint(
            QStyleOptionViewItem(), gallery.model.index(0)).width())
        self.assertGreaterEqual(len(gallery.visible_entries()), 1)

    def test_states_are_written_as_words_on_every_card(self):
        from trama_qt.gallery import description, label
        from trama_qt.gallery_catalog import catalog
        project = fixture_project(calculated=True)
        project.runs[0].calculation_error = "Updating 1 linked result(s)…"
        project.runs[1].result, project.runs[1].calculation_error = None, "Boom"
        project.runs[2].result = None
        entries = {entry.ref: entry for entry in catalog(project)}
        self.assertEqual(label(entries[("graph", 0)]), "Graph · Out of date")
        self.assertEqual(label(entries[("graph", 1)]), "Graph · Calculation failed")
        self.assertEqual(label(entries[("graph", 2)]), "Graph · Not calculated")
        self.assertEqual(label(entries[("layout", 0)]), "Layout · Calculation failed")
        self.assertIn("Boom", description(entries[("graph", 1)]))


if __name__ == "__main__":
    unittest.main()
