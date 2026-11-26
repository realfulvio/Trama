"""The Classica Qt palette, compact controls, screen fitting and scalable icons."""
import atexit
from functools import lru_cache
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import (QByteArray, QEasingCurve, QEvent, QObject, QPoint, QRect, QRectF, QSettings, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QIconEngine, QImage, QPainter, QPainterPath, QPalette,
                           QPixmap, QRegion)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame, QGraphicsBlurEffect, QGraphicsOpacityEffect,
                               QGraphicsPixmapItem, QGraphicsScene, QMainWindow, QMenu, QScrollArea, QTabBar,
                               QVBoxLayout, QWidget)

from analisi import ui_icons

from .strings import qt


def asset_root():
    """assets/ next to the sources, or inside the PyInstaller bundle."""
    bundle = getattr(sys, "_MEIPASS", None)
    candidates = [Path(__file__).resolve().parent.parent / "assets"]
    if bundle:
        candidates.insert(0, Path(bundle) / "assets")
    return next((path for path in candidates if path.is_dir()), candidates[-1])


ASSETS = asset_root()
QT_ASSETS = ASSETS / "qt"
WINDOWS = sys.platform == "win32"

LIGHT = dict(bg="#EEF1F4", panel="#FAFBFC", panel2="#F4F6F8", border="#D3DAE0", text="#1A2931",
             text2="#586874", text3="#A3AFB7", accent="#0A7C76", accent_dark="#075F5B", accent_hi="#14908A",
             tint="#DCEFED", field="#D3DAE0", field_hover="#B1BCC5", hover="#E8ECEF", on_accent="#FFFFFF",
             grid="#E1E6EA", scroll="#C9D2D7", scroll_hover="#A9B6BD", warning_bg="#FBEFE9", warning="#7A2E12",
             error_bg="#FDF2F1", error="#B3261E", header="#EEF1F4", icon_ink="#3A4E5A", icon_off="#7E8D98",
             group_ink="#465661", kind_data="#0A7C76", kind_result="#3F6498", kind_graph="#B0611A",
             setup_icon="#A9E3DD")
DARK = dict(bg="#0D1417", panel="#152025", panel2="#18252B", border="#22323A", text="#E3EBEE",
            text2="#9BABB3", text3="#6F808A", accent="#35B8AC", accent_dark="#6AD3C9", accent_hi="#4CC9BD",
            tint="#123936", field="#2E424B", field_hover="#445C66", hover="#1D2C32", on_accent="#04211E",
            grid="#1E2B31", scroll="#33464E", scroll_hover="#4A626C", warning_bg="#3A2319", warning="#F3B79E",
            error_bg="#3B1C1F", error="#F2A7A9", header="#18252B", icon_ink="#C3D0D6", icon_off="#7F929C",
            group_ink="#B6C4CB", kind_data="#4CC9BD", kind_result="#8DB0E0", kind_graph="#E5A765",
            setup_icon="#A9E3DD")
# Shadows under the panels (blur, vertical offset, opacity) and the veil over a window behind a modal dialog.
SHADOWS = {False: ((18, 5, 0.10), (3, 1, 0.06)), True: ((20, 6, 0.55), (3, 1, 0.35))}
SHADOW_RGB = {False: (18, 42, 52), True: (0, 0, 0)}
VEIL = {False: (16, 34, 42, 46), True: (0, 0, 0, 96)}

T = dict(LIGHT)
FAMILY = ["Segoe UI"]
MODES = ("system", "light", "dark")
DEFAULT_MODE = "light"
STATE = {"mode": DEFAULT_MODE, "dark": False, "connected": False}
CARD_RADIUS = 12
MENU_RADIUS = 8


class _Signals(QObject):
    changed = Signal()


SIGNALS = _Signals()


def fit_dialog(dialog, width, height):
    screen = dialog.screen()
    if screen is not None:
        bounds = screen.availableGeometry()
        width = min(width, max(1, bounds.width() - 32))
        height = min(height, max(1, bounds.height() - 48))
    dialog.resize(width, height)


def color(key):
    return QColor(T[key])


def load_fonts():
    """Use Segoe UI with the Windows font backend, and bundle a font for other backends."""
    if WINDOWS and QApplication.platformName() == "windows":
        FAMILY[0] = "Segoe UI"
        return FAMILY[0]
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


def table_font(points=9.5):
    """The interface font with tabular figures, so the digits of a column line up."""
    result = font(points)
    try:
        result.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):  # Qt before 6.7: proportional figures, nothing else changes.
        pass
    return result


# == icons ========================================================================================
def _resolve(colour, fallback="text"):
    """A colour token ("text2", "on_accent"...) or a literal colour; tokens follow the active theme."""
    colour = colour or fallback
    return T.get(colour, colour)


@lru_cache(maxsize=256)
def _svg_source(name, colour, stroke):
    path = QT_ASSETS / "icons" / f"{name}.svg"
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:
        return None
    svg = svg.replace('stroke="currentColor"', f'stroke="{colour}"').replace('stroke-width="2"',
                                                                             f'stroke-width="{stroke}"')
    return QByteArray(svg.encode("utf-8"))


@lru_cache(maxsize=1024)
def _icon_pixmap(name, colour, width, height, ratio, stroke=1.75):
    source = _svg_source(name, colour, stroke)
    pixmap = QPixmap(max(1, round(width * ratio)), max(1, round(height * ratio)))
    pixmap.fill(Qt.GlobalColor.transparent)
    if source is not None:
        side = min(pixmap.width(), pixmap.height())
        target = QRectF((pixmap.width() - side) / 2, (pixmap.height() - side) / 2, side, side)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(source).render(painter, target)
        painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class SvgIcon(QIconEngine):
    """A Lucide icon drawn from its SVG at the size and scale it is shown at (sharp on every monitor),
    in a colour token resolved when drawn, so it follows a change of theme."""

    def __init__(self, name, colour=None, disabled="text3"):
        super().__init__()
        self.name, self.colour, self.disabled = name, colour, disabled

    def clone(self):
        return SvgIcon(self.name, self.colour, self.disabled)

    def key(self):
        return "trama-svg"

    def isNull(self):
        return _svg_source(self.name, "#000", 1.75) is None

    def _pixmap(self, size, mode, ratio):
        colour = _resolve(self.disabled if mode == QIcon.Mode.Disabled else self.colour)
        return _icon_pixmap(self.name, colour, size.width(), size.height(), float(ratio))

    def pixmap(self, size, mode, state):
        return self._pixmap(size, mode, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        return self._pixmap(size, mode, scale)

    def paint(self, painter, rect, mode, state):
        device = painter.device()
        ratio = device.devicePixelRatioF() if device is not None else 1.0
        painter.drawPixmap(rect, self._pixmap(rect.size(), mode, ratio))


def icon(name, colour=None, size=18):  # noqa: ARG001 - size kept for callers; the engine draws any size.
    """A Lucide icon in the text colour or in ``colour`` (a token such as ``"text2"``, or a literal colour)."""
    return QIcon(SvgIcon(name, colour))


@lru_cache(maxsize=256)
def _classic_pixmap(name, size, ratio, ink, accent, background):
    source = ui_icons.render(name, max(1, round(size * ratio)), ink=ink, accent=accent, knockout=background)
    pixels = source.tobytes()
    image = QImage(pixels, source.width, source.height, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(image.copy())
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class ClassicIcon(SvgIcon):
    """Draw the original Classica artwork with the same renderer as Tk."""

    def clone(self):
        return ClassicIcon(self.name, self.colour, self.disabled)

    def key(self):
        return "trama-classica"

    def isNull(self):
        return self.name not in ui_icons.ICONS

    def _pixmap(self, size, mode, ratio):
        monochrome = self.disabled if mode == QIcon.Mode.Disabled else self.colour
        ink = _resolve(monochrome, "icon_ink")
        accent = _resolve(monochrome, "accent")
        return _classic_pixmap(self.name, min(size.width(), size.height()), float(ratio), ink, accent, T["panel2"])


def classic_icon(name, colour=None):
    return QIcon(ClassicIcon(name, colour, "icon_off"))


def icon_size(size=18):
    return QSize(size, size)


_UI_DIR = []


def _ui_image(name, colour, stroke=2.0):
    """An SVG for the style sheet (check mark, chevrons) in ``colour``, written once to a private folder."""
    if not _UI_DIR:
        folder = Path(tempfile.mkdtemp(prefix="trama-qt-"))
        atexit.register(shutil.rmtree, folder, True)
        _UI_DIR.append(folder)
    colour = _resolve(colour)
    path = _UI_DIR[0] / f"{name}-{colour.lstrip('#')}-{stroke}.svg"
    if not path.exists():
        source = _svg_source(name, colour, stroke)
        if source is not None:
            path.write_bytes(bytes(source))
    return path.as_posix()


def palette():
    result = QPalette()
    roles = QPalette.ColorRole
    for role, key in ((roles.Window, "bg"), (roles.Base, "panel"), (roles.AlternateBase, "panel2"),
                      (roles.Text, "text"), (roles.WindowText, "text"), (roles.Button, "panel"),
                      (roles.ButtonText, "text"), (roles.Highlight, "tint"), (roles.HighlightedText, "text"),
                      (roles.ToolTipBase, "panel"), (roles.ToolTipText, "text"), (roles.PlaceholderText, "text3"),
                      (roles.Link, "accent"), (roles.Light, "panel"), (roles.Midlight, "border"),
                      (roles.Mid, "field"), (roles.Dark, "field_hover"), (roles.Shadow, "text3")):
        result.setColor(role, color(key))
    result.setColor(QPalette.ColorGroup.Disabled, roles.Text, color("text3"))
    result.setColor(QPalette.ColorGroup.Disabled, roles.WindowText, color("text3"))
    result.setColor(QPalette.ColorGroup.Disabled, roles.ButtonText, color("text3"))
    return result


def stylesheet():
    t = T
    check = _ui_image("check", "on_accent", 3.2)
    dash = _ui_image("minus", "on_accent", 3.2)
    down, up = _ui_image("chevron-down", "text2", 2.2), _ui_image("chevron-up", "text2", 2.2)
    right = _ui_image("chevron-right", "text2", 2.2)
    down_off, up_off = _ui_image("chevron-down", "text3", 2.2), _ui_image("chevron-up", "text3", 2.2)
    primary = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {t['accent_hi']}, stop:1 {t['accent']})")
    return f"""
    QMainWindow, QDialog {{ background: {t['bg']}; }}
    QWidget {{ color: {t['text']}; }}
    QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 0px;
        padding: 5px 8px; }}
    QFrame#card {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 0px; }}
    QFrame#commandBar {{ background: {t['panel']}; border-bottom: 1px solid {t['border']}; }}
    QLabel#pageTitle {{ font-size: 16pt; font-weight: 700; }}
    QLabel#pageSubtitle, QLabel#muted {{ color: {t['text2']}; }}
    QLabel#sectionTitle {{ color: {t['text2']}; font-weight: 600; }}
    QFrame#projectStrip {{ background: {t['bg']}; }}
    QTabBar#projectTabs::tab {{ background: transparent; color: {t['text2']}; margin: 1px 1px 0 0;
        padding: 3px 7px; border: 1px solid transparent; border-bottom: none;
        border-top-left-radius: 0px; border-top-right-radius: 0px; min-width: 96px; }}
    QTabBar#projectTabs::tab:selected {{ background: {t['panel']}; color: {t['text']}; font-weight: 600;
        border-color: {t['border']}; }}
    QTabBar#projectTabs::tab:hover:!selected {{ background: {t['hover']}; color: {t['text']}; }}
    QToolButton#projectTabClose {{ padding: 2px; border-radius: 0px; }}
    QToolButton#projectTabClose:hover {{ background: {t['field']}; }}
    QToolButton#newProjectTab {{ margin: 1px 0 0 2px; padding: 2px; }}
    QLabel#notice {{ background: {t['warning_bg']}; color: {t['warning']}; border-radius: 0px; padding: 8px 12px; }}
    QLabel#errorBanner {{ background: {t['error_bg']}; color: {t['error']}; border-radius: 0px; padding: 8px 12px; }}

    QMenuBar {{ background: {t['panel2']}; border: 0; padding: 1px 3px; }}
    QMenuBar::item {{ background: transparent; padding: 3px 7px; }}
    QMenuBar::item:selected {{ background: {t['tint']}; color: {t['text']}; }}
    QFrame#classicToolbar {{ background: {t['panel2']}; border-bottom: 1px solid {t['border']}; }}
    QFrame#classicToolbar QToolButton {{ padding: 2px 3px; }}
    QFrame#classicToolbar QComboBox#toolbarFont, QFrame#classicToolbar QComboBox#toolbarSize {{
        padding: 1px 3px; }}
    QFrame#classicToolbar QComboBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
    QFrame#classicToolbar QToolButton#primary {{ padding: 2px 7px; background: {t['accent']}; }}
    QFrame#classicToolbar QToolButton#primary:disabled {{ background: {t['field']}; }}
    QFrame#classicDivider {{ color: {t['field_hover']}; }}
    QLabel#classicGroup {{ color: {t['group_ink']}; font-size: 9pt; }}
    QFrame#classicToolbar QToolButton:hover {{ background: {t['hover']}; border-color: {t['field']}; }}
    QFrame#classicToolbar QToolButton:pressed {{ background: {t['tint']}; border-color: {t['accent']}; }}
    QFrame#classicToolbar QToolButton:focus {{ border: 1px solid {t['accent']}; }}
    QFrame#classicToolbar QToolButton:disabled {{ color: {t['icon_off']}; }}
    QToolButton#pageAction {{ background: {t['panel']}; border: 1px solid {t['field']};
        border-bottom-color: {t['field_hover']}; padding: 4px 12px; }}
    QToolButton#pageAction:hover {{ background: {t['hover']}; border-color: {t['field_hover']}; }}
    QToolButton#pageAction:pressed {{ background: {t['tint']}; border-color: {t['accent']}; }}
    QToolButton#pageAction:checked {{ background: {t['tint']}; border-color: {t['accent']}; color: {t['accent_dark']}; }}
    QToolButton#pageAction:checked:hover {{ background: {t['tint']}; border-color: {t['accent_dark']}; }}
    QToolButton#pageAction:focus {{ border-color: {t['accent']}; }}
    QToolButton#pageAction:disabled {{ background: {t['panel2']}; border-color: {t['border']}; color: {t['icon_off']}; }}
    QLabel#infoBanner {{ background: {t['tint']}; color: {t['accent_dark']}; border-left: 3px solid {t['accent']};
        padding: 8px 12px; }}
    QToolButton:focus {{ border-color: {t['accent']}; }}
    QFrame#classicNavigator, QFrame#classicSheet {{ background: {t['panel']}; }}
    QFrame#setupSidebar {{ background: #102f3a; }}
    QFrame#setupSidebar QLabel {{ color: #d7edee; }}
    QFrame#setupSidebar QPushButton, QFrame#setupSidebar QToolButton {{ text-align: left; background: #153f4d; color: #fff; border-color: #476873; }}
    QFrame#setupSidebar QPushButton:hover, QFrame#setupSidebar QToolButton:hover {{ background: #25505c; }}
    QFrame#setupSidebar QToolButton:disabled {{ color: #a4bbc2; }}
    QListWidget#setupTypes {{ background: transparent; color: #e4f0f0; border: 0; }}
    QListWidget#setupTypes::item {{ color: #e4f0f0; padding: 2px 6px; border-left: 3px solid transparent; }}
    QListWidget#setupTypes::item:hover {{ background: #25505c; }}
    QListWidget#setupTypes::item:selected {{ background: #22515b; color: #fff; border-left: 3px solid #54d3bf; }}
    QWidget#setupWelcomeContent {{ background: {t['bg']}; }}
    QFrame#setupCard {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 6px; }}
    QLabel#setupCaption {{ font-size: 11pt; font-weight: 700; }}
    QFrame#setupDivider {{ border: 0; background: {t['border']}; }}
    QPushButton#setupRecent {{ text-align: left; background: {t['panel2']}; }}
    QPushButton#setupRecent:hover {{ background: {t['tint']}; }}
    QToolBar#plotTools {{ border: none; background: transparent; spacing: 2px; }}
    QToolBar::separator {{ background: {t['border']}; width: 1px; margin: 6px 6px; }}
    QToolBar#plotTools QLabel {{ color: {t['text2']}; }}

    QToolButton {{ border: 1px solid transparent; border-radius: 0px; padding: 5px 9px; background: transparent; }}
    QToolButton:hover {{ background: {t['hover']}; }}
    QToolButton:pressed {{ background: {t['tint']}; }}
    QToolButton:checked {{ background: {t['tint']}; color: {t['accent_dark']}; }}
    QToolButton[textState="mixed"] {{ border: 1px dashed {t['accent']}; }}
    QToolButton:disabled {{ color: {t['text3']}; }}
    QToolButton#primary {{ background: {primary}; color: {t['on_accent']}; border: 1px solid {t['accent']};
        padding: 5px 13px; font-weight: 600; }}
    QToolButton#primary:hover {{ background: {t['accent_hi']}; }}
    QToolButton#primary:pressed {{ background: {t['accent']}; }}
    QToolButton#primary:disabled {{ background: {t['field']}; border-color: {t['field']}; color: {t['text3']}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}

    QPushButton {{ background: {t['panel']}; border: 1px solid {t['field']}; border-bottom-color: {t['field_hover']};
        border-radius: 0px; padding: 6px 14px; }}
    QPushButton:hover {{ background: {t['hover']}; border-color: {t['field_hover']}; }}
    QPushButton:pressed {{ background: {t['tint']}; }}
    QPushButton:focus {{ border-color: {t['accent']}; }}
    QPushButton:checked {{ background: {t['tint']}; border-color: {t['accent']}; color: {t['accent_dark']}; }}
    QPushButton:default, QPushButton#primary {{ background: {primary}; color: {t['on_accent']};
        border: 1px solid {t['accent']}; font-weight: 600; }}
    QPushButton:default:hover, QPushButton#primary:hover {{ background: {t['accent_hi']}; }}
    QPushButton:default:pressed, QPushButton#primary:pressed {{ background: {t['accent']}; }}
    QPushButton:default:focus, QPushButton#primary:focus {{ border-color: {t['accent_dark']}; }}
    QPushButton:disabled {{ color: {t['text3']}; background: {t['panel2']}; border-color: {t['border']}; }}
    QPushButton::menu-indicator {{ image: url({down}); subcontrol-origin: padding; subcontrol-position: center right;
        width: 12px; height: 12px; left: 4px; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {t['panel']};
        border: 1px solid {t['field']}; border-radius: 0px; padding: 5px 8px;
        selection-background-color: {t['tint']}; selection-color: {t['text']}; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover,
    QTextEdit:hover {{ border-color: {t['field_hover']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus,
    QTextEdit:focus, QComboBox:on {{ border: 1px solid {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        background: {t['panel2']}; color: {t['text3']}; border-color: {t['border']}; }}
    QComboBox {{ padding-right: 22px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px;
        border: none; background: transparent; }}
    QComboBox::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}
    QComboBox::down-arrow:disabled {{ image: url({down_off}); }}
    QComboBox QAbstractItemView {{ background: {t['panel']}; border: 1px solid {t['border']};
        border-radius: 0px; padding: 4px; selection-background-color: {t['tint']};
        selection-color: {t['text']}; outline: 0; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
        width: 20px; border: none; border-top-right-radius: 0px; background: transparent; margin: 1px 1px 0 0; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
        subcontrol-position: bottom right; width: 20px; border: none; border-bottom-right-radius: 0px;
        background: transparent; margin: 0 1px 1px 0; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::down-button:hover {{ background: {t['hover']}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
    QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{ image: url({up_off}); }}
    QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: url({down_off}); }}

    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QCheckBox::indicator, QListView::indicator, QTreeView::indicator, QTableView::indicator,
    QGroupBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t['field_hover']}; border-radius: 0px;
        background: {t['panel']}; }}
    QCheckBox::indicator:hover, QListView::indicator:hover, QTreeView::indicator:hover {{
        border-color: {t['accent']}; }}
    QCheckBox::indicator:checked, QListView::indicator:checked, QTreeView::indicator:checked,
    QTableView::indicator:checked, QGroupBox::indicator:checked {{ background: {t['accent']};
        border-color: {t['accent']}; image: url({check}); }}
    QCheckBox::indicator:indeterminate, QListView::indicator:indeterminate,
    QTreeView::indicator:indeterminate {{ background: {t['accent']}; border-color: {t['accent']};
        image: url({dash}); }}
    QCheckBox::indicator:disabled {{ background: {t['panel2']}; border-color: {t['field']}; }}
    QCheckBox::indicator:checked:disabled {{ background: {t['field']}; border-color: {t['field']}; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {t['field_hover']}; border-radius: 0px;
        background: {t['panel']}; }}
    QRadioButton::indicator:hover {{ border-color: {t['accent']}; }}
    QRadioButton::indicator:checked {{ border: 5px solid {t['accent']}; width: 6px; height: 6px;
        background: {t['panel']}; }}
    QRadioButton::indicator:disabled {{ background: {t['panel2']}; border-color: {t['field']}; }}
    QRadioButton#setupMode::indicator {{ border-radius: 8px; }}

    QGroupBox {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 0px;
        margin-top: 20px; padding: 6px 0 0 0; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 2px;
        padding: 0 4px; color: {t['text2']}; font-weight: 600; }}

    QListWidget, QTreeWidget, QListView, QTreeView {{ background: {t['panel']}; border: 1px solid {t['border']};
        border-radius: 0px; outline: 0; padding: 3px; }}
    QListWidget::item, QTreeWidget::item {{ padding: 4px 6px; border-radius: 0px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t['hover']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {t['tint']}; color: {t['accent_dark']}; }}
    QTreeView::branch, QTreeView::branch:selected, QTreeView::branch:hover {{ background: transparent; }}
    QTreeWidget#navigator {{ border: none; background: transparent; padding: 0; }}
    QTreeWidget#navigator::branch:open:has-children {{ image: url({down}); }}
    QTreeWidget#navigator::branch:closed:has-children {{ image: url({right}); }}
    QTreeWidget#navigator::item {{ padding: 1px 3px; border-radius: 0px; }}
    QTreeWidget#navigator::item:hover {{ background: {t['hover']}; }}
    QTreeWidget#navigator::item:selected {{ background: {t['tint']}; color: {t['accent_dark']}; font-weight: 600; }}

    QTabWidget::pane {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 0px; }}
    QTabWidget::tab-bar {{ left: 0; }}
    QTabBar::tab {{ background: transparent; padding: 6px 14px; margin: 0 4px 6px 0; border: none;
        border-radius: 0px; color: {t['text2']}; }}
    QTabBar::tab:hover:!selected {{ background: {t['hover']}; color: {t['text']}; }}
    QTabBar::tab:selected {{ background: {t['tint']}; color: {t['accent_dark']}; font-weight: 600; }}

    QTableView {{ background: {t['panel']}; border: none; gridline-color: {t['grid']};
        selection-background-color: {t['tint']}; selection-color: {t['text']}; outline: 0; }}
    QLineEdit#worksheetEditor {{ padding: 0 3px; border: 1px solid {t['accent']}; }}
    QHeaderView {{ background: {t['header']}; border: none; }}
    QHeaderView::section {{ background: {t['header']}; color: {t['text2']}; border: none;
        border-right: 1px solid {t['grid']}; border-bottom: 1px solid {t['border']}; padding: 3px 6px; }}
    QHeaderView::section:horizontal {{ font-weight: 600; }}
    QTableView QTableCornerButton::section {{ background: {t['header']}; border: none;
        border-bottom: 1px solid {t['border']}; border-right: 1px solid {t['grid']}; }}

    QScrollBar:vertical {{ width: 12px; background: transparent; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: {t['scroll']}; border-radius: 0px; min-height: 32px; }}
    QScrollBar:horizontal {{ height: 12px; background: transparent; margin: 3px; }}
    QScrollBar::handle:horizontal {{ background: {t['scroll']}; border-radius: 0px; min-width: 32px; }}
    QScrollBar::handle:hover {{ background: {t['scroll_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: transparent; }}
    QStatusBar {{ background: {t['panel2']}; color: {t['text2']};
        border-top: 1px solid {t['field_hover']}; padding-left: 4px; }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QToolButton[statusTool="true"] {{ padding: 2px; }}
    QStatusBar QLabel {{ padding: 0 6px; }}
    QFrame#statusDivider {{ color: {t['field_hover']}; }}
    QLabel#statusMessage[fresh="true"] {{ color: {t['accent_dark']}; font-weight: 600; }}
    QProgressBar {{ background: {t['border']}; border: none; border-radius: 0px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {primary}; border-radius: 0px; }}

    QMenu {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 0px;
        padding: 5px; }}
    QMenu::item {{ padding: 6px 26px 6px 10px; border-radius: 0px; margin: 1px 0; }}
    QMenu::item:selected {{ background: {t['tint']}; color: {t['text']}; }}
    QMenu::item:disabled {{ color: {t['text3']}; }}
    QMenu::icon {{ padding-left: 8px; }}
    QMenu::indicator:checked {{ image: url({_ui_image('check', 'accent', 2.6)}); width: 14px; height: 14px;
        padding-left: 8px; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QAbstractScrollArea::corner {{ background: transparent; border: none; }}
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




# == motion ======================================================================================
def animations_enabled():
    """Short transitions, unless the system asks for none (Windows: "Animation effects" off), the session
    has no real screen (tests, smoke screenshots) or TRAMA_NO_ANIMATIONS is set."""
    if os.environ.get("TRAMA_NO_ANIMATIONS"):
        return False
    app = QApplication.instance()
    if app is None or app.platformName() in {"offscreen", "minimal"}:
        return False
    if WINDOWS:
        try:
            import ctypes
            enabled = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return True


def _animate(parent, start, end, step, *, duration=180, done=None, curve=QEasingCurve.Type.OutCubic):
    """Run ``step(value)`` from ``start`` to ``end``; at once (then ``done``) when animations are off."""
    if not animations_enabled():
        step(end)
        if done is not None:
            done()
        return None
    animation = QVariantAnimation(parent)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setDuration(duration)
    animation.setEasingCurve(curve)
    animation.valueChanged.connect(step)
    if done is not None:
        animation.finished.connect(done)
    animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def stop_animation(animation):
    """Stop a running transition; one that already finished has deleted itself."""
    if animation is None:
        return
    try:
        animation.stop()
    except RuntimeError:
        pass


def fade_in(widget, duration=170):
    """Fade a freshly shown widget in; the opacity effect is removed at the end (it costs a redraw)."""
    if not animations_enabled():
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    def finish():
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    _animate(widget, 0.0, 1.0, effect.setOpacity, duration=duration, done=finish)


def slide_splitter(splitter, start, end, done=None, duration=200):
    """Animate the first pane of ``splitter`` from ``start`` to ``end`` pixels wide."""
    total = max(sum(splitter.sizes()), start, end)

    def step(value):
        value = int(value)
        splitter.setSizes([value, max(total - value, 0)])

    return _animate(splitter, int(start), int(end), step, duration=duration, done=done)


class SlidingTabBar(QTabBar):
    """The command-bar tabs: a rounded accent bar slides under the selected tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bar = QRectF()
        self._animation = None
        self.currentChanged.connect(self._slide)

    def _target(self, index):
        rect = self.tabRect(index)
        if not rect.isValid():
            return QRectF()
        inset = min(14.0, rect.width() / 4)
        return QRectF(rect.left() + inset, rect.bottom() - 3.0, rect.width() - 2 * inset, 3.0)

    def _set(self, rect):
        self._bar = QRectF(rect)
        self.update()

    def _slide(self, index):
        target = self._target(index)
        if self._bar.isNull() or not self.isVisible():
            self._set(target)
            return
        stop_animation(self._animation)
        self._animation = _animate(self, QRectF(self._bar), target, self._set, duration=220)

    def tabLayoutChange(self):
        super().tabLayoutChange()
        self._set(self._target(self.currentIndex()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set(self._target(self.currentIndex()))

    def showEvent(self, event):
        super().showEvent(event)
        self._set(self._target(self.currentIndex()))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._bar.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color("accent"))
        painter.drawRoundedRect(self._bar, 1.5, 1.5)
        painter.end()


# == soft shadows ================================================================================
def _blurred(image, radius):
    """Gaussian blur by Qt (QGraphicsBlurEffect) of a premultiplied image."""
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    scene.render(painter, QRectF(result.rect()), QRectF(image.rect()))
    painter.end()
    return result


@lru_cache(maxsize=32)
def _shadow_tile(radius, blur, rgba, ratio):
    """A blurred rounded square for nine-slice drawing: returns (image, pad, corner) in device pixels."""
    pad = math.ceil(blur * 1.2 * ratio)
    inner = math.ceil((radius + 2) * ratio)
    core = 2 * inner + max(4, math.ceil(4 * ratio))  # A straight middle to stretch along the edges.
    side = core + 2 * pad
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(pad, pad, core, core), radius * ratio, radius * ratio)
    painter.fillPath(path, QColor(*rgba))
    painter.end()
    return _blurred(image, blur * ratio), pad, pad + inner


def paint_shadow(painter, rect, radius=CARD_RADIUS, ratio=1.0):
    """Soft layered shadow under ``rect`` (logical coordinates), drawn in nine slices so any size is cheap."""
    dark = STATE["dark"]
    red, green, blue = SHADOW_RGB[dark]
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for blur, offset, alpha in SHADOWS[dark]:
        image, pad, corner = _shadow_tile(radius, blur, (red, green, blue, round(255 * alpha)), ratio)
        side = image.width()
        # Target in device pixels, then back to logical with the painter's scale.
        left, top = rect.left() * ratio - pad, (rect.top() + offset) * ratio - pad
        width, height = rect.width() * ratio + 2 * pad, rect.height() * ratio + 2 * pad
        if width < 2 * corner or height < 2 * corner:
            continue
        mid_w, mid_h, src_mid = width - 2 * corner, height - 2 * corner, side - 2 * corner
        pieces = (
            (0, 0, corner, corner, 0, 0, corner, corner),
            (corner, 0, mid_w, corner, corner, 0, src_mid, corner),
            (corner + mid_w, 0, corner, corner, side - corner, 0, corner, corner),
            (0, corner, corner, mid_h, 0, corner, corner, src_mid),
            (corner + mid_w, corner, corner, mid_h, side - corner, corner, corner, src_mid),
            (0, corner + mid_h, corner, corner, 0, side - corner, corner, corner),
            (corner, corner + mid_h, mid_w, corner, corner, side - corner, src_mid, corner),
            (corner + mid_w, corner + mid_h, corner, corner, side - corner, side - corner, corner, corner),
        )
        for x, y, w, h, sx, sy, sw, sh in pieces:
            target = QRectF((left + x) / ratio, (top + y) / ratio, w / ratio, h / ratio)
            painter.drawImage(target, image, QRectF(sx, sy, sw, sh))
    painter.restore()


class ShadowCanvas(QWidget):
    """The window's background: paints soft shadows under the panel cards laid on it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = []

    def add_card(self, card):
        self._cards.append(card)
        card.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in {QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide}:
            self.update()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ratio = self.devicePixelRatioF()
        for card in self._cards:
            if card.isVisible() and card.width() > 0:
                paint_shadow(painter, QRect(card.mapTo(self, QPoint(0, 0)), card.size()), CARD_RADIUS, ratio)
        painter.end()


# == frosted glass behind modal dialogs ==========================================================
class GlassVeil(QWidget):
    """Covers a main window while a modal dialog is open: the window blurred, with a light veil, faded in."""

    def __init__(self, host):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.dialogs = set()
        self.progress = 0.0
        shot = host.grab()
        ratio = shot.devicePixelRatio()
        small = shot.toImage().scaled(max(1, shot.width() // 3), max(1, shot.height() // 3),
                                      Qt.AspectRatioMode.IgnoreAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        small = small.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.backdrop = _blurred(small, 7 * ratio)
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.raise_()
        self.show()
        self._animation = _animate(self, 0.0, 1.0, self._set, duration=200)

    def _set(self, value):
        self.progress = float(value)
        self.update()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return False

    def release(self, dialog_id):
        self.dialogs.discard(dialog_id)
        if self.dialogs:
            return
        stop_animation(self._animation)
        self._animation = None
        self.parentWidget().removeEventFilter(self)
        _animate(self, self.progress, 0.0, self._set, duration=140, done=self.deleteLater,
                 curve=QEasingCurve.Type.InCubic)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self.progress)
        painter.drawImage(QRectF(self.rect()), self.backdrop)
        painter.setOpacity(1.0)
        red, green, blue, alpha = VEIL[STATE["dark"]]
        painter.fillRect(self.rect(), QColor(red, green, blue, round(alpha * self.progress)))
        painter.end()


def _veil_for(dialog):
    parent = dialog.parentWidget()
    host = parent.window() if parent is not None else None
    if not isinstance(host, QMainWindow) or not host.isVisible():
        return None
    for child in host.children():
        if isinstance(child, GlassVeil) and child.dialogs:
            return child
    return GlassVeil(host)


# == Windows frame ===============================================================================
def _colorref(value):
    colour = QColor(value)
    return colour.red() | (colour.green() << 8) | (colour.blue() << 16)


def native_frame(widget):
    """Windows 11: title bar in the theme's colours (dark title bar in the dark theme) and rounded corners for
    windows, menus and drop-down lists. Does nothing elsewhere or on older Windows."""
    if not WINDOWS or not widget.isWindow():
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm = ctypes.windll.dwmapi

        def attribute(name, value):
            data = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, name, ctypes.byref(data), ctypes.sizeof(data))

        popup = widget.windowType() in {Qt.WindowType.Popup, Qt.WindowType.ToolTip}
        if not popup:
            attribute(20, 1 if STATE["dark"] else 0)  # DWMWA_USE_IMMERSIVE_DARK_MODE
            caption = T["panel"] if isinstance(widget, QMainWindow) else T["bg"]
            attribute(35, _colorref(caption))  # DWMWA_CAPTION_COLOR
            attribute(36, _colorref(T["text"]))  # DWMWA_TEXT_COLOR
    except (AttributeError, OSError, ValueError):
        pass


class _WindowPolish(QObject):
    """Fit dialogs within the available desktop and apply the native frame colours."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            native_frame(watched)
            if isinstance(watched, QDialog):
                keep_on_screen(watched)
        return False


def _live_veils(dialog):
    parent = dialog.parentWidget()
    host = parent.window() if parent is not None else None
    if host is None:
        return []
    return [child for child in host.children() if isinstance(child, GlassVeil) and id(dialog) in child.dialogs]


def _release(veil, key):
    try:
        if key in veil.dialogs:
            veil.release(key)
    except RuntimeError:  # The veil went with its window.
        pass


_POLISH = _WindowPolish()


# == light and dark ==============================================================================
def saved_mode():
    """Restore the theme chosen in View. A new installation starts in light mode."""
    forced = os.environ.get("TRAMA_THEME", "").strip().lower()
    if forced in MODES:
        return forced
    value = QSettings("TramaStat", "Trama").value("qt/theme", DEFAULT_MODE)
    return value if value in MODES else DEFAULT_MODE


def system_dark(app=None):
    app = app or QApplication.instance()
    try:
        return app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def set_mode(mode, app=None, *, remember=True):
    """Switch theme now; with ``remember`` the choice is kept for the next start."""
    if mode not in MODES:
        raise ValueError(mode)
    STATE["mode"] = mode
    if remember:
        QSettings("TramaStat", "Trama").setValue("qt/theme", mode)
    apply(app or QApplication.instance())


def _system_changed(*_args):
    if STATE["mode"] == "system":
        apply(QApplication.instance())


def apply(app, *, dark=None):
    """Apply the theme: ``dark`` forces light or dark, otherwise the mode in ``STATE`` decides (the system's
    colour scheme for "system"). Open windows are restyled and ``SIGNALS.changed`` is emitted."""
    if dark is None:
        mode = STATE["mode"]
        dark = mode == "dark" or (mode == "system" and system_dark(app))
    app.removeEventFilter(_POLISH)
    app.installEventFilter(_POLISH)
    STATE["dark"] = bool(dark)
    T.clear()
    T.update(DARK if dark else LIGHT)
    _icon_pixmap.cache_clear()
    if not STATE["connected"]:
        app.setStyle("Fusion")
        try:
            app.styleHints().colorSchemeChanged.connect(_system_changed)
        except AttributeError:
            pass
        STATE["connected"] = True
    app.setPalette(palette())
    app.setFont(font())
    app.setStyleSheet(stylesheet())
    for window in app.topLevelWidgets():
        if window.isVisible():
            native_frame(window)
    SIGNALS.changed.emit()


PLOT_ICONS = {"home": "house", "back": "arrow-left", "forward": "arrow-right", "pan": "move", "zoom": "zoom-in"}


def plot_toolbar(toolbar):
    """matplotlib's navigation toolbar with the interface's icons and look."""
    toolbar.setObjectName("plotTools")
    for key, action in getattr(toolbar, "_actions", {}).items():
        if key in PLOT_ICONS:
            action.setIcon(icon(PLOT_ICONS[key], "text2"))
            action.setToolTip(qt(f"qt.plot_{key}"))
