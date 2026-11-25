"""The Classic Qt welcome page and the typed worksheet chooser."""
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QMenu, QPushButton, QRadioButton, QScrollArea,
                               QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from analisi._version import RELEASE_CHANNEL, VERSION
from analisi.data import MAX_COLUMNS
from analisi.i18n import tr
from analisi.table_templates import (EXAMPLE_KEYS, GROUPED_FORMATS, TEMPLATES, XY_EXAMPLES, XY_FORMATS,
                                    _blank_xy, format_label, template_detail)

from . import theme
from .sessions import elide, recent_projects


class TableSetup(QWidget):
    def __init__(self, parent=None, *, open_project=None, open_path=None, create_info=None, recover=None):
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
            self.types.ensurePolished()
            self.types.setFixedHeight(sum(self.types.sizeHintForRow(i) for i in range(self.types.count())) + 6)
            sidebar.addWidget(self.types)
            sidebar.addWidget(QLabel(tr("setup.existing_project")))
            sidebar.addWidget(self._button(tr("setup.open_file"), open_project))
            if open_path is not None:
                self.recent = QPushButton(tr("setup.recent_projects"))
                self.recent.setObjectName("recentProjects")
                menu = QMenu(self.recent)
                menu.setToolTipsVisible(True)
                menu.aboutToShow.connect(lambda: self._recent_menu(menu, open_path))
                self.recent.setMenu(menu)
                sidebar.addWidget(self.recent)
            if recover is not None:
                button = QToolButton()
                button.setDefaultAction(recover)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                sidebar.addWidget(button)
            sidebar.addWidget(self._button(tr("setup.new_project_info"), create_info))
            sidebar.addStretch(1)
            sidebar.addWidget(self._button(tr("setup.quick_start"), self._quick_start))
            row.addWidget(panel)
        else:
            self.types.setMaximumWidth(185)
            row.addWidget(self.types)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        row.addWidget(scroll, 1)
        content = QWidget()
        content.setMaximumWidth(790)
        scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        detail = self.detail = QVBoxLayout(content)
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
        self.preview_note = QLabel()
        self.preview_note.setWordWrap(True)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        modes = QWidget()
        mode_row = QVBoxLayout(modes)
        mode_row.setContentsMargins(0, 0, 0, 0)
        self.empty = QRadioButton(tr("setup.blank_table"))
        self.sample = QRadioButton(tr("setup.with_example"))
        for option in (self.empty, self.sample):
            option.setObjectName("setupMode")
            mode_row.addWidget(option)
        self.empty.setChecked(True)
        form.addRow(tr("setup.data_table"), modes)
        self.examples = QComboBox()
        form.addRow(tr("setup.select_sample"), self.examples)
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
        detail.addLayout(previews)
        detail.addWidget(self.preview_note)
        detail.addStretch(1)

        self.types.currentRowChanged.connect(self._choose_kind)
        self.sample.toggled.connect(self.refresh)
        for widget in (self.examples, self.encoding):
            widget.currentIndexChanged.connect(self.refresh)
        self.series.valueChanged.connect(self.refresh)
        self.replicates.valueChanged.connect(self.refresh)
        self.row_titles.toggled.connect(self.refresh)
        theme.SIGNALS.changed.connect(self.refresh)
        self.types.setCurrentRow(0)

    @staticmethod
    def _button(label, command):
        button = QPushButton(label)
        button.clicked.connect(command)
        return button

    @staticmethod
    def _quick_start():
        QDesktopServices.openUrl(QUrl("https://github.com/realfulvio/Trama/blob/main/docs/getting-started.md"))

    @staticmethod
    def _recent_menu(menu, open_path):
        menu.clear()
        paths = recent_projects()
        if not paths:
            menu.addAction(tr("setup.no_recent_projects")).setEnabled(False)
            return
        names = [path.name for path in paths]
        for path in paths:
            label = path.name if names.count(path.name) == 1 else f"{path.name} · {path.parent}"
            action = menu.addAction(elide(label, 60).replace("&", "&&"))
            action.setToolTip(str(path))
            action.triggered.connect(lambda _checked=False, chosen=path: open_path(chosen))

    @property
    def create_label(self):
        return tr("setup.create_example" if self.sample.isChecked() else "setup.create_blank")

    def bind_create(self, command):
        button = self._button(self.create_label, command)
        button.setObjectName("primary")
        self.sample.toggled.connect(lambda: button.setText(self.create_label))
        self.detail.insertWidget(self.detail.count() - 1, button, 0, Qt.AlignmentFlag.AlignLeft)

    def _formats(self):
        kind = TEMPLATES[max(0, self.types.currentRow())].kind
        return XY_FORMATS if kind == "xy" else GROUPED_FORMATS if kind == "grouped" else {}

    def _choose_kind(self):
        blocked = self.encoding.blockSignals(True)
        self.encoding.clear()
        for key in self._formats():
            self.encoding.addItem(format_label(key), key)
        self.encoding.blockSignals(blocked)
        blocked = self.examples.blockSignals(True)
        self.examples.clear()
        base = TEMPLATES[max(0, self.types.currentRow())]
        if base.kind == "xy":
            for _, label, code in XY_EXAMPLES:
                self.examples.addItem(tr(EXAMPLE_KEYS[label]), code)
        elif base.kind == "grouped":
            for index, code in enumerate(GROUPED_FORMATS):
                label = tr("example.grouped") if index == 0 else format_label(code)
                self.examples.addItem(label, code)
        else:
            self.examples.addItem(tr(f"example.{base.kind}"))
        self.examples.blockSignals(blocked)
        self.refresh()

    def selection(self):
        template = TEMPLATES[max(0, self.types.currentRow())]
        sample = self.sample.isChecked()
        code = self.examples.currentData() if sample else self.encoding.currentData()
        template = self._formats().get(code, template)
        if template.kind.casefold().startswith("xy") and not sample:
            template = _blank_xy(template, self.series.value(), self.replicates.value(), self.row_titles.isChecked())
        return template, sample

    def refresh(self):
        base = TEMPLATES[max(0, self.types.currentRow())]
        sample = self.sample.isChecked()
        numeric_xy = base.kind == "xy" and not sample
        self.form.setRowVisible(self.examples, sample)
        self.form.setRowVisible(self.encoding, bool(self._formats()) and not sample)
        self.form.setRowVisible(self.series, numeric_xy)
        self.form.setRowVisible(self.replicates, numeric_xy and self.encoding.currentData()
                                == "Replicates in side-by-side subcolumns")
        self.form.setRowVisible(self.row_titles, numeric_xy)
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
        self.setWindowTitle(tr("setup.qt_dialog_title"))
        self.resize(765, 480)
        layout = QVBoxLayout(self)
        self.setup = TableSetup(self)
        self.setup.sample.setChecked(sample)
        layout.addWidget(self.setup)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        create = buttons.button(QDialogButtonBox.StandardButton.Ok)
        create.setText(self.setup.create_label)
        self.setup.sample.toggled.connect(lambda: create.setText(self.setup.create_label))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setup.types.setFocus(Qt.FocusReason.OtherFocusReason)
