"""Qt dialogs and reusable widgets for multivariate Bubble plot symbol, color and encoding editors."""
from copy import deepcopy

from matplotlib import colormaps
from matplotlib.markers import MarkerStyle
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from analisi.bubble_style import (
    AREA_LIMIT, BUBBLE_PALETTES, CATEGORY_COLORS, COLOR_LEGEND, COLOR_LIMITS, COLOR_MAX, COLOR_MID, COLOR_MIN,
    COLOR_TITLE, DEFAULT_AREA, DEFAULT_FIXED_AREA, DEFAULT_FIXED_COLOR, DEFAULT_FIXED_SHAPE,
    DEFAULT_MISSING_COLOR, DEFAULT_MISSING_SHAPE, FILL_BY_CATEGORY, FILL_CONTINUOUS, FILL_FIXED,
    FILL_MODE, FILL_MODES, FIXED_AREA, FIXED_COLOR, FIXED_SHAPE, LIMITS_AUTO, LIMITS_MANUAL,
    LIMITS_MODES, MAX_AREA, MISSING_COLOR, MISSING_SHAPE, PALETTE, PRIMARY_SHAPES, REVERSE_PALETTE,
    SHAPE_BY_CATEGORY, SHAPE_CHOICES, SHAPE_FIXED, SHAPE_LEGEND, SHAPE_MAP, SHAPE_MODE, SHAPE_MODES,
    SHOW_LABELS, SIZE_BY_COLUMN, SIZE_FIXED, SIZE_LEGEND, SIZE_MODE, SIZE_MODES, STYLE_TO_FIELD,
    BubbleStyleError, _ExactReverse, apply_bubble_style, baseline_bubble_style,
    describe_bubble_artists, shape_label, snapshot_bubble_style, valid_color, validate_bubble_style,
)
from analisi.category_graphs import COLORS
from analisi.i18n import tr

from . import theme
from .labels import choice_label, field_label


def marker_icon(marker, color_hex=None, size=14):
    """Paint a crisp Qt icon matching Matplotlib's ``MarkerStyle(marker)``."""
    color_hex = color_hex or theme.T.get("text", "#34414f")
    dpr = 2
    px = size * dpr
    pixmap = QPixmap(px, px)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    style = MarkerStyle(marker)
    path = style.get_path().transformed(style.get_transform())
    verts = np.asarray(path.vertices, dtype=float)
    codes = path.codes
    if len(verts) == 0:
        return QIcon(pixmap)

    vmin = verts.min(axis=0)
    vmax = verts.max(axis=0)
    span = np.maximum(vmax - vmin, 1e-6).max()
    scale = (size - 4.0) / span
    center = 0.5 * (vmin + vmax)
    qpath = QPainterPath()
    i = 0
    while i < len(verts):
        code = codes[i] if codes is not None else (1 if i == 0 else 2)
        px_x = size * 0.5 + (verts[i, 0] - center[0]) * scale
        px_y = size * 0.5 - (verts[i, 1] - center[1]) * scale
        if code == 1:  # MOVETO
            qpath.moveTo(px_x, px_y)
        elif code == 2:  # LINETO
            qpath.lineTo(px_x, px_y)
        elif code == 3 and i + 1 < len(verts):  # CURVE3
            cx = size * 0.5 + (verts[i + 1, 0] - center[0]) * scale
            cy = size * 0.5 - (verts[i + 1, 1] - center[1]) * scale
            qpath.quadTo(px_x, px_y, cx, cy)
            i += 1
        elif code == 4 and i + 2 < len(verts):  # CURVE4
            x2 = size * 0.5 + (verts[i + 1, 0] - center[0]) * scale
            y2 = size * 0.5 - (verts[i + 1, 1] - center[1]) * scale
            x3 = size * 0.5 + (verts[i + 2, 0] - center[0]) * scale
            y3 = size * 0.5 - (verts[i + 2, 1] - center[1]) * scale
            qpath.cubicTo(px_x, px_y, x2, y2, x3, y3)
            i += 2
        elif code == 79:  # CLOSEPOLY
            qpath.closeSubpath()
        i += 1

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    fg = QColor(color_hex) if QColor(color_hex).isValid() else QColor("#34414f")
    if style.is_filled():
        painter.setPen(QPen(fg, 0.8))
        painter.setBrush(fg)
    else:
        painter.setPen(QPen(fg, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(qpath)
    painter.end()
    return QIcon(pixmap)


def palette_icon(palette_name, *, reverse=False, width=48, height=12):
    """Build a crisp horizontal palette gradient icon from the named Matplotlib scale."""
    name = BUBBLE_PALETTES.get(palette_name, "viridis")
    cmap = _ExactReverse(colormaps[name]) if reverse else colormaps[name]
    u = np.linspace(0.0, 1.0, width)
    rgba = np.round(cmap(u) * 255.0).astype(np.uint8)
    row = rgba[None, :, :]
    band = np.repeat(row, height, axis=0).copy()
    image = QImage(band.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
    return QIcon(QPixmap.fromImage(image.copy()))


class MarkerCombo(QComboBox):
    """Combo box listing Matplotlib markers with rendered glyph icons."""

    def __init__(self, choices=SHAPE_CHOICES, current=DEFAULT_FIXED_SHAPE, parent=None):
        super().__init__(parent)
        self.setMinimumContentsLength(14)
        for marker in choices:
            self.addItem(marker_icon(marker), shape_label(marker), marker)
        self.set_value(current)

    def value(self):
        return self.currentData()

    def set_value(self, marker):
        idx = self.findData(marker)
        if idx >= 0:
            self.setCurrentIndex(idx)


class PaletteCombo(QComboBox):
    """Palette selector with live linear gradient swatch previews."""

    def __init__(self, current="Viridis", *, reverse=False, parent=None):
        super().__init__(parent)
        self._reverse = bool(reverse)
        for key in BUBBLE_PALETTES:
            self.addItem(palette_icon(key, reverse=self._reverse), choice_label(key), key)
        self.set_value(current)

    def set_reverse(self, reverse):
        self._reverse = bool(reverse)
        for i in range(self.count()):
            key = self.itemData(i)
            self.setItemIcon(i, palette_icon(key, reverse=self._reverse))

    def value(self):
        return self.currentData()

    def set_value(self, name):
        idx = self.findData(name)
        if idx >= 0:
            self.setCurrentIndex(idx)


class ColorField(QWidget):
    """Editable hex color text box paired with a color swatch picker button."""

    changed = Signal()

    def __init__(self, initial=DEFAULT_FIXED_COLOR, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit(str(initial or ""))
        self.edit.setMinimumWidth(96)
        self.edit.textChanged.connect(self._on_edit)
        self.pick = QPushButton(tr("bubble.style.pick"))
        self.pick.setAutoDefault(False)
        self.pick.setFixedWidth(74)
        self.pick.clicked.connect(self._choose)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.pick)
        self.setFocusProxy(self.edit)
        self._paint_pick()

    def text(self):
        return self.edit.text().strip()

    def setText(self, text):
        self.edit.setText(str(text or ""))
        self._paint_pick()

    def _on_edit(self):
        self._paint_pick()
        self.changed.emit()

    def _paint_pick(self):
        val = self.edit.text().strip()
        if valid_color(val):
            qcol = QColor(val)
            fg = "#111111" if qcol.lightnessF() > 0.56 else "#ffffff"
            self.pick.setStyleSheet(f"background: {qcol.name()}; color: {fg};")
        else:
            self.pick.setStyleSheet("")

    def _choose(self):
        current = self.edit.text().strip()
        initial = QColor(current) if valid_color(current) else QColor(DEFAULT_FIXED_COLOR)
        chosen = QColorDialog.getColor(initial, self, tr("bubble.style.pick"))
        if chosen.isValid():
            self.edit.setText(chosen.name())


def _level_warning(levels_with_markers):
    used = [marker for _, marker in levels_with_markers]
    if len(levels_with_markers) > len(PRIMARY_SHAPES) or len(set(used)) < len(used):
        return tr("bubble.style.warning.shape_repeat", limit=len(PRIMARY_SHAPES))
    return ""


class LevelSymbolEditor(QWidget):
    """Per-level symbol assignment table keyed strictly by ``typed_group_token``."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels = []
        self._combos = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            tr("bubble.style.level_col.level"),
            tr("bubble.style.level_col.type"),
            tr("bubble.style.level_col.symbol"),
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(140)
        self.table.setMaximumHeight(240)
        layout.addWidget(self.table)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.warning = QLabel()
        self.warning.setObjectName("muted")
        self.warning.setWordWrap(True)
        self.reset_button = QPushButton(tr("bubble.style.reset_symbols"))
        self.reset_button.setAutoDefault(False)
        self.reset_button.clicked.connect(self.reset_defaults)
        footer.addWidget(self.warning, 1)
        footer.addWidget(self.reset_button)
        layout.addLayout(footer)

    def populate(self, levels, mapping):
        """Fill rows from ``[(token, raw_label, type_key), ...]`` and saved ``{token: marker}``."""
        self._levels = list(levels)
        self._combos = []
        self.table.setRowCount(len(self._levels))
        used = set()
        resolved = []
        # Reserve explicit saved choices first, then assign unused primary markers cleanly.
        for token, raw_label, _type_key in self._levels:
            picked = (mapping or {}).get(token)
            if picked is None and raw_label in (mapping or {}):
                picked = mapping[raw_label]
            if picked in SHAPE_CHOICES:
                used.add(picked)
            resolved.append(picked)

        unused = [m for m in PRIMARY_SHAPES if m not in used]
        cycle = 0
        for row, (item, explicit) in enumerate(zip(self._levels, resolved, strict=True)):
            token, raw_label, type_key = item
            if explicit in SHAPE_CHOICES:
                marker = explicit
            elif unused:
                marker = unused.pop(0)
            else:
                marker = PRIMARY_SHAPES[cycle % len(PRIMARY_SHAPES)]
                cycle += 1

            lvl_item = QTableWidgetItem(str(raw_label))
            lvl_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            lvl_item.setData(Qt.ItemDataRole.UserRole, token)
            typ_item = QTableWidgetItem(tr(type_key))
            typ_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            combo = MarkerCombo(SHAPE_CHOICES, marker)
            combo.currentIndexChanged.connect(self._on_change)
            self.table.setItem(row, 0, lvl_item)
            self.table.setItem(row, 1, typ_item)
            self.table.setCellWidget(row, 2, combo)
            self._combos.append((token, combo))
        self.reset_button.setEnabled(bool(self._levels))
        self._update_warning()

    def values(self):
        return {token: combo.value() for token, combo in self._combos}

    def reset_defaults(self):
        self.populate(self._levels, {})
        self.changed.emit()

    def _on_change(self):
        self._update_warning()
        self.changed.emit()

    def _update_warning(self):
        pairs = [(token, combo.value()) for token, combo in self._combos]
        msg = _level_warning(pairs)
        self.warning.setText(msg)
        self.warning.setVisible(bool(msg))


class LevelSymbolDialog(QDialog):
    """Modal editor for mapping Shape category levels to distinct symbol markers."""

    def __init__(self, parent, levels, current_map, missing_shape=DEFAULT_MISSING_SHAPE):
        super().__init__(parent)
        self.setWindowTitle(tr("bubble.style.edit_symbols"))
        self.result = None
        self.missing_result = missing_shape

        layout = QVBoxLayout(self)
        self.editor = LevelSymbolEditor(self)
        self.editor.populate(levels, current_map)
        layout.addWidget(self.editor)

        form = QFormLayout()
        self.missing_combo = MarkerCombo(SHAPE_CHOICES, missing_shape)
        form.addRow(QLabel(tr("ui.Missing shape") if False else field_text("Missing shape")), self.missing_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        theme.fit_dialog(self, 480, 400)

    def accept(self):
        self.result = self.editor.values()
        self.missing_result = self.missing_combo.value()
        super().accept()


def field_text(name):
    return field_label(name)


class CategoryColorsDialog(QDialog):
    """Per-level fill color editor keyed by ``typed_group_token``."""

    def __init__(self, parent, levels, current_map):
        super().__init__(parent)
        self.setWindowTitle(tr("bubble.style.edit_colors"))
        self._levels = list(levels)
        self._editors = []
        self.result = None

        layout = QVBoxLayout(self)
        table = QTableWidget(len(self._levels), 3)
        table.setHorizontalHeaderLabels([
            tr("bubble.style.level_col.level"),
            tr("bubble.style.level_col.type"),
            tr("bubble.style.level_col.color"),
        ])
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(150)

        for idx, (token, raw_label, type_key) in enumerate(self._levels):
            default_hex = COLORS[idx % len(COLORS)]
            val = (current_map or {}).get(token) or (current_map or {}).get(raw_label) or default_hex
            lvl_item = QTableWidgetItem(str(raw_label))
            lvl_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            typ_item = QTableWidgetItem(tr(type_key))
            typ_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            swatch = ColorField(val)
            table.setItem(idx, 0, lvl_item)
            table.setItem(idx, 1, typ_item)
            table.setCellWidget(idx, 2, swatch)
            self._editors.append((token, swatch))
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        theme.fit_dialog(self, 480, 380)

    def accept(self):
        out = {}
        for token, swatch in self._editors:
            text = swatch.text()
            if not valid_color(text):
                swatch.setFocus()
                return
            out[token] = text
        self.result = out
        super().accept()


class MappingFieldWidget(QWidget):
    """Inline compact summary + button for ``Symbol map`` / ``Category colors`` inside forms."""

    changed = Signal()

    def __init__(self, button_key, parent=None):
        super().__init__(parent)
        self._mapping = {}
        self._levels = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.summary = QLabel(tr("bubble.style.levels_summary.none"))
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.button = QPushButton(tr(button_key))
        self.button.setAutoDefault(False)
        layout.addWidget(self.summary, 1)
        layout.addWidget(self.button)

    def set_levels(self, levels, mapping=None):
        self._levels = list(levels)
        if mapping is not None:
            self._mapping = dict(mapping)
        self._refresh_summary()

    def mapping(self):
        return dict(self._mapping)

    def set_mapping(self, mapping):
        self._mapping = dict(mapping or {})
        self._refresh_summary()
        self.changed.emit()

    def _refresh_summary(self):
        if not self._levels:
            self.summary.setText(tr("bubble.style.levels_summary.none"))
            self.button.setEnabled(False)
        else:
            self.summary.setText(tr("bubble.style.levels_summary", count=len(self._levels)))
            self.button.setEnabled(True)


class BubbleStyleDialog(QDialog):
    """Live-previewing, single-Apply dialog for all multivariate Bubble plot encodings."""

    def __init__(self, parent, figure, section=None, *, full_style=None, on_preview=None):
        super().__init__(parent)
        self.setWindowTitle(tr("bubble.style.title"))
        self.figure = figure
        self.state = describe_bubble_artists(figure)
        self.baseline = baseline_bubble_style(figure)
        self._before = snapshot_bubble_style(figure)
        self._full_style = deepcopy(full_style or {})
        self._on_preview = on_preview
        self.result = None
        current = {**self.baseline, **(validate_bubble_style(section or {}, figure=figure))}

        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        # Size tab
        size_form, _ = self._add_tab("bubble.style.tab.size")
        self.size_mode = self._choice_combo(SIZE_MODES, current["size_mode"])
        if not self.state.get("has_size"):
            # Only fixed area works without a Size column.
            idx = self.size_mode.findData(SIZE_BY_COLUMN)
            if idx >= 0:
                self.size_mode.removeItem(idx)
        self.max_area = QLineEdit(f"{current['maximum_area']:g}")
        self.fixed_area = QLineEdit(f"{current['fixed_area']:g}")
        self.show_size_legend = QCheckBox()
        self.show_size_legend.setChecked(bool(current["show_size_legend"]))
        self.size_rows = {}
        for fld, widget in (
            (SIZE_MODE, self.size_mode),
            (MAX_AREA, self.max_area),
            (FIXED_AREA, self.fixed_area),
            (SIZE_LEGEND, self.show_size_legend),
        ):
            size_form.addRow(QLabel(field_label(fld)), widget)
            self.size_rows[fld] = (size_form, widget)

        # Color tab
        color_form, _ = self._add_tab("bubble.style.tab.color")
        avail_fill = list(FILL_MODES) if self.state.get("has_color") else [FILL_BY_CATEGORY, FILL_FIXED]
        self.fill_mode = self._choice_combo(avail_fill, current["fill_mode"])
        self.fixed_color = ColorField(current["fixed_color"])
        self._category_colors = dict(current["category_colors"])
        self.cat_colors_btn = QPushButton(tr("bubble.style.edit_colors"))
        self.cat_colors_btn.setAutoDefault(False)
        self.cat_colors_btn.setEnabled(bool(self.state.get("has_group")))
        self.cat_colors_btn.clicked.connect(self._edit_category_colors)

        self.palette = PaletteCombo(current["palette"], reverse=current["reverse"])
        self.reverse = QCheckBox()
        self.reverse.setChecked(bool(current["reverse"]))
        self.reverse.toggled.connect(self.palette.set_reverse)
        self.limits_mode = self._choice_combo(LIMITS_MODES, current["limits_mode"])
        self.color_min = QLineEdit("" if current["color_min"] is None else f"{current['color_min']:g}")
        self.color_mid = QLineEdit("" if current["color_mid"] is None else f"{current['color_mid']:g}")
        self.color_max = QLineEdit("" if current["color_max"] is None else f"{current['color_max']:g}")
        self.missing_color = ColorField(current["missing_color"])
        self.show_color_legend = QCheckBox()
        self.show_color_legend.setChecked(bool(current["show_color_legend"]))
        self.color_title = QLineEdit(str(current["color_title"] or ""))

        self.color_rows = {}
        for fld, widget in (
            (FILL_MODE, self.fill_mode),
            (FIXED_COLOR, self.fixed_color),
            ("Category colors", self.cat_colors_btn),
            (PALETTE, self.palette),
            (REVERSE_PALETTE, self.reverse),
            (COLOR_LIMITS, self.limits_mode),
            (COLOR_MIN, self.color_min),
            (COLOR_MID, self.color_mid),
            (COLOR_MAX, self.color_max),
            (MISSING_COLOR, self.missing_color),
            (COLOR_LEGEND, self.show_color_legend),
            (COLOR_TITLE, self.color_title),
        ):
            color_form.addRow(QLabel(field_label(fld)), widget)
            self.color_rows[fld] = (color_form, widget)

        # Shapes & level symbols tab
        shape_form, shape_box = self._add_tab("bubble.style.tab.shape")
        avail_shape = list(SHAPE_MODES) if self.state.get("has_shape") else [SHAPE_FIXED]
        self.shape_mode = self._choice_combo(avail_shape, current["shape_mode"])
        self.fixed_shape = MarkerCombo(SHAPE_CHOICES, current["fixed_shape"])
        self.missing_shape = MarkerCombo(SHAPE_CHOICES, current["missing_shape"])
        self.show_shape_legend = QCheckBox()
        self.show_shape_legend.setChecked(bool(current["show_shape_legend"]))
        self.level_symbols = LevelSymbolEditor(self)
        shape_levels = [(item[0], item[1], item[2]) for item in self.state.get("shape_levels", ())]
        self.level_symbols.populate(shape_levels, current["shape_map"])

        self.shape_rows = {}
        for fld, widget in (
            (SHAPE_MODE, self.shape_mode),
            (FIXED_SHAPE, self.fixed_shape),
            (MISSING_SHAPE, self.missing_shape),
            (SHAPE_LEGEND, self.show_shape_legend),
        ):
            shape_form.addRow(QLabel(field_label(fld)), widget)
            self.shape_rows[fld] = (shape_form, widget)
        self.symbol_group = QGroupBox(tr("bubble.style.tab.levels"))
        sg_lay = QVBoxLayout(self.symbol_group)
        sg_lay.addWidget(self.level_symbols)
        shape_box.addWidget(self.symbol_group)

        # Labels tab
        leg_form, _ = self._add_tab("bubble.style.tab.legends")
        self.show_labels = QCheckBox()
        self.show_labels.setChecked(bool(current["show_labels"]))
        leg_form.addRow(QLabel(field_label(SHOW_LABELS)), self.show_labels)

        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        outer.addWidget(self.problem)

        buttons = QHBoxLayout()
        self.preview_button = QPushButton(tr("bubble.style.preview"))
        self.preview_button.setAutoDefault(False)
        self.preview_button.clicked.connect(self.preview)
        self.reset_button = QPushButton(tr("graph.inspector.reset_section"))
        self.reset_button.setAutoDefault(False)
        self.reset_button.clicked.connect(self._restore_baseline)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.apply_button = box.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText(tr("bubble.style.apply"))
        self.apply_button.setObjectName("primary")
        self.cancel_button = box.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText(tr("bubble.style.cancel"))
        self.cancel_button.setAutoDefault(False)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        outer.addLayout(buttons)

        for combo in (self.size_mode, self.fill_mode, self.limits_mode, self.shape_mode):
            combo.currentIndexChanged.connect(self._sync_visibility)
        self._sync_visibility()
        theme.fit_dialog(self, 660, 560)

    def _add_tab(self, title_key):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        vbox = QVBoxLayout(inner)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(10)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vbox.addLayout(form)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, tr(title_key))
        return form, vbox

    @staticmethod
    def _choice_combo(choices, selected):
        combo = QComboBox()
        for choice in choices:
            combo.addItem(choice_label(str(choice)), choice)
        idx = combo.findData(selected)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        return combo

    def _sync_visibility(self):
        sm = self.size_mode.currentData()
        for fld, vis in (
            (MAX_AREA, sm == SIZE_BY_COLUMN),
            (FIXED_AREA, sm == SIZE_FIXED),
            (SIZE_LEGEND, True),
        ):
            form, w = self.size_rows[fld]
            form.setRowVisible(w, vis)

        fm = self.fill_mode.currentData()
        lm = self.limits_mode.currentData()
        cont = fm == FILL_CONTINUOUS
        for fld, vis in (
            (FIXED_COLOR, fm == FILL_FIXED),
            ("Category colors", fm == FILL_BY_CATEGORY and bool(self.state.get("has_group"))),
            (PALETTE, cont),
            (REVERSE_PALETTE, cont),
            (COLOR_LIMITS, cont),
            (COLOR_MIN, cont and lm == LIMITS_MANUAL),
            (COLOR_MID, cont),
            (COLOR_MAX, cont and lm == LIMITS_MANUAL),
            (MISSING_COLOR, cont),
            (COLOR_LEGEND, cont),
            (COLOR_TITLE, cont),
        ):
            form, w = self.color_rows[fld]
            form.setRowVisible(w, vis)

        shm = self.shape_mode.currentData()
        by_cat = shm == SHAPE_BY_CATEGORY and bool(self.state.get("has_shape"))
        for fld, vis in (
            (FIXED_SHAPE, not by_cat),
            (MISSING_SHAPE, by_cat),
            (SHAPE_LEGEND, by_cat),
        ):
            form, w = self.shape_rows[fld]
            form.setRowVisible(w, vis)
        self.symbol_group.setVisible(by_cat)

    def _edit_category_colors(self):
        levels = [(item[0], item[1], item[2]) for item in self.state.get("group_levels", ())]
        if not levels:
            return
        dlg = CategoryColorsDialog(self, levels, self._category_colors)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result is not None:
            self._category_colors = dlg.result

    def _restore_baseline(self):
        b = self.baseline
        for combo, val in (
            (self.size_mode, b["size_mode"]),
            (self.fill_mode, b["fill_mode"]),
            (self.limits_mode, b["limits_mode"]),
            (self.shape_mode, b["shape_mode"]),
        ):
            idx = combo.findData(val)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self.max_area.setText(f"{b['maximum_area']:g}")
        self.fixed_area.setText(f"{b['fixed_area']:g}")
        self.show_size_legend.setChecked(bool(b["show_size_legend"]))
        self.fixed_color.setText(b["fixed_color"])
        self._category_colors = dict(b["category_colors"])
        self.palette.set_value(b["palette"])
        self.reverse.setChecked(bool(b["reverse"]))
        self.color_min.setText("" if b["color_min"] is None else f"{b['color_min']:g}")
        self.color_mid.setText("" if b["color_mid"] is None else f"{b['color_mid']:g}")
        self.color_max.setText("" if b["color_max"] is None else f"{b['color_max']:g}")
        self.missing_color.setText(b["missing_color"])
        self.show_color_legend.setChecked(bool(b["show_color_legend"]))
        self.color_title.setText(b["color_title"])
        self.fixed_shape.set_value(b["fixed_shape"])
        self.missing_shape.set_value(b["missing_shape"])
        self.show_shape_legend.setChecked(bool(b["show_shape_legend"]))
        shape_levels = [(item[0], item[1], item[2]) for item in self.state.get("shape_levels", ())]
        self.level_symbols.populate(shape_levels, b["shape_map"])
        self.show_labels.setChecked(bool(b["show_labels"]))
        self._sync_visibility()
        self.preview()

    def _payload(self):
        payload = {
            "size_mode": self.size_mode.currentData(),
            "maximum_area": self.max_area.text(),
            "fixed_area": self.fixed_area.text(),
            "show_size_legend": self.show_size_legend.isChecked(),
            "fill_mode": self.fill_mode.currentData(),
            "fixed_color": self.fixed_color.text(),
            "category_colors": dict(self._category_colors),
            "palette": self.palette.value(),
            "reverse": self.reverse.isChecked(),
            "limits_mode": self.limits_mode.currentData(),
            "color_min": self.color_min.text() or None,
            "color_mid": self.color_mid.text() or None,
            "color_max": self.color_max.text() or None,
            "missing_color": self.missing_color.text(),
            "show_color_legend": self.show_color_legend.isChecked(),
            "color_title": self.color_title.text(),
            "shape_mode": self.shape_mode.currentData(),
            "fixed_shape": self.fixed_shape.value(),
            "missing_shape": self.missing_shape.value(),
            "show_shape_legend": self.show_shape_legend.isChecked(),
            "show_labels": self.show_labels.isChecked(),
        }
        if self.state.get("has_shape") and self.shape_mode.currentData() == SHAPE_BY_CATEGORY:
            payload["shape_map"] = self.level_symbols.values()
        else:
            payload["shape_map"] = dict(self.baseline.get("shape_map", {}))
        return payload

    def _validated_section(self):
        canonical = validate_bubble_style(self._payload(), figure=self.figure)
        if canonical["limits_mode"] == LIMITS_MANUAL:
            cmin, cmax, cmid = canonical["color_min"], canonical["color_max"], canonical["color_mid"]
            if cmin is None or cmax is None:
                raise BubbleStyleError(
                    "color_min" if cmin is None else "color_max",
                    tr("bubble.error.color_limits_number"),
                )
            if cmin >= cmax:
                raise BubbleStyleError("color_min", tr("bubble.error.color_limits_order"))
            if cmid is not None and not (cmin < cmid < cmax):
                raise BubbleStyleError("color_mid", tr("bubble.error.midpoint_range"))
        minimal = {}
        for key, value in canonical.items():
            if value != self.baseline.get(key):
                minimal[key] = value
        return minimal

    def _draw(self, section):
        merged = {**self.baseline, **section}
        apply_bubble_style(self.figure, section, style=self._full_style)
        if self._on_preview is not None:
            self._on_preview()
        elif getattr(self.figure, "canvas", None) is not None:
            self.figure.canvas.draw_idle()

    def preview(self):
        self.problem.hide()
        try:
            section = self._validated_section()
            self._draw(section)
        except BubbleStyleError as err:
            from analisi.bubble_catalog import translate_bubble_error
            self.problem.setText(translate_bubble_error(err))
            self.problem.show()
            return False
        return True

    def accept(self):
        self.problem.hide()
        try:
            section = self._validated_section()
            self._draw(section)
        except BubbleStyleError as err:
            from analisi.bubble_catalog import translate_bubble_error
            self.problem.setText(translate_bubble_error(err))
            self.problem.show()
            return
        self.result = section
        super().accept()

    def reject(self):
        try:
            apply_bubble_style(self.figure, self._before, style=self._full_style)
            if self._on_preview is not None:
                self._on_preview()
            elif getattr(self.figure, "canvas", None) is not None:
                self.figure.canvas.draw_idle()
        finally:
            super().reject()


def _column_levels(frame, column_name):
    if not column_name or column_name not in frame:
        return []
    from analisi.bubble_style import resolve_category_levels
    from analisi.category_order import WORKSHEET_ORDERS

    orders = frame.attrs.get(WORKSHEET_ORDERS) or frame.attrs.get("category_orders") or {}
    col_order = orders.get(column_name) if isinstance(orders, dict) else None
    levels, _disp, _rows = resolve_category_levels(
        frame[column_name].to_numpy(dtype=object),
        column_order=col_order,
        preserve_first_seen=False,
    )
    return [(item[0], item[1], item[2]) for item in levels]


def attach_analysis_dialog(dialog, saved):
    """Wire dynamic field visibility and custom level symbol/color pickers on AnalysisDialog."""
    controls = dialog.controls
    size_mode = controls[SIZE_MODE][1]
    fill_mode = controls[FILL_MODE][1]
    limits_mode = controls[COLOR_LIMITS][1]
    shape_mode = controls[SHAPE_MODE][1]
    group_col = controls["Group"][1]
    shape_col = controls["Shape"][1]
    palette = controls[PALETTE][1]
    reverse = controls[REVERSE_PALETTE][1]
    cat_field = controls[CATEGORY_COLORS][1]
    sym_field = controls[SHAPE_MAP][1]

    if isinstance(palette, PaletteCombo):
        palette.set_reverse(reverse.isChecked())
        reverse.toggled.connect(palette.set_reverse)

    cat_field.set_mapping(saved.get(CATEGORY_COLORS) or {})
    sym_field.set_mapping(saved.get(SHAPE_MAP) or {})

    def refresh_levels():
        g_name = group_col.currentData() or None
        cat_field.set_levels(_column_levels(dialog.data, g_name))
        s_name = shape_col.currentData() or None
        sym_field.set_levels(_column_levels(dialog.data, s_name))

    def edit_cat_colors():
        g_name = group_col.currentData() or None
        levels = _column_levels(dialog.data, g_name)
        if not levels:
            return
        dlg = CategoryColorsDialog(dialog, levels, cat_field.mapping())
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result is not None:
            cat_field.set_mapping(dlg.result)

    def edit_sym_map():
        s_name = shape_col.currentData() or None
        levels = _column_levels(dialog.data, s_name)
        if not levels:
            return
        miss_combo = controls[MISSING_SHAPE][1]
        dlg = LevelSymbolDialog(dialog, levels, sym_field.mapping(), miss_combo.value())
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result is not None:
            sym_field.set_mapping(dlg.result)
            miss_combo.set_value(dlg.missing_result)

    cat_field.button.clicked.connect(edit_cat_colors)
    sym_field.button.clicked.connect(edit_sym_map)

    def sync():
        sm = size_mode.currentData()
        fm = fill_mode.currentData()
        lm = limits_mode.currentData()
        shm = shape_mode.currentData()
        cont = fm == FILL_CONTINUOUS
        by_group = fm == FILL_BY_CATEGORY
        by_shape = shm == SHAPE_BY_CATEGORY
        dialog._set_field_visibility({
            "Size": sm == SIZE_BY_COLUMN,
            MAX_AREA: sm == SIZE_BY_COLUMN,
            FIXED_AREA: sm == SIZE_FIXED,
            "Group": by_group,
            CATEGORY_COLORS: by_group and bool(group_col.currentData()),
            FIXED_COLOR: fm == FILL_FIXED,
            "Color": cont,
            PALETTE: cont,
            REVERSE_PALETTE: cont,
            COLOR_LIMITS: cont,
            COLOR_MIN: cont and lm == LIMITS_MANUAL,
            COLOR_MID: cont,
            COLOR_MAX: cont and lm == LIMITS_MANUAL,
            MISSING_COLOR: cont,
            COLOR_LEGEND: cont,
            COLOR_TITLE: cont,
            "Shape": by_shape,
            FIXED_SHAPE: not by_shape,
            SHAPE_MAP: by_shape,
            MISSING_SHAPE: by_shape,
            SHAPE_LEGEND: by_shape,
        })
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)

    for w in (size_mode, fill_mode, limits_mode, shape_mode):
        w.currentIndexChanged.connect(sync)
    group_col.currentIndexChanged.connect(lambda: (refresh_levels(), sync()))
    shape_col.currentIndexChanged.connect(lambda: (refresh_levels(), sync()))
    refresh_levels()
    sync()


class BubbleInspectorSection:
    """Integrated live-previewing Bubble encoding controls inside ``GraphInspector``."""

    def __init__(self, inspector):
        self.inspector = inspector
        self.state = describe_bubble_artists(inspector.figure)
        self.baseline = baseline_bubble_style(inspector.figure)
        self.loading = False
        self.rows = {}

        form = inspector._section("bubble", tr("bubble.style.inspector.section"))
        self.size_mode = BubbleStyleDialog._choice_combo(SIZE_MODES, self.baseline["size_mode"])
        if not self.state.get("has_size"):
            idx = self.size_mode.findData(SIZE_BY_COLUMN)
            if idx >= 0:
                self.size_mode.removeItem(idx)
        self.max_area = QLineEdit()
        self.fixed_area = QLineEdit()
        self.show_size_legend = QCheckBox()

        avail_fill = list(FILL_MODES) if self.state.get("has_color") else [FILL_BY_CATEGORY, FILL_FIXED]
        self.fill_mode = BubbleStyleDialog._choice_combo(avail_fill, self.baseline["fill_mode"])
        self.fixed_color = ColorField(self.baseline["fixed_color"])
        self.palette = PaletteCombo(self.baseline["palette"], reverse=self.baseline["reverse"])
        self.reverse = QCheckBox()
        self.reverse.toggled.connect(self.palette.set_reverse)
        self.limits_mode = BubbleStyleDialog._choice_combo(LIMITS_MODES, self.baseline["limits_mode"])
        self.color_min = QLineEdit()
        self.color_mid = QLineEdit()
        self.color_max = QLineEdit()
        self.missing_color = ColorField(self.baseline["missing_color"])
        self.show_color_legend = QCheckBox()

        avail_shape = list(SHAPE_MODES) if self.state.get("has_shape") else [SHAPE_FIXED]
        self.shape_mode = BubbleStyleDialog._choice_combo(avail_shape, self.baseline["shape_mode"])
        self.fixed_shape = MarkerCombo(SHAPE_CHOICES, self.baseline["fixed_shape"])
        self.missing_shape = MarkerCombo(SHAPE_CHOICES, self.baseline["missing_shape"])
        self.show_shape_legend = QCheckBox()
        self.show_labels = QCheckBox()

        for key, lbl, widget, immediate in (
            ("size_mode", SIZE_MODE, self.size_mode, True),
            ("maximum_area", MAX_AREA, self.max_area, False),
            ("fixed_area", FIXED_AREA, self.fixed_area, False),
            ("show_size_legend", SIZE_LEGEND, self.show_size_legend, True),
            ("fill_mode", FILL_MODE, self.fill_mode, True),
            ("fixed_color", FIXED_COLOR, self.fixed_color, False),
            ("palette", PALETTE, self.palette, True),
            ("reverse", REVERSE_PALETTE, self.reverse, True),
            ("limits_mode", COLOR_LIMITS, self.limits_mode, True),
            ("color_min", COLOR_MIN, self.color_min, False),
            ("color_mid", COLOR_MID, self.color_mid, False),
            ("color_max", COLOR_MAX, self.color_max, False),
            ("missing_color", MISSING_COLOR, self.missing_color, False),
            ("show_color_legend", COLOR_LEGEND, self.show_color_legend, True),
            ("shape_mode", SHAPE_MODE, self.shape_mode, True),
            ("fixed_shape", FIXED_SHAPE, self.fixed_shape, True),
            ("missing_shape", MISSING_SHAPE, self.missing_shape, True),
            ("show_shape_legend", SHAPE_LEGEND, self.show_shape_legend, True),
            ("show_labels", SHOW_LABELS, self.show_labels, True),
        ):
            form.addRow(field_label(lbl), widget)
            self.rows[key] = (form, widget)
            source = f"bubble:{key}"
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(lambda _i=0, s=source: self._changed(s, True))
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda _v=False, s=source: self._changed(s, True))
            elif isinstance(widget, ColorField):
                widget.changed.connect(lambda s=source: self._changed(s, False))
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(lambda _t="", s=source: self._changed(s, False))

        self.warning_label = QLabel()
        self.warning_label.setObjectName("muted")
        self.warning_label.setWordWrap(True)
        form.addRow(self.warning_label)

        self.edit_button = QPushButton(tr("bubble.style.button"))
        self.edit_button.setAutoDefault(False)
        self.edit_button.clicked.connect(inspector.edit_bubble)
        form.addRow(self.edit_button)

        inspector._message(form, "bubble:error")
        inspector._finish(form, "bubble")

    def _changed(self, source, immediate):
        if self.loading:
            return
        self._sync_visibility()
        if immediate:
            self.inspector._now("bubble:section")
        else:
            self.inspector._schedule("bubble:section")

    def _sync_visibility(self):
        sm = self.size_mode.currentData()
        fm = self.fill_mode.currentData()
        lm = self.limits_mode.currentData()
        shm = self.shape_mode.currentData()
        cont = fm == FILL_CONTINUOUS
        by_shape = shm == SHAPE_BY_CATEGORY and bool(self.state.get("has_shape"))
        vis = {
            "maximum_area": sm == SIZE_BY_COLUMN,
            "fixed_area": sm == SIZE_FIXED,
            "show_size_legend": True,
            "fixed_color": fm == FILL_FIXED,
            "palette": cont,
            "reverse": cont,
            "limits_mode": cont,
            "color_min": cont and lm == LIMITS_MANUAL,
            "color_mid": cont,
            "color_max": cont and lm == LIMITS_MANUAL,
            "missing_color": cont,
            "show_color_legend": cont,
            "fixed_shape": not by_shape,
            "missing_shape": by_shape,
            "show_shape_legend": by_shape,
        }
        for key, visible in vis.items():
            form, w = self.rows[key]
            form.setRowVisible(w, visible)

    def load(self, draft):
        self.loading = True
        try:
            merged = {**self.baseline, **(draft.get("bubble") or {})}
            for combo, val in (
                (self.size_mode, merged["size_mode"]),
                (self.fill_mode, merged["fill_mode"]),
                (self.limits_mode, merged["limits_mode"]),
                (self.shape_mode, merged["shape_mode"]),
            ):
                idx = combo.findData(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.max_area.setText(f"{merged['maximum_area']:g}")
            self.fixed_area.setText(f"{merged['fixed_area']:g}")
            self.show_size_legend.setChecked(bool(merged["show_size_legend"]))
            self.fixed_color.setText(merged["fixed_color"])
            self.palette.set_value(merged["palette"])
            self.reverse.setChecked(bool(merged["reverse"]))
            self.palette.set_reverse(bool(merged["reverse"]))
            self.color_min.setText("" if merged["color_min"] is None else f"{merged['color_min']:g}")
            self.color_mid.setText("" if merged["color_mid"] is None else f"{merged['color_mid']:g}")
            self.color_max.setText("" if merged["color_max"] is None else f"{merged['color_max']:g}")
            self.missing_color.setText(merged["missing_color"])
            self.show_color_legend.setChecked(bool(merged["show_color_legend"]))
            self.fixed_shape.set_value(merged["fixed_shape"])
            self.missing_shape.set_value(merged["missing_shape"])
            self.show_shape_legend.setChecked(bool(merged["show_shape_legend"]))
            self.show_labels.setChecked(bool(merged["show_labels"]))
            self._sync_visibility()
            warn = self.state.get("shape_warning")
            self.warning_label.setText(warn or "")
            self.warning_label.setVisible(bool(warn))
        finally:
            self.loading = False

    def write(self, style):
        existing = dict(style.get("bubble") or {})
        payload = {
            **existing,
            "size_mode": self.size_mode.currentData(),
            "maximum_area": self.max_area.text(),
            "fixed_area": self.fixed_area.text(),
            "show_size_legend": self.show_size_legend.isChecked(),
            "fill_mode": self.fill_mode.currentData(),
            "fixed_color": self.fixed_color.text(),
            "palette": self.palette.value(),
            "reverse": self.reverse.isChecked(),
            "limits_mode": self.limits_mode.currentData(),
            "color_min": self.color_min.text() or None,
            "color_mid": self.color_mid.text() or None,
            "color_max": self.color_max.text() or None,
            "missing_color": self.missing_color.text(),
            "show_color_legend": self.show_color_legend.isChecked(),
            "shape_mode": self.shape_mode.currentData(),
            "fixed_shape": self.fixed_shape.value(),
            "missing_shape": self.missing_shape.value(),
            "show_shape_legend": self.show_shape_legend.isChecked(),
            "show_labels": self.show_labels.isChecked(),
        }
        canonical = validate_bubble_style(payload, figure=self.inspector.figure)
        if canonical["limits_mode"] == LIMITS_MANUAL:
            cmin, cmax, cmid = canonical["color_min"], canonical["color_max"], canonical["color_mid"]
            if cmin is None or cmax is None:
                raise ValueError(tr("bubble.error.color_limits_number"))
            if cmin >= cmax:
                raise ValueError(tr("bubble.error.color_limits_order"))
            if cmid is not None and not (cmin < cmid < cmax):
                raise ValueError(tr("bubble.error.midpoint_range"))
        minimal = {k: v for k, v in canonical.items() if v != self.baseline.get(k)}
        if minimal:
            style["bubble"] = minimal
        else:
            style.pop("bubble", None)

