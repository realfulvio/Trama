"""Vetro look for the Qt interface: colour tokens, Figtree, Lucide icons and one style sheet."""
from functools import lru_cache
from pathlib import Path
import sys

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QScrollArea, QVBoxLayout, QWidget


def asset_root():
    """assets/ next to the sources, or inside the PyInstaller bundle."""
    bundle = getattr(sys, "_MEIPASS", None)
    candidates = [Path(__file__).resolve().parent.parent / "assets"]
    if bundle:
        candidates.insert(0, Path(bundle) / "assets")
    return next((path for path in candidates if path.is_dir()), candidates[-1])


ASSETS = asset_root()
QT_ASSETS = ASSETS / "qt"

LIGHT = dict(bg="#EEF2F4", panel="#FFFFFF", panel2="#F7F9FA", border="#E1E6EA", text="#17242D",
             text2="#5A6873", text3="#8A97A0", accent="#0B7A73", accent_dark="#075E58", tint="#E2F2EF",
             field="#CFD7DC", hover="#EDF2F3", on_accent="#FFFFFF", grid="#EDF1F3", scroll="#C9D2D7",
             warning_bg="#FBEFE9", warning="#7A2E12", error_bg="#FDECEC", error="#A3262A", header="#F4F7F8")
DARK = dict(bg="#0D1417", panel="#152025", panel2="#18252B", border="#22323A", text="#E3EBEE",
            text2="#9BABB3", text3="#6F808A", accent="#35B8AC", accent_dark="#6AD3C9", tint="#123936",
            field="#2E424B", hover="#1D2C32", on_accent="#FFFFFF", grid="#1E2B31", scroll="#33464E",
            warning_bg="#3A2319", warning="#F3B79E", error_bg="#3B1C1F", error="#F2A7A9", header="#18252B")

T = dict(LIGHT)
FAMILY = ["Segoe UI"]


def color(key):
    return QColor(T[key])


def load_fonts():
    """Register Figtree (OFL) and return the family used by the interface."""
    family = None
    for path in sorted((QT_ASSETS / "fonts").glob("Figtree-*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0 and family is None:
            families = QFontDatabase.applicationFontFamilies(font_id)
            family = families[0] if families else None
    if family:
        FAMILY[0] = family
    return FAMILY[0]


def font(points=9.5, weight=QFont.Weight.Normal):
    result = QFont(FAMILY[0])
    result.setPointSizeF(points)
    result.setWeight(weight)
    return result


@lru_cache(maxsize=512)
def _icon_pixmap(name, colour, size, ratio):
    path = QT_ASSETS / "icons" / f"{name}.svg"
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:
        return QPixmap()
    svg = svg.replace('stroke="currentColor"', f'stroke="{colour}"').replace('stroke-width="2"', 'stroke-width="1.75"')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon(name, colour=None, size=18):
    """A Lucide icon drawn in the text colour (or ``colour``), sharp at the screen's scale."""
    app = QApplication.instance()
    ratio = max(1.0, app.devicePixelRatio()) if app is not None else 1.0
    result = QIcon()
    result.addPixmap(_icon_pixmap(name, colour or T["text"], size, ratio))
    disabled = _icon_pixmap(name, T["text3"], size, ratio)
    result.addPixmap(disabled, QIcon.Mode.Disabled)
    return result


def icon_size(size=18):
    return QSize(size, size)


def palette():
    result = QPalette()
    roles = QPalette.ColorRole
    for role, key in ((roles.Window, "bg"), (roles.Base, "panel"), (roles.AlternateBase, "panel2"),
                      (roles.Text, "text"), (roles.WindowText, "text"), (roles.Button, "panel"),
                      (roles.ButtonText, "text"), (roles.Highlight, "tint"), (roles.HighlightedText, "text"),
                      (roles.ToolTipBase, "panel"), (roles.ToolTipText, "text"), (roles.PlaceholderText, "text3"),
                      (roles.Link, "accent")):
        result.setColor(role, color(key))
    result.setColor(QPalette.ColorGroup.Disabled, roles.Text, color("text3"))
    result.setColor(QPalette.ColorGroup.Disabled, roles.WindowText, color("text3"))
    result.setColor(QPalette.ColorGroup.Disabled, roles.ButtonText, color("text3"))
    return result


def stylesheet():
    t = T
    return f"""
    QMainWindow, QDialog {{ background: {t['bg']}; }}
    QWidget {{ color: {t['text']}; }}
    QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 5px 8px; }}
    QFrame#card {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QFrame#commandBar {{ background: {t['panel']}; border-bottom: 1px solid {t['border']}; }}
    QLabel#pageTitle {{ font-size: 15pt; font-weight: 700; }}
    QLabel#pageSubtitle, QLabel#muted {{ color: {t['text2']}; }}
    QLabel#sectionTitle {{ color: {t['text2']}; font-weight: 600; }}
    QLabel#notice {{ background: {t['warning_bg']}; color: {t['warning']}; border-radius: 6px; padding: 7px 10px; }}
    QLabel#errorBanner {{ background: {t['error_bg']}; color: {t['error']}; border-radius: 6px; padding: 7px 10px; }}
    QTabBar#ribbonTabs::tab {{ background: transparent; border: none; padding: 7px 13px 6px 13px;
        color: {t['text2']}; margin-right: 2px; }}
    QTabBar#ribbonTabs::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; font-weight: 600; }}
    QTabBar#ribbonTabs::tab:hover {{ color: {t['text']}; }}
    QToolButton {{ border: none; border-radius: 6px; padding: 5px 8px; background: transparent; }}
    QToolButton:hover {{ background: {t['hover']}; }}
    QToolButton:pressed, QToolButton:checked {{ background: {t['tint']}; }}
    QToolButton:disabled {{ color: {t['text3']}; }}
    QToolButton#primary {{ background: {t['accent']}; color: {t['on_accent']}; padding: 5px 12px; font-weight: 600; }}
    QToolButton#primary:hover {{ background: {t['accent_dark']}; }}
    QToolButton#primary:disabled {{ background: {t['field']}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QPushButton {{ background: {t['panel']}; border: 1px solid {t['field']}; border-radius: 6px; padding: 6px 14px; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:default, QPushButton#primary {{ background: {t['accent']}; color: {t['on_accent']}; border-color: {t['accent']};
        font-weight: 600; }}
    QPushButton:default:hover, QPushButton#primary:hover {{ background: {t['accent_dark']}; }}
    QPushButton:disabled {{ color: {t['text3']}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: {t['panel']};
        border: 1px solid {t['field']}; border-radius: 6px; padding: 4px 8px;
        selection-background-color: {t['tint']}; selection-color: {t['text']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {t['accent']}; }}
    QComboBox QAbstractItemView {{ background: {t['panel']}; border: 1px solid {t['border']};
        selection-background-color: {t['tint']}; selection-color: {t['text']}; outline: 0; }}
    QListWidget, QTreeWidget {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 6px;
        outline: 0; }}
    QListWidget::item {{ padding: 3px 4px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {t['tint']}; color: {t['text']}; }}
    QTreeWidget#navigator {{ border: none; background: transparent; }}
    QTreeWidget#navigator::item {{ padding: 4px 2px; border-radius: 6px; }}
    QTreeWidget#navigator::item:hover {{ background: {t['hover']}; }}
    QTreeWidget#navigator::item:selected {{ background: {t['tint']}; color: {t['accent_dark']}; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {t['border']}; }}
    QTabBar::tab {{ background: transparent; padding: 6px 12px; border: none; color: {t['text2']}; }}
    QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
    QTableView {{ background: {t['panel']}; border: none; gridline-color: {t['grid']};
        selection-background-color: {t['tint']}; selection-color: {t['text']}; outline: 0; }}
    QHeaderView::section {{ background: {t['header']}; color: {t['text2']}; border: none;
        border-right: 1px solid {t['grid']}; border-bottom: 1px solid {t['border']}; padding: 3px 6px; }}
    QTableView QTableCornerButton::section {{ background: {t['header']}; border: none;
        border-bottom: 1px solid {t['border']}; border-right: 1px solid {t['grid']}; }}
    QScrollBar:vertical {{ width: 11px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['scroll']}; border-radius: 3px; min-height: 28px; }}
    QScrollBar:horizontal {{ height: 11px; background: transparent; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['scroll']}; border-radius: 3px; min-width: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle {{ background: {t['bg']}; }}
    QStatusBar {{ background: {t['bg']}; color: {t['text2']}; }}
    QStatusBar::item {{ border: none; }}
    QProgressBar {{ background: {t['border']}; border: none; border-radius: 3px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
    QMenu {{ background: {t['panel']}; border: 1px solid {t['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {t['hover']}; }}
    QMenu::item:disabled {{ color: {t['text3']}; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    """


def keep_on_screen(window):
    """Shrink and move a top-level window into the available area of its screen (small screens at 150%).

    Unbound QWidget calls: some dialogs keep fields called ``width`` or ``size``.
    """
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    frame = window.frameGeometry()
    inner = QWidget.size(window)
    extra_w, extra_h = frame.width() - inner.width(), frame.height() - inner.height()
    width = min(inner.width(), area.width() - extra_w)
    height = min(inner.height(), area.height() - extra_h)
    if (width, height) != (inner.width(), inner.height()):
        QWidget.resize(window, max(width, 1), max(height, 1))
        frame = window.frameGeometry()
    x = min(max(frame.x(), area.left()), area.right() + 1 - frame.width())
    y = min(max(frame.y(), area.top()), area.bottom() + 1 - frame.height())
    if (x, y) != (frame.x(), frame.y()):
        QWidget.move(window, max(x, area.left()), max(y, area.top()))


class FitScrollArea(QScrollArea):
    """Asks for the full size of its content, scrolls vertically only when the screen is too short."""

    def _bar(self):
        return self.verticalScrollBar().sizeHint().width()

    def sizeHint(self):
        content = self.widget()
        if content is None:
            return super().sizeHint()
        hint = content.sizeHint()
        return QSize(hint.width() + self._bar(), hint.height())

    def minimumSizeHint(self):
        content = self.widget()
        if content is None:
            return super().minimumSizeHint()
        return QSize(content.minimumSizeHint().width() + self._bar(), min(160, content.minimumSizeHint().height()))


def scroll_body(dialog):
    """The layout for a dialog's fields, inside a vertical scroll area; add the buttons to ``dialog.layout()``."""
    root = QVBoxLayout(dialog)
    area = FitScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    area.setWidget(body)
    root.addWidget(area, 1)
    return layout


class _DialogsOnScreen(QObject):
    """Every dialog, when shown, fits the screen it opens on: its size hint or resize() can exceed it."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog) and watched.isWindow():
            keep_on_screen(watched)
        return False


_ON_SCREEN = _DialogsOnScreen()


_TRANSLATOR = None


def install_qt_translations(app, language):
    """Qt's own texts (standard buttons of message boxes, file dialogs) in the active language, when the
    translations shipped with PySide6 are present; English otherwise."""
    from PySide6.QtCore import QLibraryInfo, QTranslator
    global _TRANSLATOR
    if _TRANSLATOR is not None:
        app.removeTranslator(_TRANSLATOR)
        _TRANSLATOR = None
    if language == "en":
        return
    translator = QTranslator(app)
    if translator.load(f"qtbase_{language}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        _TRANSLATOR = translator


def apply(app, *, dark=False):
    app.removeEventFilter(_ON_SCREEN)
    app.installEventFilter(_ON_SCREEN)
    T.clear()
    T.update(DARK if dark else LIGHT)
    _icon_pixmap.cache_clear()
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setFont(font())
    app.setStyleSheet(stylesheet())
