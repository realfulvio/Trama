"""The Classic Qt welcome page and the typed worksheet chooser."""
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QBoxLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QListWidget, QMenu, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

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
        self.welcome = open_project is not None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.types = QListWidget()
        self.types.setAccessibleName(tr("setup.new_data_table"))
        self.types.setMinimumWidth(145)
        self.types.addItems([format_label(template.kind) for template in TEMPLATES])
        if self.welcome:
            row.setSpacing(0)
            self.sidebar = self._sidebar()
            row.addWidget(self.sidebar)
        else:
            self.types.setMaximumWidth(185)
            row.addWidget(self.types)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        row.addWidget(scroll, 1)
        content = QWidget()
        if self.welcome:
            content.setObjectName("setupWelcomeContent")
            scroll.setFrameShape(QFrame.Shape.NoFrame)
        else:
            content.setMaximumWidth(790)
        scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        detail = self.detail = QVBoxLayout(content)
        detail.setContentsMargins(*((24, 20, 24, 20) if self.welcome else (12, 8, 12, 8)))
        if self.welcome:
            detail.setSpacing(14)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        detail.addWidget(self.heading)
        self.description = QLabel()
        self.description.setWordWrap(True)
        if self.welcome:
            self.description.setObjectName("pageSubtitle")
        detail.addWidget(self.description)

        previews = QVBoxLayout() if self.welcome else QHBoxLayout()
        table_box = QVBoxLayout()
        table_box.addWidget(self._caption("setup.preview_title") if self.welcome else QLabel(tr("setup.worksheet_preview")))
        self.preview = QTableWidget(4, 0)
        self.preview.setAccessibleName(tr("setup.worksheet_preview"))
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        if self.welcome:
            self.preview.verticalHeader().setDefaultSectionSize(24)
            self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.preview.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            self.preview.setAlternatingRowColors(True)
            self.preview.setTabKeyNavigation(False)
        else:
            self.preview.setFixedHeight(138)
        table_box.addWidget(self.preview)
        previews.addLayout(table_box, 1)
        self.preview_note = QLabel()
        self.preview_note.setWordWrap(True)
        if self.welcome:
            self.preview_note.setObjectName("muted")
            previews.addWidget(self.preview_note)
            previews.addWidget(self._divider())
        chart_box = QVBoxLayout()
        chart_box.addWidget(self._caption("setup.chart_title") if self.welcome else QLabel(tr("setup.graph_example")))
        self.figure = Figure(figsize=(1.6, 1.35))
        self.chart = FigureCanvasQTAgg(self.figure)
        if self.welcome:
            self.chart.setFixedHeight(146)
            self.chart.setMinimumWidth(140)
            self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.chart.setFixedSize(142, 138)
        chart_box.addWidget(self.chart)
        previews.addLayout(chart_box)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow if self.welcome
                                  else QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        if self.welcome:
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            form.setVerticalSpacing(9)
        modes = QWidget()
        mode_row = QVBoxLayout(modes)
        mode_row.setContentsMargins(0, 0, 0, 0)
        self.empty = QRadioButton(tr("setup.blank_table"))
        self.sample = QRadioButton(tr("setup.example_data" if self.welcome else "setup.with_example"))
        for option in (self.empty, self.sample):
            option.setObjectName("setupMode")
            mode_row.addWidget(option)
        self.empty.setChecked(True)
        form.addRow(tr("setup.data_origin" if self.welcome else "setup.data_table"), modes)
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
        if self.welcome:
            for index in range(form.rowCount()):
                item = form.itemAt(index, QFormLayout.ItemRole.LabelRole)
                if item is not None:
                    item.widget().setObjectName("sectionTitle")
            self.encoding.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.examples.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.series.setMaximumWidth(88)
            self.replicates.setMaximumWidth(88)
            self.configuration, settings = self._card()
            settings.addWidget(self._caption("setup.configuration"))
            settings.addWidget(self._divider())
            settings.addLayout(form)
            settings.addStretch(1)
            settings.addWidget(self._divider())
            self.create_row = QHBoxLayout()
            settings.addLayout(self.create_row)
            preview_card, preview_layout = self._card()
            preview_layout.addLayout(previews)
            self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
            self.columns.setSpacing(14)
            self.columns.addWidget(self.configuration)
            self.columns.addWidget(preview_card, 1)
            detail.addLayout(self.columns)
            detail.addWidget(self._projects(open_project, open_path, create_info, recover))
        else:
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.welcome:
            return
        width = event.size().width()
        wide = width >= 900
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        self.columns.setDirection(direction)
        if self.project_cards is not None:
            self.project_cards.setDirection(direction)
        self.sidebar.setFixedWidth(226 if width >= 1160 else 204 if wide else 176)
        if wide:
            self.configuration.setFixedWidth(354 if width >= 1160 else 302)
        else:
            self.configuration.setMinimumWidth(0)
            self.configuration.setMaximumWidth(16777215)

    def _sidebar(self):
        panel = QFrame()
        panel.setObjectName("setupSidebar")
        sidebar = QVBoxLayout(panel)
        sidebar.setContentsMargins(14, 18, 14, 14)
        sidebar.setSpacing(10)
        logo = QLabel()
        pixmap = QPixmap(str(theme.ASSETS / "brand" / "trama-wordmark-panel.png"))
        ratio = self.devicePixelRatioF()
        pixmap = pixmap.scaledToWidth(round(146 * ratio), Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio)
        logo.setPixmap(pixmap)
        logo.setAccessibleName("Trama")
        sidebar.addWidget(logo, 0, Qt.AlignmentFlag.AlignLeft)
        sidebar.addWidget(QLabel(tr("setup.table_type")))
        self.types.setObjectName("setupTypes")
        self.types.setIconSize(QSize(17, 17))
        self.types.setMinimumHeight(0)
        self.types.setMaximumHeight(self.types.count() * 36 + 12)
        self.types.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for index, name in enumerate(("chart-line", "chart-column", "table-2", "table", "chart-spline",
                                      "chart-column", "table-2", "table")):
            item = self.types.item(index)
            item.setSizeHint(QSize(136, 36))
            item.setIcon(theme.icon(name, "setup_icon"))
        sidebar.addWidget(self.types, 1)
        sidebar.addStretch()
        sidebar.addWidget(self._button(tr("setup.quick_start"), self._quick_start, "book-open"))
        sidebar.addWidget(QLabel(tr("setup.version", version=f"{VERSION} {RELEASE_CHANNEL}")))
        return panel

    def _projects(self, open_project, open_path, create_info, recover):
        panel, layout = self._card()
        heading = QHBoxLayout()
        heading.addWidget(self._caption("setup.recent_projects"))
        heading.addStretch(1)
        heading.addWidget(self._button(tr("setup.open_file"), open_project, "folder-open"))
        layout.addLayout(heading)
        paths = recent_projects() if open_path is not None else ()
        self.project_cards = None
        if paths:
            projects = self.project_cards = QBoxLayout(QBoxLayout.Direction.LeftToRight)
            names = [path.name for path in paths]
            for path in paths[:2]:
                name = path.name if names.count(path.name) == 1 else f"{path.name} · {path.parent}"
                card = self._button(elide(name, 37).replace("&", "&&"),
                                    lambda chosen=path: open_path(chosen), "table-2")
                card.setObjectName("setupRecent")
                card.setToolTip(str(path))
                projects.addWidget(card, 1)
            if len(paths) > 2:
                more = QPushButton(tr("setup.more_projects"))
                menu = QMenu(more)
                menu.setToolTipsVisible(True)
                self._recent_menu(menu, open_path, paths[2:])
                more.setMenu(menu)
                projects.addWidget(more)
            layout.addLayout(projects)
        else:
            empty = QLabel(tr("setup.no_recent_projects"))
            empty.setObjectName("muted")
            layout.addWidget(empty)
        actions = QHBoxLayout()
        if recover is not None:
            button = QToolButton()
            button.setDefaultAction(recover)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            actions.addWidget(button)
        actions.addWidget(self._button(tr("setup.new_project_info"), create_info, "info"))
        actions.addStretch(1)
        layout.addLayout(actions)
        return panel

    @staticmethod
    def _card():
        panel = QFrame()
        panel.setObjectName("setupCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        return panel, layout

    @staticmethod
    def _caption(key):
        label = QLabel(tr(key))
        label.setObjectName("setupCaption")
        return label

    @staticmethod
    def _divider():
        line = QFrame()
        line.setObjectName("setupDivider")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _button(label, command, icon=None):
        button = QPushButton(label)
        button.clicked.connect(lambda: command())
        if icon is not None:
            button.setIcon(theme.icon(icon, "setup_icon" if icon == "book-open" else "accent"))
        return button

    @staticmethod
    def _quick_start():
        QDesktopServices.openUrl(QUrl("https://github.com/realfulvio/Trama/blob/main/docs/getting-started.md"))

    @staticmethod
    def _recent_menu(menu, open_path, paths):
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
        button.setIcon(theme.icon("plus", "on_accent"))
        button.setMinimumHeight(36)
        button.setDefault(True)
        self.sample.toggled.connect(lambda: button.setText(self.create_label))
        self.create_row.addWidget(button)
        self.create_row.addStretch(1)
        self.setTabOrder(self.row_titles, button)

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
        self.heading.setText(tr("setup.xy_title" if self.welcome and base.kind == "xy"
                                else f"setup.heading.{base.kind}"))
        self.description.setText(template_detail(template))
        columns = template.columns[:8]
        self.preview.clearContents()
        self.preview.setColumnCount(len(columns))
        headings = {"Row title": tr("setup.preview_row_title"), "Control": tr("setup.preview_control"),
                    "Treatment": tr("setup.preview_treatment")}
        self.preview.setHorizontalHeaderLabels([headings.get(name, name) for name in columns]
                                               if self.welcome else columns)
        self.preview.horizontalHeader().setMinimumSectionSize(55)
        self.preview.horizontalHeader().setDefaultSectionSize(88)
        for i, values in enumerate(template.rows[:4] if sample else ()):
            for j, value in enumerate(values[:len(columns)]):
                self.preview.setItem(i, j, QTableWidgetItem("" if value is None else str(value)))
        if self.welcome:
            # Keep all four rows visible when wide headings need a horizontal scrollbar.
            header_height = self.preview.horizontalHeader().sizeHint().height()
            rows_height = self.preview.verticalHeader().defaultSectionSize() * self.preview.rowCount()
            scrollbar_height = self.preview.horizontalScrollBar().sizeHint().height()
            self.preview.setFixedHeight(header_height + rows_height + scrollbar_height
                                        + 2 * self.preview.frameWidth())
        more = len(template.columns) > len(columns)
        self.preview_note.setVisible(more)
        if more:
            self.preview_note.setText(tr("setup.preview_note", shown=len(columns), total=len(template.columns)))
        self._draw_chart(base.kind)

    def _draw_chart(self, kind):
        self.figure.clear()
        self.figure.set_facecolor(theme.T["panel"])
        axes = self.figure.add_axes((.11, .26, .85, .62) if self.welcome and kind == "xy"
                                   else (.13, .16, .80, .78))
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
        elif self.welcome and kind == "xy":
            x = [1, 2, 3, 4]
            axes.plot(x, [2, 4, 8, 9], "o", color=blue, markersize=4, label=tr("setup.preview_control"))
            if self.sample.isChecked() or self.series.value() > 1:
                axes.plot(x, [1, 5, 11, 13], "o", color=teal, markersize=4, label=tr("setup.preview_treatment"))
            axes.set(xticks=x, yticks=[0, 5, 10, 15], xlim=(.65, 4.35), ylim=(0, 15), xlabel="X", ylabel="Y")
            axes.tick_params(labelsize=8, length=3, colors=theme.T["text2"])
            for label in (axes.xaxis.label, axes.yaxis.label):
                label.set_size(8)
                label.set_color(theme.T["text2"])
            axes.set_axisbelow(True)
            axes.grid(axis="y", color=theme.T["grid"], linewidth=.7)
            legend = axes.legend(loc="upper left", bbox_to_anchor=(0, 1.2), borderaxespad=0,
                                 ncols=2, frameon=False, fontsize=8, handlelength=1)
            for text in legend.get_texts():
                text.set_color(theme.T["text"])
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
