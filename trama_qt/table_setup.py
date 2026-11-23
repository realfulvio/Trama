"""Qt worksheet setup using the same templates as the Standard interface."""
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from analisi._version import RELEASE_CHANNEL, VERSION
from analisi.data import MAX_COLUMNS
from analisi.i18n import tr
from analisi.table_templates import GROUPED_FORMATS, TEMPLATES, XY_FORMATS, _blank_xy, format_label, template_detail

from . import theme


class TableSetup(QWidget):
    def __init__(self, parent=None, *, open_project=None, create_info=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.types = QListWidget()
        self.types.setAccessibleName(tr("setup.new_data_table"))
        self.types.setMinimumWidth(145)
        self.types.addItems([format_label(template.kind) for template in TEMPLATES])
        if open_project is not None:
            panel = QFrame()
            panel.setObjectName("setupSidebar")
            panel.setFixedWidth(234)
            sidebar = QVBoxLayout(panel)
            sidebar.setContentsMargins(10, 12, 10, 10)
            sidebar.setSpacing(6)
            logo = QLabel()
            pixmap = QPixmap(str(theme.ASSETS / "brand" / "trama-wordmark-panel.png"))
            ratio = self.devicePixelRatioF()
            pixmap = pixmap.scaledToWidth(round(212 * ratio), Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            logo.setPixmap(pixmap)
            logo.setAccessibleName("Trama")
            sidebar.addWidget(logo)
            sidebar.addWidget(QLabel(tr("setup.version", version=f"{VERSION} {RELEASE_CHANNEL}")))
            sidebar.addWidget(QLabel(tr("setup.new_data_table")))
            self.types.setObjectName("setupTypes")
            sidebar.addWidget(self.types, 1)
            sidebar.addWidget(QLabel(tr("setup.existing_project")))
            for label, callback in (("open_file", open_project), ("new_project_info", create_info)):
                button = QPushButton(tr(f"setup.{label}"))
                button.clicked.connect(callback)
                sidebar.addWidget(button)
            row.addWidget(panel)
        else:
            self.types.setMaximumWidth(185)
            row.addWidget(self.types)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        row.addWidget(scroll, 1)
        content = QWidget()
        scroll.setWidget(content)
        detail = QVBoxLayout(content)
        detail.setContentsMargins(12, 8, 12, 8)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        detail.addWidget(self.heading)
        self.description = QLabel()
        self.description.setWordWrap(True)
        detail.addWidget(self.description)

        previews = QHBoxLayout()
        table_box = QVBoxLayout()
        table_box.addWidget(QLabel(tr("setup.worksheet_preview")))
        self.preview = QTableWidget(4, 0)
        self.preview.setAccessibleName(tr("setup.worksheet_preview"))
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview.setFixedHeight(138)
        table_box.addWidget(self.preview)
        previews.addLayout(table_box, 1)
        chart_box = QVBoxLayout()
        chart_box.addWidget(QLabel(tr("setup.graph_example")))
        self.figure = Figure(figsize=(1.6, 1.35))
        self.chart = FigureCanvasQTAgg(self.figure)
        self.chart.setFixedSize(142, 138)
        chart_box.addWidget(self.chart)
        previews.addLayout(chart_box)
        detail.addLayout(previews)
        self.preview_note = QLabel()
        self.preview_note.setWordWrap(True)
        detail.addWidget(self.preview_note)

        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem(tr("setup.enter_data"), False)
        self.mode.addItem(tr("setup.sample_data"), True)
        form.addRow(tr("setup.data_table"), self.mode)
        self.encoding = QComboBox()
        self.encoding_label = QLabel(tr("setup.structure"))
        form.addRow(self.encoding_label, self.encoding)
        self.series = QSpinBox()
        self.series.setRange(1, 16)
        self.series.setValue(2)
        form.addRow(tr("setup.data_sets"), self.series)
        self.replicates = QSpinBox()
        self.replicates.setRange(2, 256)
        self.replicates.setValue(2)
        form.addRow(tr("setup.replicates"), self.replicates)
        self.row_titles = QCheckBox(tr("setup.row_titles"))
        self.row_titles.setChecked(True)
        form.addRow(self.row_titles)
        self.form = form
        detail.addLayout(form)
        detail.addStretch(1)

        self.types.currentRowChanged.connect(self._choose_kind)
        for widget in (self.mode, self.encoding):
            widget.currentIndexChanged.connect(self.refresh)
        self.series.valueChanged.connect(self.refresh)
        self.replicates.valueChanged.connect(self.refresh)
        self.row_titles.toggled.connect(self.refresh)
        theme.SIGNALS.changed.connect(self.refresh)
        self.types.setCurrentRow(0)

    def _formats(self):
        kind = TEMPLATES[max(0, self.types.currentRow())].kind
        return XY_FORMATS if kind == "xy" else GROUPED_FORMATS if kind == "grouped" else {}

    def _choose_kind(self):
        blocked = self.encoding.blockSignals(True)
        self.encoding.clear()
        for key in self._formats():
            self.encoding.addItem(format_label(key), key)
        self.encoding.blockSignals(blocked)
        self.refresh()

    def selection(self):
        template = TEMPLATES[max(0, self.types.currentRow())]
        template = self._formats().get(self.encoding.currentData(), template)
        sample = bool(self.mode.currentData())
        if template.kind.casefold().startswith("xy") and not sample:
            template = _blank_xy(template, self.series.value(), self.replicates.value(), self.row_titles.isChecked())
        return template, sample

    def refresh(self):
        base = TEMPLATES[max(0, self.types.currentRow())]
        numeric_xy = base.kind == "xy" and not self.mode.currentData()
        self.form.setRowVisible(self.encoding, bool(self._formats()))
        self.form.setRowVisible(self.series, numeric_xy)
        self.form.setRowVisible(self.replicates, numeric_xy)
        self.form.setRowVisible(self.row_titles, numeric_xy)
        self.replicates.setEnabled(self.encoding.currentData() == "Replicates in side-by-side subcolumns")
        maximum = min(256, (MAX_COLUMNS - 1 - int(self.row_titles.isChecked())) // self.series.value())
        previous = self.replicates.blockSignals(True)
        self.replicates.setMaximum(maximum)
        self.replicates.blockSignals(previous)

        template, sample = self.selection()
        self.heading.setText(tr(f"setup.heading.{base.kind}"))
        self.description.setText(template_detail(template))
        columns = template.columns[:8]
        self.preview.clearContents()
        self.preview.setColumnCount(len(columns))
        self.preview.setHorizontalHeaderLabels(columns)
        self.preview.horizontalHeader().setMinimumSectionSize(55)
        self.preview.horizontalHeader().setDefaultSectionSize(88)
        for i, values in enumerate(template.rows[:4] if sample else ()):
            for j, value in enumerate(values[:len(columns)]):
                self.preview.setItem(i, j, QTableWidgetItem("" if value is None else str(value)))
        more = len(template.columns) > len(columns)
        self.preview_note.setVisible(more)
        if more:
            self.preview_note.setText(tr("setup.preview_note", shown=len(columns), total=len(template.columns)))
        self._draw_chart(base.kind)

    def _draw_chart(self, kind):
        self.figure.clear()
        self.figure.set_facecolor(theme.T["panel"])
        axes = self.figure.add_axes((.13, .16, .80, .78))
        axes.set_facecolor(theme.T["panel"])
        axes.set(xticks=[], yticks=[])
        axes.spines[["top", "right"]].set_visible(False)
        for side in ("left", "bottom"):
            axes.spines[side].set_color(theme.T["text2"])
        blue, teal = "#3475ae", "#148f81"
        if kind == "parts_of_whole":
            axes.pie([22, 16, 12, 8], colors=[blue, teal, "#e29954", "#9b78a9"], wedgeprops={"width": .56})
        elif kind in {"column", "grouped", "contingency", "nested"}:
            axes.bar([0, 1, 3, 4], [12, 17, 18, 24], color=[blue, teal, blue, teal], width=.8)
        elif kind == "survival":
            axes.step([0, 3, 7, 9], [1, .85, .6, .45], where="post", color=blue)
            axes.step([0, 2, 6, 9], [1, .75, .62, .55], where="post", color=teal)
        else:
            axes.plot([0, 1, 2, 3], [2, 4, 8, 9], "o", color=blue, markersize=4)
            axes.plot([0, 1, 2, 3], [1, 5, 11, 13], "o", color=teal, markersize=4)
        self.chart.draw_idle()


class TableSetupDialog(QDialog):
    def __init__(self, parent, *, sample=False):
        super().__init__(parent)
        self.setWindowTitle(tr("setup.dialog_title"))
        self.resize(765, 480)
        layout = QVBoxLayout(self)
        self.setup = TableSetup(self)
        self.setup.mode.setCurrentIndex(self.setup.mode.findData(sample))
        layout.addWidget(self.setup)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("setup.create"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setup.types.setFocus(Qt.FocusReason.OtherFocusReason)
