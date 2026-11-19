"""The gallery of graphs and layouts on Qt: cards with a preview, a state and a literal search.

``GalleryModel`` lists the cards that ``gallery_catalog`` finds, ``CardDelegate`` paints them and
``GalleryPage`` is the view the main window shows in place of a sheet. Opening a card goes through the
standard navigation of the window (``MainWindow.open_sheet``), so a sheet without a result is calculated the
ordinary way, with its errors and its Cancel. The gallery itself never calculates, never changes the project
and never marks it as modified; its filters are a state of the view.
"""
from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QPushButton, QStyle,
                               QStyledItemDelegate, QTabBar, QVBoxLayout, QWidget)

from analisi.i18n import active_language

from . import theme
from .flow import FlowLayout
from .gallery_catalog import ERROR, GRAPH, KINDS, LAYOUT, PENDING, READY, STALE, catalog, visible
from .gallery_thumbs import ThumbnailService

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
THUMB_ROLE = Qt.ItemDataRole.UserRole + 2
PREVIEW = QSize(232, 140)  # Logical pixels; previews are drawn at the screen's device pixel ratio.
PAD, GAP, LINE_GAP = 8, 4, 3
SCAN_MS = 40  # Scrolling waits this long before the visible cards are asked for.

_TEXT = {
    "action": ("Gallery", "Galleria"),
    "tip": ("Browse every graph and layout of the project as cards",
            "Sfoglia tutti i grafici e i layout del progetto come schede"),
    "title": ("Gallery", "Galleria"),
    "all": ("All", "Tutti"),
    "graphs": ("Graphs", "Grafici"),
    "layouts": ("Layouts", "Layout"),
    "search": ("Search by name", "Cerca per nome"),
    "back": ("Back to sheet", "Torna al foglio"),
    "list": ("Graphs and layouts", "Grafici e layout"),
    "count": ("{shown} of {total} sheets", "{shown} di {total} fogli"),
    "help": ("Arrow keys move, Enter opens, Esc goes back, Ctrl+F searches.",
             "Frecce per spostarti, Invio per aprire, Esc per tornare, Ctrl+F per cercare."),
    "kind.graph": ("Graph", "Grafico"),
    "kind.layout": ("Layout", "Layout"),
    "state.ready": ("Ready", "Pronto"),
    "state.pending": ("Not calculated", "Non calcolato"),
    "state.stale": ("Out of date", "Obsoleto"),
    "state.error": ("Calculation failed", "Calcolo non riuscito"),
    "hole.pending": ("No result yet. Open the sheet to calculate it.",
                     "Nessun risultato. Apri il foglio per calcolarlo."),
    "hole.error": ("The last calculation failed. Open the sheet to see why.",
                   "L'ultimo calcolo non è riuscito. Apri il foglio per vedere il motivo."),
    "hole.loading": ("Preparing the preview…", "Preparo l'anteprima…"),
    "hole.failed": ("Preview not available. The sheet opens normally.",
                    "Anteprima non disponibile. Il foglio si apre normalmente."),
    "empty": ("There are no graphs or layouts in this project yet. Create a graph from a data table with "
              "Ctrl+G, then open the gallery again with Ctrl+Shift+G. Esc returns to the sheet.",
              "In questo progetto non ci sono ancora grafici o layout. Crea un grafico da una tabella con Ctrl+G, "
              "poi riapri la galleria con Ctrl+Maiusc+G. Esc torna al foglio."),
    "no_match": ("No sheet matches “{text}”. Edit or clear the search to see more. Esc returns to the sheet.",
                 "Nessun foglio corrisponde a «{text}». Modifica o svuota la ricerca per vederne altri. "
                 "Esc torna al foglio."),
    "failed": ("The gallery could not list the sheets: {error}. Esc returns to the sheet.",
               "La galleria non ha potuto elencare i fogli: {error}. Esc torna al foglio."),
    "same_name": ("{ordinal} of {total} with this name", "{ordinal} di {total} con questo nome"),
    "panels": ("{count} panels", "{count} pannelli"),
}


def g(key, **values):
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


def label(entry):
    """``Graph 2/3 · Ready``: the kind, which one of several with the same name, and the state in words."""
    kind = g(f"kind.{entry.kind}") + (f" {entry.ordinal}/{entry.total}" if entry.ordinal else "")
    return f"{kind} · {g('state.' + entry.state)}"


def description(entry):
    """Everything a card says, for the tooltip and for screen readers."""
    parts = [entry.name, label(entry)]
    if entry.ordinal:
        parts.append(g("same_name", ordinal=entry.ordinal, total=entry.total))
    if entry.panels:
        parts.append(g("panels", count=entry.panels))
    if entry.detail:
        parts.append(entry.detail)
    return "\n".join(parts)


STATE_ICONS = {READY: "circle-check", PENDING: "circle-dashed", STALE: "triangle-alert", ERROR: "circle-x"}


class GalleryModel(QAbstractListModel):
    """The visible cards. ``UserRole`` is the reference the navigation of the window uses."""

    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self._entries = []

    def entry(self, row):
        return self._entries[row]

    def row_of(self, ref):
        return next((row for row, entry in enumerate(self._entries) if entry.ref == tuple(ref)), -1)

    def set_entries(self, entries):
        """Show ``entries``. The same cards in the same order only repaint, so scrolling and selection stay."""
        if [entry.ref for entry in entries] == [entry.ref for entry in self._entries]:
            self._entries = list(entries)
            if entries:
                self.dataChanged.emit(self.index(0), self.index(len(entries) - 1))
            return
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def touch(self, ref):
        row = self.row_of(ref)
        if row >= 0:
            self.dataChanged.emit(self.index(row), self.index(row))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.name
        if role == Qt.ItemDataRole.UserRole:
            return entry.ref
        if role == ENTRY_ROLE:
            return entry
        if role == THUMB_ROLE:
            return self.cache.get(entry) if entry.previewable else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return description(entry)
        if role in (Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.AccessibleDescriptionRole):
            return description(entry).replace("\n", ", ")
        return None


class CardDelegate(QStyledItemDelegate):
    """A card: the preview (or an explicit hole when there is none), the name and the state in words."""

    def sizeHint(self, option, index):
        line = option.fontMetrics.height()
        return QSize(PREVIEW.width() + 2 * PAD + 2 * GAP,
                     PREVIEW.height() + 2 * PAD + 2 * line + LINE_GAP + 6 + 2 * GAP)

    def paint(self, painter, option, index):
        entry = index.data(ENTRY_ROLE)
        if entry is None:
            return
        T = theme.T
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        line = option.fontMetrics.height()
        card = option.rect.adjusted(GAP, GAP, -GAP, -GAP)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(T["accent"] if selected else T["border"]), 2 if selected else 1))
        painter.setBrush(QColor(T["tint"] if selected else T["hover"] if hovered else T["panel"]))
        painter.drawRoundedRect(QRectF(card).adjusted(.5, .5, -.5, -.5), 8, 8)
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(T["accent_dark"]), 2, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(QRectF(card).adjusted(-1.5, -1.5, 1.5, 1.5), 9, 9)
        preview = QRect(card.left() + PAD, card.top() + PAD, card.width() - 2 * PAD, PREVIEW.height())
        self._preview(painter, option, entry, index.data(THUMB_ROLE), preview)
        text = card.left() + PAD, card.width() - 2 * PAD
        name = QRect(text[0], preview.bottom() + 7, text[1], line)
        painter.setPen(QColor(T["text"]))
        font = painter.font()
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(name, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                         painter.fontMetrics().elidedText(entry.name.replace("\n", " "), Qt.TextElideMode.ElideRight,
                                                          name.width()))
        font.setWeight(font.Weight.Normal)
        painter.setFont(font)
        state = QRect(text[0], name.bottom() + LINE_GAP, text[1], line)
        icon = theme.icon(STATE_ICONS[entry.state], T["text2"], 14)
        icon.paint(painter, QRect(state.left(), state.top() + (line - 14) // 2, 14, 14))
        painter.setPen(QColor(T["text2"]))
        painter.drawText(state.adjusted(19, 0, 0, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                         painter.fontMetrics().elidedText(label(entry), Qt.TextElideMode.ElideRight,
                                                          state.width() - 19))
        painter.restore()

    def _preview(self, painter, option, entry, thumb, rect):
        T = theme.T
        if thumb is not None and thumb.pixmap is not None:
            size = thumb.pixmap.deviceIndependentSize()
            width, height = min(size.width(), rect.width()), min(size.height(), rect.height())
            box = QRectF(rect.left() + (rect.width() - width) / 2, rect.top() + (rect.height() - height) / 2,
                         width, height)
            painter.fillRect(rect, QColor("#ffffff"))
            painter.drawPixmap(box, thumb.pixmap, QRectF(thumb.pixmap.rect()))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(T["border"]), 1))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            if entry.state == STALE:  # Words as well as colour: the preview shows the last calculation.
                band = QRect(rect.left(), rect.bottom() - option.fontMetrics.height() - 4, rect.width(),
                             option.fontMetrics.height() + 5)
                painter.fillRect(band, QColor(T["warning_bg"]))
                painter.setPen(QColor(T["warning"]))
                painter.drawText(band, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine,
                                 g("state.stale"))
            return
        if not entry.previewable:
            text, icon = g("hole.error" if entry.state == ERROR else "hole.pending"), STATE_ICONS[entry.state]
        elif thumb is not None:
            text, icon = g("hole.failed"), "triangle-alert"
        else:
            text, icon = g("hole.loading"), "gallery-thumbnails"
        painter.setBrush(QColor(T["panel2"]))
        painter.setPen(QPen(QColor(T["field"]), 1, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), 6, 6)
        theme.icon(icon, T["text2"], 24).paint(painter, QRect(rect.center().x() - 12, rect.top() + 20, 24, 24))
        painter.setPen(QColor(T["text2"]))
        painter.drawText(rect.adjusted(12, 52, -12, -8),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)


class GalleryView(QListView):
    """The list of cards. It says when the visible cards may have changed."""
    moved = Signal()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.moved.emit()

    def updateGeometries(self):
        """After every layout of the cards (a resize, a new scroll bar, another filter)."""
        super().updateGeometries()
        self.moved.emit()

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Resize:
            self.moved.emit()
        return super().viewportEvent(event)


class GalleryPage(QWidget):
    """Search, the Tutti/Grafici/Layout views and the cards, with Back to the sheet the gallery came from.

    ``project`` returns the project to show and ``busy`` tells whether a calculation is running (previews wait
    for it). ``state`` is the view state that the window remembers between two openings: it is never saved.
    """
    opened = Signal(tuple)
    closed = Signal()

    def __init__(self, project, busy, state, origin=None, parent=None):
        super().__init__(parent)
        self.setObjectName("galleryPage")
        self._project, self.state, self.origin = project, state, origin
        self._shown_project = None
        self.entries = []
        self.service = ThumbnailService(project, busy, self)
        self.model = GalleryModel(self.service.cache, self)
        self.service.ready.connect(self.model.touch)
        self.service.outdated.connect(self.schedule_scan)
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(SCAN_MS)
        self._scan_timer.timeout.connect(self.scan)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)
        title = QLabel(g("title"))
        title.setObjectName("pageTitle")
        root.addWidget(title)
        controls = QWidget()
        row = FlowLayout(controls, spacing=8)
        self.back = QPushButton(g("back"))
        self.back.setObjectName("galleryBack")
        self.back.setIcon(theme.icon("arrow-left", None, 16))
        self.back.clicked.connect(self.closed.emit)
        row.addWidget(self.back)
        self.kinds = QTabBar()
        self.kinds.setObjectName("galleryKinds")
        self.kinds.setDrawBase(False)
        self.kinds.setExpanding(False)
        self.kinds.setAccessibleName(g("title"))
        for _ in KINDS:
            self.kinds.addTab("")
        self.kinds.setCurrentIndex(KINDS.index(state.get("kind")) if state.get("kind") in KINDS else 0)
        self.kinds.currentChanged.connect(self._filter_changed)
        row.addWidget(self.kinds)
        self.search = QLineEdit(state.get("text", ""))
        self.search.setObjectName("gallerySearch")
        self.search.setPlaceholderText(g("search"))
        self.search.setAccessibleName(g("search"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.addAction(theme.icon("search", theme.T["text3"], 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter_changed)
        self.search.installEventFilter(self)
        row.addWidget(self.search)
        root.addWidget(controls)

        self.count = QLabel()
        self.count.setObjectName("galleryCount")
        root.addWidget(self.count)
        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        root.addWidget(self.notice)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        root.addWidget(self.problem)

        self.view = GalleryView()
        self.view.setObjectName("sheetGallery")
        self.view.setAccessibleName(g("list"))
        self.view.setAccessibleDescription(g("help"))
        self.view.setModel(self.model)
        self.view.setItemDelegate(CardDelegate(self.view))
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setMovement(QListView.Movement.Static)
        self.view.setLayoutMode(QListView.LayoutMode.SinglePass)
        self.view.setUniformItemSizes(True)
        self.view.setSpacing(0)
        self.view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setMouseTracking(True)
        self.view.activated.connect(self._activate)
        self.view.moved.connect(self.schedule_scan)
        root.addWidget(self.view, 1)
        hint = QLabel(g("help"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.setTabOrder(self.search, self.kinds)
        self.setTabOrder(self.kinds, self.view)
        self.setTabOrder(self.view, self.back)

        for sequence in (Qt.Key.Key_Escape, QKeySequence(QKeySequence.StandardKey.Back)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.closed.emit)
        find = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(self.focus_search)
        self.sync(select=origin)

    # -- the cards -------------------------------------------------------------------------------------
    def sync(self, select=None):
        """List the project again (after a recalculation, a style change or a new project)."""
        project = self._project()
        if project is not self._shown_project:  # Another project: no preview of the old one survives.
            self.service.clear()
            self._shown_project = project
        self.problem.hide()
        try:
            self.entries = catalog(project)
        except Exception as error:  # noqa: BLE001 - the gallery says what went wrong and stays usable by keyboard.
            self.entries = []
            self.problem.setText(g("failed", error=f"{type(error).__name__}: {error}"))
            self.problem.show()
        self.service.cache.prune({entry.ref for entry in self.entries})
        self._apply(select)

    def _apply(self, select=None):
        current = self.view.currentIndex()
        keep = tuple(select) if select is not None else (self.model.entry(current.row()).ref
                                                         if current.isValid() else None)
        kind, text = KINDS[self.kinds.currentIndex()], self.search.text()
        shown = visible(self.entries, kind, text)
        counts = [len(visible(self.entries, name)) for name in KINDS]
        for position, (name, total) in enumerate(zip(("all", "graphs", "layouts"), counts)):
            self.kinds.setTabText(position, f"{g(name)} ({total})")
        scroll = self.view.verticalScrollBar().value()
        self.model.set_entries(shown)
        self.view.verticalScrollBar().setValue(scroll)
        self.count.setText(g("count", shown=len(shown), total=counts[self.kinds.currentIndex()]))
        if shown:
            row = self.model.row_of(keep) if keep is not None else -1
            self.view.setCurrentIndex(self.model.index(max(row, 0)))
        self.notice.setVisible(not shown and self.problem.isHidden())
        if not shown:
            self.notice.setText(g("empty") if not self.entries else g("no_match", text=text.strip() or g("all")))
        self.schedule_scan()

    def _filter_changed(self, *_):
        self.state["kind"], self.state["text"] = KINDS[self.kinds.currentIndex()], self.search.text()
        self._apply()

    def current_entry(self):
        index = self.view.currentIndex()
        return self.model.entry(index.row()) if index.isValid() else None

    def _activate(self, index):
        if index.isValid():
            self.opened.emit(tuple(index.data(Qt.ItemDataRole.UserRole)))

    # -- previews --------------------------------------------------------------------------------------
    def schedule_scan(self):
        if not self._scan_timer.isActive():
            self._scan_timer.start()

    def visible_entries(self):
        """The cards that are on screen now."""
        viewport = self.view.viewport().rect()
        return [self.model.entry(row) for row in range(self.model.rowCount())
                if self.view.visualRect(self.model.index(row)).intersects(viewport)]

    def scan(self):
        """Ask for the previews of the cards that are visible, and only those."""
        if not self.isVisible():
            return
        ratio = self.view.devicePixelRatioF()
        self.service.request(self.visible_entries(), (round(PREVIEW.width() * ratio), round(PREVIEW.height() * ratio)),
                             ratio)

    # -- keyboard --------------------------------------------------------------------------------------
    def focus_first(self):
        (self.view if self.model.rowCount() else self.search).setFocus()

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.Type.KeyPress and self.model.rowCount():
            if event.key() == Qt.Key.Key_Down:
                self.view.setFocus()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                index = self.view.currentIndex() if self.view.currentIndex().isValid() else self.model.index(0)
                self._activate(index)
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_scan()

    def dispose(self):
        """The gallery is closing: stop drawing and let go of every preview and every result it held."""
        self._scan_timer.stop()
        self.service.stop()
        self.model.set_entries([])
        self.entries = []
        self._shown_project = None
