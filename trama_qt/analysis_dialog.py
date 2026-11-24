"""The analysis dialog, built from the field specification of ``analisi.workbench.METHODS``.

Each analysis declares its fields as column roles, choices, flags, numbers or text. The Qt dialog
renders every declared field directly: Variables holds the column roles, Options the rest. The few
compound editors of the classic dialog (pair lists, profiles, term pickers…) keep the value of the
analysis being edited, or the engine default for a new one.
"""
from copy import deepcopy
from unicodedata import combining, normalize

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QHeaderView, QAbstractItemView)

from analisi.anova_planned_contrasts import ALPHA as CONTRAST_ALPHA, CONTRAST_LIST, CORRECTION as CONTRAST_CORRECTION
from analisi.anova_planned_contrasts import FACTOR_LIST as CONTRAST_FACTOR_LIST
from analisi.anova_terms import TERM_LIST
from analisi import curve_pipeline, curve_pipeline_dialog, lognormal_tests, regression_range, ttest_options
from analisi.custom_fit import CUSTOM_EQUATION, DEFAULT_EQUATION, EQUATION_TEXT, EXAMPLE_PARAMETERS
from analisi.data import decimal_comma
from analisi import (
    cluster_silhouette,
    cohen_kappa as kappa,
    cox_exact,
    cox_outputs,
    interaction_plot_catalog,
    raincloud_plot_catalog,
)
from analisi import cohen_kappa_options as kappa_text, cohen_kappa_workbench as kappa_form
from analisi import extract_rearrange as extraction
from analisi.field_error import FieldError
from analisi.parameter_intervals import REPORT_LOG_IC50, has_ic50
from analisi.replicate_fit import MERGE_REPLICATES, replicate_groups
from analisi.hierarchical_gap import GAP_DATA, GAP_OPTIONS, GAP_PLOT
from analisi.hierarchical_workbench import (HIERARCHICAL_TABS, HIERARCHY_GRAPH, check_hierarchical_options,
                                           check_hierarchy_view, saved_hierarchical_options)
from analisi import brunner_munzel, kmeans_options, kmeans_reports, mean_permutation, mood_median, yuen
from analisi import mean_permutation_options as permutation_text
from analisi import nonlinear_calibration as calibration
from analisi import ordinal_logit as ordinal
from analisi import paired_proportions as paired
from analisi.paired_graphs import TTEST_ESTIMATION
from analisi.variance_ratio import SHOW as TTEST_VARIANCE
from analisi import mcnemar_power, monte_carlo, plot_function, power_plan, rmst, transpose_xy
from analisi import rmst_dialog, rmst_workbench as rmst_form
from analisi import tolerance_intervals as tolerance
from analisi import weibull_aft as weibull
from analisi import weibull_aft_workbench as weibull_form
from analisi.i18n import active_language, tr, translate_message, ui
from analisi.select_transform import SELECT_TRANSFORM, check_options as check_select_transform
from analisi.xy_series import XY_METHOD, check_xy_options, retain_recipe_options
from analisi.survival_input import (PAIRWISE_CORRECTION, PAIRWISE_FIELDS, PAIRWISE_SCOPE, PAIRWISE_PAIR_LIST,
                                     pairwise_corrections, pairwise_scope)
from analisi.workbench import (CLASSIC_RESPONSES, GROUP_CHOICE, GROUPS, METHODS, MULTIPLE, OPTIONAL,
                               OPTIONAL_MULTIPLE, TEXT, check_survival_options, classic_roles)
from analisi.stats import GEOMETRIC_REPORT, SUMMARY_FORMAT, summary_confidence, summary_fields

from . import anova_model, ellipse_groups, global_catalog, global_fit, logistic_validation, planned_contrasts
from . import kmeans_stability as stability_options
from . import bland_altman_repeated as repeated_agreement
from . import rm_sphericity_dialog as sphericity_options
from . import icc as icc_binding
from . import ecdf_graph as ecdf_binding
from . import interaction_plot as interaction_binding
from . import precision_recall as precision_options
from . import raincloud_plot as raincloud_binding
from . import pareto_plot as pareto_binding
from . import reshape_long_wide as reshape_editor
from . import select_transform as select_editor
from . import standard_curve as calibration_options
from . import worksheet_join as join_editor
from . import kappa_options, ordinal_options, permutation_options, rmst_options, survival_pairs, weibull_options
from .function_curves import FunctionCurves
from .transpose_sets import TransposeSets
from .labels import choice_label, field_label, method_label
from .predictor_profiles import Profiles
from .strings import qt
from .theme import fit_dialog

try:  # Optional helpers: the dialog still works if a later refactor moves them.
    from analisi.hierarchical_workbench import hierarchy_view_available
except Exception:  # pragma: no cover
    def hierarchy_view_available(_frame):
        return True

try:
    from analisi.custom_fit import PARAMETER_LIST
except Exception:  # pragma: no cover
    PARAMETER_LIST = "Parameter list"

CATEGORY_ROLES = {"Group", "Rows", "Columns", "Subject", "Row label", "Row factor variable",
                  "Column factor variable", "Row (treatment) variable", "Column (outcome) variable",
                  "X categories", "Y categories", "X factor", "Series factor"}
VARIABLE_KINDS = (None, OPTIONAL, MULTIPLE, OPTIONAL_MULTIPLE)
PLANNED_PANEL_FIELDS = {CONTRAST_CORRECTION, CONTRAST_ALPHA}


def _text_defaults(method):
    """Defaults the classic dialog types into text fields (status codes, colours)."""
    defaults = {}
    try:
        if method == "Kaplan–Meier survival":
            from analisi.survival_input import STATUS_DEFAULTS
            defaults.update(STATUS_DEFAULTS)
        elif method == "Cox regression":
            from analisi.cox_outputs import STATUS_DEFAULTS
            defaults.update(STATUS_DEFAULTS)
        elif method == "Prune rows":
            defaults["X threshold"] = "0"
        else:
            from analisi.competing_risks_workbench import COMPETING_RISKS, DEFAULTS
            if method == COMPETING_RISKS:
                defaults.update(DEFAULTS)
            from analisi.heatmap import GRADIENT_COLORS, HEAT_MAP
            if method == HEAT_MAP:
                defaults.update(GRADIENT_COLORS)
                from analisi.heatmap_cell_labels import CELL_LABEL_COLOR, DEFAULT_LABEL_COLOR
                defaults[CELL_LABEL_COLOR] = DEFAULT_LABEL_COLOR
    except Exception:  # pragma: no cover - defaults are a convenience only
        pass
    return defaults


class ParameterTable(QTableWidget):
    """Name, start, lower, upper and fixed of each parameter of a user-defined equation."""

    HEADERS = ("name", "start", "lower", "upper", "fixed")

    def __init__(self, records, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels([field_label(name.capitalize()) for name in self.HEADERS])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(150)
        for record in records or ():
            self.add(record)
        self.add({})
        self.itemChanged.connect(self._grow)

    def add(self, record):
        row = self.rowCount()
        self.insertRow(row)
        for column, key in enumerate(self.HEADERS[:4]):
            value = record.get(key)
            self.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
        fixed = QTableWidgetItem()
        fixed.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        fixed.setCheckState(Qt.CheckState.Checked if record.get("fixed") else Qt.CheckState.Unchecked)
        self.setItem(row, 4, fixed)

    def _grow(self, item):
        if item.row() == self.rowCount() - 1 and item.column() == 0 and item.text().strip():
            self.blockSignals(True)
            self.add({})
            self.blockSignals(False)

    def values(self):
        def number(text):
            text = (text or "").strip()
            if not text:
                return None
            try:
                return float(decimal_comma(text))
            except ValueError:
                raise FieldError("Parameters", f"{text} is not a number.") from None

        records = []
        for row in range(self.rowCount()):
            name = (self.item(row, 0).text() if self.item(row, 0) else "").strip()
            if not name:
                continue
            start = number(self.item(row, 1).text() if self.item(row, 1) else "")
            records.append({"name": name, "start": 1.0 if start is None else start,
                            "lower": number(self.item(row, 2).text() if self.item(row, 2) else ""),
                            "upper": number(self.item(row, 3).text() if self.item(row, 3) else ""),
                            "fixed": self.item(row, 4).checkState() == Qt.CheckState.Checked})
        return records


class AnalysisDialog(QDialog):
    def __init__(self, parent, frame, *, current=None, only=None, error=None, error_field=None,
                 join_sources=None, join_left=None, xy_left_scale="linear", graph_type_source=None):
        super().__init__(parent)
        # Join worksheets by key: the other data sheets with their columns, and the title of the left one.
        self.join_sources, self.join_left = join_sources, join_left
        self.join = None
        self.graph_type_source = graph_type_source
        self.setWindowTitle(qt("qt.graph_type_title" if graph_type_source else "qt.analysis_title"))
        self.data = frame
        self.xy_left_scale = xy_left_scale
        self.current = current
        self.only = {only} if isinstance(only, str) else set(only) if only else None
        self.result = None
        self.controls = {}
        self.rows = {}
        self.hidden = set()  # fields the current choices hide: left out of options()
        self.anova = None  # Multifactor ANOVA bindings (trama_qt.anova_model)
        self.stability = None  # K-means stability bindings (trama_qt.kmeans_stability)
        self.repeated = None  # Bland–Altman for repeated pairs (trama_qt.bland_altman_repeated)
        self.sphericity = None  # Repeated measures ANOVA sphericity correction (trama_qt.rm_sphericity_dialog)
        self.icc = None  # Intraclass correlation (trama_qt.icc)
        self.ecdf = None  # Empirical cumulative distribution (trama_qt.ecdf_graph)
        self.interaction = None  # Two-factor interaction plot (trama_qt.interaction_plot)
        self.precision = None  # Precision–recall curve (trama_qt.precision_recall)
        self.raincloud = None  # Raincloud plot (trama_qt.raincloud_plot)
        self.pareto = None  # Pareto plot (trama_qt.pareto_plot)
        self.calibration = None  # Standard-curve calibration (trama_qt.standard_curve)
        self.reshape = None  # Reshape long and wide editor (trama_qt.reshape_long_wide)
        method = current[0] if current and current[0] in METHODS else None
        self.method = method or self._first_method()
        fit_dialog(self, 940, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        picker = QWidget()
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(0, 0, 8, 0)
        find_method = qt("qt.find_graph_type" if graph_type_source else "qt.find_analysis")
        caption = QLabel(find_method)
        caption.setObjectName("sectionTitle")
        picker_layout.addWidget(caption)
        self.query = QLineEdit()
        self.query.setPlaceholderText(find_method)
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(self.fill_methods)
        picker_layout.addWidget(self.query)
        self.methods = QTreeWidget()
        self.methods.setHeaderHidden(True)
        self.methods.setRootIsDecorated(False)
        self.methods.setIndentation(10)
        self.methods.currentItemChanged.connect(self._picked)
        picker_layout.addWidget(self.methods, 1)
        splitter.addWidget(picker)

        workspace = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(8, 0, 0, 0)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        self.heading.setWordWrap(True)
        work_layout.addWidget(self.heading)
        self.banner = QLabel()
        self.banner.setObjectName("errorBanner")
        self.banner.setWordWrap(True)
        self.error_field = error_field
        self.banner.setVisible(bool(error))
        if error:
            self.banner.setText(self._message(error, error_field))
        work_layout.addWidget(self.banner)
        self.tabs = QTabWidget()
        work_layout.addWidget(self.tabs, 1)
        splitter.addWidget(workspace)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 640])

        buttons = QDialogButtonBox()
        run_label = qt("qt.apply_graph_type" if graph_type_source else "qt.run")
        self.run_button = buttons.addButton(run_label, QDialogButtonBox.ButtonRole.AcceptRole)
        self.run_button.setDefault(True)
        buttons.addButton(qt("qt.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.fill_methods()
        self.configure_fields()
        if error and self.stability is not None:  # engine errors reopen here; word them in the active language
            self.banner.setText(self.stability.message(error))
        if error and self.repeated is not None:  # engine errors reopen here; word them in the active language
            self.banner.setText(self.repeated.message(error))
        if error and self.sphericity is not None:  # engine errors reopen here; word them in the active language
            self.banner.setText(self.sphericity.message(error, error_field))
        if error and self.icc is not None:  # engine errors reopen here; word them in the active language
            self.banner.setText(self.icc.message(error))
        if error and self.ecdf is not None:
            self.banner.setText(self.ecdf.message(error))
        if error and self.interaction is not None:
            self.banner.setText(self.interaction.message(error))
        if error and self.precision is not None:
            self.banner.setText(self.precision.message(error))
        if error and self.raincloud is not None:
            self.banner.setText(self.raincloud.message(error))
        if error and self.pareto is not None:
            self.banner.setText(self.pareto.message(error))
        if error and self.calibration is not None:
            self.banner.setText(self.calibration.message(error))
        if error_field:
            if self.anova is not None and error:  # engine errors reopen here; word them in the active language
                self.banner.setText(self.anova.message(FieldError(error_field, str(error))))
            self.focus_field(error_field, error)
        if self.only and len(self.only) == 1:
            splitter.widget(0).setVisible(False)

    # -- method list -----------------------------------------------------------------------------
    def _offered(self, name):
        if self.only and name not in self.only:
            return False
        if name == kmeans_reports.MODEL_GRAPH:
            return name == self.method or kmeans_reports.model_plot_available(self.data)
        return name != HIERARCHY_GRAPH or name == self.method or hierarchy_view_available(self.data)

    def _first_method(self):
        for methods in GROUPS.values():
            for name in methods:
                if name in METHODS and self._offered(name):
                    return name
        return next(iter(METHODS))

    def fill_methods(self):
        search = self.query.text().strip().casefold()
        self.methods.blockSignals(True)
        self.methods.clear()
        selected = None
        for group, methods in GROUPS.items():
            matches = [name for name in methods if name in METHODS and self._offered(name)
                       and any(search in caption.casefold()
                               for caption in (name, group, method_label(name), method_label(group)))]
            if not matches:
                continue
            folder = QTreeWidgetItem([method_label(group)])
            folder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = folder.font(0)
            font.setBold(True)
            folder.setFont(0, font)
            self.methods.addTopLevelItem(folder)
            for name in matches:
                item = QTreeWidgetItem([method_label(name)])
                item.setData(0, Qt.ItemDataRole.UserRole, name)
                folder.addChild(item)
                if name == self.method:
                    selected = item
            folder.setExpanded(True)
        if selected is not None:
            self.methods.setCurrentItem(selected)
            self.methods.scrollToItem(selected)
        self.methods.blockSignals(False)

    def _picked(self, item, _previous=None):
        name = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if name in METHODS and name != self.method:
            self.method = name
            self.banner.setVisible(False)
            self.error_field = None
            self.configure_fields()

    # -- fields ----------------------------------------------------------------------------------
    def _saved(self):
        if not self.current or self.current[0] != self.method:
            if self.graph_type_source is None:
                return {}
            source_method, options = self.graph_type_source
            source_fields = METHODS[source_method]
            return {field: options[field] for field, kind in METHODS[self.method].items()
                    if kind in VARIABLE_KINDS and field in options and field in source_fields
                    and source_fields[field] == kind}
        saved = dict(self.current[1])
        if self.method in kmeans_options.METHODS:
            saved = kmeans_options.saved_scaling(saved)
        if self.method == "Hierarchical clustering":
            saved = saved_hierarchical_options(saved)
        if self.method in CLASSIC_RESPONSES:
            saved = {**saved, **classic_roles(self.method, saved)}
        return saved

    def configure_fields(self):
        self.heading.setText(method_label(self.method))
        self.tabs.clear()
        self.controls.clear()
        self.rows.clear()
        self.hidden.clear()
        self.anova = None
        self.stability = None
        self.repeated = None
        self.sphericity = None
        self.icc = None
        self.ecdf = None
        self.interaction = None
        self.precision = None
        self.raincloud = None
        self.pareto = None
        self.calibration = None
        self.reshape = None
        self.join = None
        pages, scrolls = {}, {}
        power_method = self.method == power_plan.METHOD
        paired_power = self.method == mcnemar_power.METHOD
        cox_method = self.method == cox_outputs.METHOD
        weibull_method = self.method == weibull.METHOD
        ordinal_method = self.method == ordinal.ORDINAL_LOGIT
        rmst_method = self.method == rmst.METHOD
        kappa_method = self.method == kappa.METHOD
        permutation_method = self.method == mean_permutation.METHOD
        yuen_method = self.method == yuen.METHOD
        brunner_method = self.method == brunner_munzel.METHOD
        mood_method = self.method == mood_median.METHOD
        page_specs = (("variables", ui("Design")), ("options", ui("Effect")), ("curve", ui("Curve"))) if (
            power_method or paired_power) else (
            ("variables", qt("qt.variables")), *global_fit.pages(self.method),
            *global_catalog.pages(self.method), *select_editor.pages(self.method),
            ("options", qt("qt.options")))
        survival_method = self.method == "Kaplan–Meier survival"
        lognormal_method = self.method == lognormal_tests.LOGNORMAL
        if survival_method:
            page_specs += (("survival-pairs", ui("Pairwise tests")),)
        hierarchy_method = self.method == "Hierarchical clustering"
        if hierarchy_method:
            page_specs += tuple((name, ui(name)) for name in HIERARCHICAL_TABS)
        if self.method in regression_range.METHODS:
            page_specs += (("range", ui(regression_range.TAB_TITLE)),)
        cox_fields = (cox_outputs.DIAGNOSTICS, cox_outputs.SCHOENFELD, *cox_outputs.FIT_DIAGNOSTICS,
                      cox_outputs.GRAPH, cox_outputs.GRAPH_TERM, cox_outputs.X_AXIS)
        if cox_method:
            page_specs += (("diagnostics", ui("Diagnostics")),)
        if weibull_method:
            page_specs = tuple((key, tr(weibull_form.TAB_KEYS[name])) for key, name in (
                ("variables", "Data"), ("options", "Model"), ("predicted", "Predicted survival")))
        if ordinal_method:
            page_specs += (("profiles", tr("ord.tab.profiles")),)
        if rmst_method:
            page_specs = (("variables", tr(rmst_form.TAB_KEYS["Data"])),
                          ("options", tr(rmst_form.TAB_KEYS["Options"])))
        if kappa_method:
            page_specs = (("variables", tr(kappa_form.TAB_KEYS["Ratings"])),
                          ("options", tr(kappa_form.TAB_KEYS["Interval and graph"])))
        if permutation_method:
            page_specs = (("variables", tr(mean_permutation.TAB_KEYS["Data"])),
                          ("options", tr(mean_permutation.TAB_KEYS["Test"])))
        if yuen_method:
            page_specs = (("variables", tr(yuen.TAB_KEYS["Data"])),
                          ("options", tr(yuen.TAB_KEYS["Test"])))
        if brunner_method:
            page_specs = (("variables", tr(brunner_munzel.TAB_KEYS["Data"])),
                          ("options", tr(brunner_munzel.TAB_KEYS["Test"])))
        if mood_method:
            page_specs = (("variables", tr(mood_median.TAB_KEYS["Data"])),
                          ("options", tr(mood_median.TAB_KEYS["Test"])))
        for key, name in page_specs:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            body = QWidget()
            form = QFormLayout(body)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setContentsMargins(12, 12, 12, 12)
            form.setVerticalSpacing(8)
            scroll.setWidget(body)
            pages[key], scrolls[key] = form, scroll
            self.tabs.addTab(scroll, name)
        variables, options = pages["variables"], pages["options"]
        saved = self._saved()
        if survival_method:
            saved = {**saved, PAIRWISE_SCOPE: pairwise_scope(saved)}
        if kappa_method:
            saved = {**kappa_text.defaults(self.data), **saved}
        paired_method = self.method == paired.PAIRED_PROPORTIONS
        tolerance_method = self.method == tolerance.TOLERANCE
        if paired_method:
            saved = {**paired.DEFAULT_CODES, **paired.defaults(self.data), **saved}
            self.tabs.setTabText(self.tabs.indexOf(scrolls["variables"]), tr("paired.tab.data"))
            self.tabs.setTabText(self.tabs.indexOf(scrolls["options"]), tr("paired.tab.test"))
        if tolerance_method:
            self.tabs.setTabText(self.tabs.indexOf(scrolls["variables"]), tr(tolerance.TAB_KEYS["Data"]))
            self.tabs.setTabText(self.tabs.indexOf(scrolls["options"]), tr(tolerance.TAB_KEYS["Interval"]))
        labels = paired.LABEL_KEYS if paired_method else tolerance.LABEL_KEYS if tolerance_method else {}
        captions = paired.CHOICE_KEYS if paired_method else tolerance.CHOICE_KEYS if tolerance_method else {}
        if weibull_method:
            labels, captions = weibull_form.LABEL_KEYS, weibull_form.CHOICE_KEYS
        if rmst_method:
            labels = rmst_form.LABEL_KEYS
        if kappa_method:
            labels, captions = kappa_form.LABEL_KEYS, kappa_form.CHOICE_KEYS
        if permutation_method:
            labels, captions = mean_permutation.LABEL_KEYS, mean_permutation.CHOICE_KEYS
        if yuen_method:
            labels, captions = yuen.LABEL_KEYS, yuen.CHOICE_KEYS
        if brunner_method:
            labels, captions = brunner_munzel.LABEL_KEYS, brunner_munzel.CHOICE_KEYS
        if mood_method:
            labels, captions = mood_median.LABEL_KEYS, mood_median.CHOICE_KEYS
        if self.method == "t-test":
            labels, captions = ttest_options.LABEL_KEYS, ttest_options.CHOICE_KEYS
        if lognormal_method:
            labels, captions = lognormal_tests.LABEL_KEYS, lognormal_tests.CHOICE_KEYS
            for page, title in (("variables", "Data"), ("options", "Test and graph")):
                self.tabs.setTabText(self.tabs.indexOf(scrolls[page]), tr(lognormal_tests.TAB_KEYS[title]))
        if self.method == interaction_binding.METHOD:
            captions = interaction_plot_catalog.CHOICE_KEYS
            if interaction_binding.ERROR_BARS not in saved:
                saved = {**saved, interaction_binding.ERROR_BARS: interaction_binding.DEFAULT_ERROR_BARS}
        if self.method == raincloud_binding.METHOD:
            captions = raincloud_plot_catalog.CHOICE_KEYS
        if self.method == CUSTOM_EQUATION and not saved:
            saved = {"Equation": DEFAULT_EQUATION, "Parameters": [dict(record) for record in EXAMPLE_PARAMETERS]}
        elif self.method == global_fit.GLOBAL_CUSTOM_EQUATION and not saved:
            saved = global_fit.default_recipe()
        elif self.method == cluster_silhouette.METHOD and not saved:
            saved = cluster_silhouette.default_options(self.data)
        elif self.method == plot_function.PLOT_FUNCTION and not saved:
            saved = {plot_function.CURVES: plot_function.EXAMPLE_CURVES[:1]}
        elif self.method == transpose_xy.TRANSPOSE_XY and not saved:
            x = transpose_xy.proposed_x(self.data) or next(iter(self.data.select_dtypes(include="number").columns), None)
            saved = {transpose_xy.X: x, transpose_xy.Y_SETS: transpose_xy.propose_sets(self.data, x)}
        text_defaults = _text_defaults(self.method)
        if weibull_method:
            text_defaults = weibull_form.DEFAULTS
        if rmst_method:
            text_defaults = rmst_form.DEFAULTS
        power_forms = {}
        if power_method:
            text_defaults = power_plan.TEXT_DEFAULTS
            for name, form in (("Design", variables), ("Effect", options), ("Curve", pages["curve"])):
                power_forms.update(dict.fromkeys(power_plan.TABS[name], form))
        if paired_power:
            for name, form in (("Design", variables), ("Effect", options), ("Curve", pages["curve"])):
                power_forms.update(dict.fromkeys(mcnemar_power.TABS[name], form))
        hierarchy_forms = {field: pages[tab] for tab, names in HIERARCHICAL_TABS.items()
                           for field in names} if hierarchy_method else {}
        columns = [str(name) for name in self.data.columns]
        numeric = [str(name) for name in self.data.select_dtypes(include="number").columns]
        categorical = [name for name in columns if name not in numeric] or columns
        numeric_position = category_position = 0
        fields = {} if self.method in {reshape_editor.METHOD, SELECT_TRANSFORM, join_editor.wj.METHOD} else METHODS[self.method]
        for label, kind in fields.items():
            if kind == CONTRAST_FACTOR_LIST or (kind != CONTRAST_LIST and label in PLANNED_PANEL_FIELDS
                                                and CONTRAST_LIST in METHODS[self.method].values()):
                continue  # the Planned contrasts… editor holds these fields
            variable = (kind in VARIABLE_KINDS or label == "Input format") and label not in {
                "Comparison factor", "Condition on factors"}
            if self.method == extraction.EXTRACT_REARRANGE and label == extraction.OUTPUT:
                variable = True
            if self.method == precision_options.METHOD and label in precision_options.CODE_FIELDS:
                variable = True  # the labels of the outcome sit beside the Outcome column
            if paired_method:
                variable = label in paired.DATA_FIELDS
            if rmst_method:
                variable = label in rmst_form.DATA_FIELDS
            if kappa_method:
                variable = label in kappa_form.RATING_FIELDS
            if permutation_method:
                variable = label in mean_permutation.DATA_FIELDS
            if yuen_method:
                variable = label in yuen.DATA_FIELDS
            if brunner_method:
                variable = label in brunner_munzel.DATA_FIELDS
            if mood_method:
                variable = label in mood_median.DATA_FIELDS
            if self.method == "t-test" and label in ("Design", ttest_options.INPUT):
                variable = True
            if self.method == ecdf_binding.METHOD and label == ecdf_binding.INPUT:
                variable = True
            form = (power_forms.get(label) or pages.get(global_fit.page_of(self.method, label))
                    or (variables if variable else options))
            if label in hierarchy_forms:
                form = hierarchy_forms[label]
            if lognormal_method:
                form = variables if label in lognormal_tests.DATA_FIELDS else options
            if survival_method and label in PAIRWISE_FIELDS:
                form = pages["survival-pairs"]
            if self.method in regression_range.METHODS and label in (*regression_range.FIELDS, regression_range.SHOW_OUTSIDE):
                form = pages["range"]
            if self.method == transpose_xy.TRANSPOSE_XY and label == transpose_xy.Y_SETS:
                form = variables
            if cox_method and label in cox_fields:
                form = pages["diagnostics"]
            if weibull_method:
                form = (variables if label in weibull_form.DATA_FIELDS else pages["predicted"]
                        if label in weibull_form.PREDICT_FIELDS else options)
            if ordinal_method:
                if label == ordinal.ORDER:
                    form = variables
                elif label in ordinal.PROFILE_FIELDS:
                    form = pages["profiles"]
            caption_label = ("Report scaled observations"
                             if self.method in kmeans_options.METHODS and label == kmeans_reports.SCALED else label)
            caption = QLabel(tr(labels[label]) if label in labels else field_label(caption_label))
            caption.setWordWrap(True)
            caption.setMinimumWidth(150)
            caption.setMaximumWidth(230)
            widget = None
            if kind in (MULTIPLE, OPTIONAL_MULTIPLE):
                widget = QListWidget()
                widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                default_columns = numeric if label in {"Variables", "Count columns"} and not tolerance_method else ()
                defaults = saved.get(label, default_columns)
                selected = [str(name) for name in (defaults or ())]
                offered = list(dict.fromkeys([*selected, *columns])) if label in saved else columns
                checked = set(selected)
                for name in offered:
                    item = QListWidgetItem(name)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if name in checked
                                       else Qt.CheckState.Unchecked)
                    widget.addItem(item)
                widget.setMaximumHeight(max(70, min(170, 24 * len(offered) + 8)))
            elif type(kind) is bool:
                widget = QCheckBox()
                widget.setChecked(bool(saved.get(label, kind)))
            elif power_method and label == power_plan.GROUP_MEANS:
                widget = QPlainTextEdit(str(saved.get(label, text_defaults[label])))
                widget.setTabChangesFocus(True)
                widget.setFixedHeight(7 * widget.fontMetrics().lineSpacing())
            elif cox_method and label == cox_outputs.GRAPH_TERM:
                widget = QComboBox()
            elif ((weibull_method and label == weibull.PROFILES)
                  or (ordinal_method and label == ordinal.PROFILES)):
                limit = ordinal.MAX_PROFILES if ordinal_method else weibull.MAX_PROFILES
                widget = Profiles(self.data, saved.get(label), limit=limit)
            elif ordinal_method and label == ordinal.ORDER:
                widget = ordinal_options.OrderEditor(saved.get(label))
            elif weibull_method and label == weibull.TIMES:
                widget = weibull_options.Times(saved.get(label))
            elif kappa_method and label == kappa.ORDER:
                widget = kappa_options.CategoryOrder(saved.get(label))
            elif rmst_method and label == rmst.REFERENCE:
                widget = QComboBox()
                reference = saved.get(label)
                if reference is not None and reference != "":
                    text = rmst.group_text(reference)
                    widget.addItem(text, text)
            elif paired_power and type(kind) in (int, float):
                value = saved.get(label, kind)
                text = mcnemar_power.canonical(value) if type(value) in (int, float) else "" if value is None else str(value)
                widget = QLineEdit(text)
            elif type(kind) in (int, float) or kind == TEXT:
                default = text_defaults.get(label, "") if kind == TEXT else kind
                value = saved.get(label, default)
                text = "" if value is None else str(value)
                if rmst_method and label in rmst_form.NUMBER_FIELDS and type(value) in (int, float):
                    text = rmst_dialog.shown_number(value)
                if yuen_method and label in yuen.NUMBER_FIELDS and type(value) in (int, float) and not isinstance(value, bool):
                    text = yuen.shown_number(value)
                if (brunner_method and label in brunner_munzel.NUMBER_FIELDS
                        and type(value) in (int, float) and not isinstance(value, bool)):
                    text = brunner_munzel.shown_number(value)
                widget = QLineEdit(text)
            elif kind == plot_function.CURVE_LIST:
                model = self.controls[plot_function.MODEL][1]
                widget = FunctionCurves(model.currentData(), saved.get(label, ()))
                model.currentIndexChanged.connect(lambda _index, editor=widget: editor.set_model(model.currentData()))
            elif kind == transpose_xy.SETS_LIST:
                widget = TransposeSets(self.data, self.controls[transpose_xy.X][1], saved.get(label, ()))
            elif kind == TERM_LIST:  # Multifactor ANOVA model terms; bound below by anova_model.attach
                widget = anova_model.TermEditor(saved.get(label))
            elif kind == CONTRAST_LIST:  # Multifactor ANOVA planned contrasts; bound by anova_model.attach
                widget = planned_contrasts.ContrastPanel(saved)
            elif kind == EQUATION_TEXT:
                widget = QPlainTextEdit(str(saved.get(label, DEFAULT_EQUATION)))
                widget.setMinimumHeight(90)
            elif kind == PAIRWISE_PAIR_LIST:
                widget = survival_pairs.PairEditor(saved.get(label, ()))
            elif kind == PARAMETER_LIST:
                widget = ParameterTable(saved.get(label, ()))
            elif kind in (global_fit.PARAMETER_LIST, global_fit.SERIES_LIST):
                # Global coefficient list / Global series constraints (Global fit custom equation).
                widget = global_fit.build_editor(kind, label, saved, self)
            elif isinstance(kind, tuple) or kind in (None, OPTIONAL, GROUP_CHOICE):
                widget = QComboBox()
                widget.setMinimumContentsLength(18)
                if isinstance(kind, tuple):
                    choices = (pairwise_corrections(saved) if survival_method and label == PAIRWISE_CORRECTION
                               else list(kind))
                    for choice in choices:
                        choice_caption = str(choice)
                        if self.method == kmeans_options.SELECTION and label == "Criterion" and choice == "Gap":
                            choice_caption = "Gap statistic"
                        text = tr(captions[choice]) if choice in captions else choice_label(choice_caption)
                        widget.addItem(text, choice)
                    default = choices[0] if choices else ""
                elif kind == GROUP_CHOICE:
                    widget.setEditable(not lognormal_method)
                    widget.addItem("", "")
                    default = ""
                else:
                    if kind == OPTIONAL:
                        widget.addItem(qt("qt.none"), "")
                    for name in columns:
                        widget.addItem(name, name)
                    if kind is None and (label in CATEGORY_ROLES or
                                         (ordinal_method and label == ordinal.RESPONSE)) and categorical:
                        default = categorical[category_position % len(categorical)]
                        category_position += 1
                    elif self.method in ("t-test", yuen.METHOD) and label in (ttest_options.FIRST, ttest_options.SECOND) and numeric:
                        default = numeric[min(int(label == ttest_options.SECOND), len(numeric) - 1)]
                    elif kind is None and numeric:
                        default = numeric[numeric_position % len(numeric)]
                        numeric_position += 1
                    else:
                        default = "" if kind == OPTIONAL else (columns[0] if columns else "")
                value = saved.get(label) or default
                position = widget.findData(value)
                if position < 0 and value not in (None, ""):
                    widget.addItem(str(value), value)
                    position = widget.count() - 1
                widget.setCurrentIndex(max(position, 0))
                if kind == GROUP_CHOICE and value and widget.isEditable():
                    widget.setEditText(str(value))
            if widget is None:
                # A compound editor of the classic dialog: keep the saved value or the default.
                note = QLabel(qt("qt.saved_setting") if label in saved else qt("qt.default_setting"))
                note.setObjectName("muted")
                note.setWordWrap(True)
                form.addRow(caption, note)
                if label in saved:
                    self.controls[label] = ("kept", deepcopy(saved[label]))
                continue
            full_width = (kind in (TERM_LIST, CONTRAST_LIST, global_fit.PARAMETER_LIST, global_fit.SERIES_LIST)
                          or isinstance(widget, (Profiles, ordinal_options.OrderEditor, kappa_options.CategoryOrder,
                                                 FunctionCurves, TransposeSets)))
            if full_width:
                form.addRow(caption)
                form.addRow(widget)
            else:
                form.addRow(caption, widget)
            self.controls[label] = (kind, widget)
            self.rows[label] = (caption, widget, form)
        variable_lists = [(self.rows[label][0], widget) for label, (kind, widget) in self.controls.items()
                          if kind in (MULTIPLE, OPTIONAL_MULTIPLE) and self.rows[label][2] is variables]
        if any(widget.count() > 8 for _, widget in variable_lists):
            self._add_column_search(variables, variable_lists)
        if hierarchy_method:
            plot = self.controls["Graph output"][1]
            report_gap = self.controls[GAP_DATA][1]

            def sync_gap():
                graph_gap = plot.currentData() == GAP_PLOT
                self._set_field_visibility({
                    GAP_DATA: not graph_gap,
                    **dict.fromkeys(GAP_OPTIONS, graph_gap or report_gap.isChecked()),
                })

            plot.currentIndexChanged.connect(sync_gap)
            report_gap.toggled.connect(sync_gap)
            sync_gap()
        if survival_method:
            survival_pairs.attach(self)
        if self.method == "Descriptive statistics":
            report = self.controls[SUMMARY_FORMAT][1]
            report.currentIndexChanged.connect(lambda _: self._set_field_visibility(summary_fields(report.currentData())))
            self._set_field_visibility(summary_fields(report.currentData()))
        if self.method == curve_pipeline.CURVE_METHOD:
            self._configure_curve_fields(options)
        if self.method == plot_function.PLOT_FUNCTION:
            source = self.controls[plot_function.X_SOURCE][1]
            source.currentIndexChanged.connect(lambda _: self._set_field_visibility(
                plot_function.visibility(source.currentData())))
            self._set_field_visibility(plot_function.visibility(source.currentData()))
        if self.method == monte_carlo.MONTE_CARLO:
            study = self.controls[monte_carlo.STUDY][1]
            source = self.controls[monte_carlo.X_SOURCE][1]

            def sync_study():
                self._set_field_visibility(monte_carlo.visibility(study.currentData(), source.currentData()))

            study.currentIndexChanged.connect(sync_study)
            source.currentIndexChanged.connect(sync_study)
            sync_study()
        if self.method == ellipse_groups.METHOD:
            self.ellipse_groups = ellipse_groups.GroupEditor(self, saved)
            key = ellipse_groups.GROUP_STYLES
            caption = QLabel(ui(key))
            options.addRow(caption, self.ellipse_groups)
            self.rows[key] = (caption, self.ellipse_groups, options)
            for name in ellipse_groups.CHOICES:
                self.controls[name][1].currentIndexChanged.connect(self.ellipse_groups.sync)
            self.ellipse_groups.sync()
        self.anova = anova_model.attach(self, saved)
        global_fit.attach(self)
        global_catalog.attach(self, pages, saved)
        if self.method == "t-test":
            design = self.controls["Design"][1]
            layout = self.controls[ttest_options.INPUT][1]

            def show_ttest_fields():
                mode = design.currentData()
                self._set_field_visibility({**ttest_options.visibility(mode, layout.currentData()),
                                            TTEST_ESTIMATION: mode == "Paired",
                                            TTEST_VARIANCE: mode in ("Welch", "Student")})

            design.currentIndexChanged.connect(show_ttest_fields)
            layout.currentIndexChanged.connect(show_ttest_fields)
            show_ttest_fields()
        if yuen_method:
            note = QLabel(tr("yuen.note"))
            note.setWordWrap(True)
            options.addRow(note)
            sample_format = self.controls[yuen.INPUT][1]

            def show_yuen_fields():
                self._set_field_visibility(yuen.visibility(sample_format.currentData()))
                if self.error_field in self.hidden:
                    self.clear_field_error(self.error_field)

            sample_format.currentIndexChanged.connect(show_yuen_fields)
            show_yuen_fields()
        if brunner_method:
            note = QLabel(tr("bm.note"))
            note.setWordWrap(True)
            options.addRow(note)
        if lognormal_method:
            for name in (lognormal_tests.DESIGN, lognormal_tests.INPUT, *lognormal_tests.GROUP_FIELDS):
                self.controls[name][1].currentIndexChanged.connect(self._show_lognormal_fields)
            self._show_lognormal_fields()
        if mood_method:
            note = QLabel(tr("mood.note"))
            note.setWordWrap(True)
            options.addRow(note)
            variables_box = self.controls[mood_median.VARIABLES][1]
            yates_box = self.controls[mood_median.YATES][1]

            def sync_yates():
                checked = sum(
                    1 for index in range(variables_box.count())
                    if variables_box.item(index).checkState() == Qt.CheckState.Checked
                )
                yates_box.setEnabled(checked == 2)
                if checked != 2:
                    yates_box.setChecked(False)

            variables_box.itemChanged.connect(lambda _item: sync_yates())
            sync_yates()
        if self.method == "Nonlinear regression":
            model = self.controls["Model"][1]

            def show_log_ic50():
                self._set_field_visibility({REPORT_LOG_IC50: has_ic50(model.currentData())})

            model.currentIndexChanged.connect(show_log_ic50)
            show_log_ic50()
        if self.method in kmeans_options.METHODS:
            algorithm = self.controls[kmeans_options.ALGORITHM][1]
            algorithm.currentIndexChanged.connect(self._sync_kmeans_options)
            self.controls[kmeans_options.SCALE][1].currentIndexChanged.connect(self._sync_kmeans_options)
            self._sync_kmeans_options()
        self.stability = stability_options.attach(self)
        self.repeated = repeated_agreement.attach(self)
        self.sphericity = sphericity_options.attach(self)
        self.icc = icc_binding.attach(self, saved)
        self.ecdf = ecdf_binding.attach(self, saved)
        self.interaction = interaction_binding.attach(self, saved)
        self.precision = precision_options.attach(self)
        self.raincloud = raincloud_binding.attach(self, saved)
        self.pareto = pareto_binding.attach(self, saved)
        self.calibration = calibration_options.attach(self)
        self.reshape = reshape_editor.attach(self, pages, saved)
        select_editor.attach(self, pages, saved)
        if self.method == extraction.EXTRACT_REARRANGE:
            output = self.controls[extraction.OUTPUT][1]
            output.currentIndexChanged.connect(self._sync_extraction_fields)
            for name, (kind, widget) in self.controls.items():
                changed = widget.toggled if type(kind) is bool else widget.currentIndexChanged
                changed.connect(lambda _value, field=name: self.clear_field_error(field))
            self._sync_extraction_fields()
        self.join = join_editor.attach(self, pages, saved)
        if power_method:
            self._configure_power_fields(pages)
        if paired_power:
            self._configure_paired_power(pages)
        if cox_method:
            self._configure_cox_fields(pages["diagnostics"], saved.get(cox_outputs.GRAPH_TERM))
        if weibull_method:
            weibull_options.attach(self, pages)
        if ordinal_method:
            ordinal_options.attach(self, pages["profiles"])
        if rmst_method:
            rmst_options.attach(self, pages)
        if kappa_method:
            kappa_options.attach(self, pages)
        if permutation_method:
            permutation_options.attach(self, pages)
        if paired_method:
            note = QLabel()
            note.setWordWrap(True)
            variables.addRow(note)

            def sync_format():
                input_format = self.controls[paired.FORMAT][1].currentData()
                self._set_field_visibility(paired.visibility(input_format))
                note.setText(tr("paired.note.matrix" if input_format == paired.COUNT_MATRIX
                                else "paired.note.observations"))
                if self.error_field in self.hidden:
                    self.clear_field_error(self.error_field)

            self.controls[paired.FORMAT][1].currentIndexChanged.connect(sync_format)
            sync_format()
        if self.method == cluster_silhouette.METHOD:
            note = QLabel(tr("silhouette.note"))
            note.setWordWrap(True)
            options.addRow(note)
        if tolerance_method:
            note = QLabel(tr(tolerance.HINT_KEY))
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            options.addRow(note)
        if options.rowCount() == 0:
            self.tabs.removeTab(self.tabs.indexOf(scrolls["options"]))

    def _add_column_search(self, form, lists):
        search = QLineEdit()
        search.setObjectName("analysisColumnSearch")
        search.setPlaceholderText(qt("qt.find_columns"))
        search.setAccessibleName(qt("qt.find_columns"))
        search.setClearButtonEnabled(True)
        form.insertRow(0, search)
        outside = QLabel()
        outside.setObjectName("muted")
        outside.setTextFormat(Qt.TextFormat.PlainText)
        outside.setWordWrap(True)
        outside.hide()
        form.insertRow(1, outside)
        limits = {widget: widget.maximumHeight() for _, widget in lists}

        def folded(text):
            return "".join(char for char in normalize("NFKD", text.casefold()) if not combining(char))

        def filter_columns(query):
            needle = folded(query.strip())
            kept = []
            for caption, widget in lists:
                visible = checked_outside = 0
                for index in range(widget.count()):
                    item = widget.item(index)
                    matches = needle in folded(item.text())
                    item.setHidden(not matches)
                    if matches:
                        visible += 1
                    elif item.checkState() == Qt.CheckState.Checked:
                        checked_outside += 1
                widget.setMaximumHeight(min(limits[widget], max(70, 24 * visible + 8)))
                if checked_outside:
                    kept.append(f"{caption.text()} ({checked_outside})")
            outside.setText(qt("qt.filtered_selection", fields=" · ".join(kept)) if kept else "")
            outside.setVisible(bool(kept))

        def focus_first_match():
            for _, widget in lists:
                if widget.isVisible():
                    for index in range(widget.count()):
                        if not widget.item(index).isHidden():
                            widget.setCurrentRow(index)
                            widget.setFocus()
                            return

        search.textChanged.connect(filter_columns)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QShortcut(QKeySequence(key), search, focus_first_match, Qt.ShortcutContext.WidgetShortcut)

    def _sync_kmeans_options(self):
        algorithm = self.controls[kmeans_options.ALGORITHM][1].currentData()
        fields = {field: key == algorithm for key, field in kmeans_options.ITERATION_FIELDS.items()}
        fields[kmeans_options.INITIALIZATION] = algorithm == kmeans_options.HARTIGAN
        scale = self.controls[kmeans_options.SCALE][1].currentData()
        fields[kmeans_reports.SCALED] = scale != kmeans_options.UNSCALED
        if self.method == kmeans_options.CLUSTERING:
            fields[kmeans_options.INITIAL_ROWS] = algorithm in kmeans_options.ITERATION_FIELDS
        self._set_field_visibility(fields)

    def _configure_curve_fields(self, form):
        notes = []
        for key in curve_pipeline_dialog.NOTE_KEYS:
            note = QLabel(tr(key))
            note.setWordWrap(True)
            note.setObjectName("muted")
            form.addRow(note)
            notes.append(note)

        choices = [self.controls[name][1] for name in ("Method", curve_pipeline.OPERATION, curve_pipeline.SMOOTHING)]

        def sync():
            method, operation, smoothing = (choice.currentData() for choice in choices)
            self._set_field_visibility(curve_pipeline.visibility(method, operation, smoothing))
            visible = curve_pipeline_dialog.notes_visibility(method, smoothing, curve_pipeline.PIPELINE,
                                                            curve_pipeline.SAVITZKY_GOLAY)
            for note, shown in zip(notes, visible):
                form.setRowVisible(note, shown)
            if self.error_field in self.hidden:
                self.clear_field_error(self.error_field)

        for choice in choices:
            choice.currentIndexChanged.connect(sync)
        sync()

    def _configure_power_fields(self, pages):
        notes = {}
        for page, key in (("variables", "design"), ("options", "effect"), ("curve", "curve")):
            note = QLabel(tr(f"power.note.{key}"))
            note.setWordWrap(True)
            pages[page].addRow(note)
            notes[key] = note

        choices = (power_plan.GOAL, power_plan.DESIGN, power_plan.EFFECT_INPUT, power_plan.PAIRED_SD_INPUT)

        def sync():
            current = {name: self.controls[name][1].currentData() for name in choices}
            self._set_field_visibility(power_plan.visibility(current))
            pages["variables"].setRowVisible(notes["design"], current[power_plan.DESIGN] == "Independent t")
            pages["options"].setRowVisible(notes["effect"], current[power_plan.EFFECT_INPUT] == power_plan.MEANS)
            if self.error_field in self.hidden:
                self.clear_field_error(self.error_field)

        for name in choices:
            self.controls[name][1].currentIndexChanged.connect(sync)
        sync()

    def _configure_paired_power(self, pages):
        notes = []
        for page, key in (("variables", "design"), ("options", "effect_empty"), ("curve", "curve")):
            note = QLabel(tr(f"mcnemar.power.note.{key}"))
            note.setWordWrap(True)
            note.setObjectName("muted")
            pages[page].addRow(note)
            notes.append(note)
        effect = notes[1]
        goal = self.controls[mcnemar_power.GOAL][1]
        first = self.controls[mcnemar_power.P01][1]
        second = self.controls[mcnemar_power.P10][1]

        def show(value):
            text = f"{value:.6g}"
            return text.replace(".", ",") if active_language() == "it" else text

        def sync(_value=None):
            self._set_field_visibility(mcnemar_power.visibility({mcnemar_power.GOAL: goal.currentData()}))
            preview = mcnemar_power.effect_preview(first.text(), second.text())
            if preview is None:
                effect.setText(tr("mcnemar.power.note.effect_empty"))
            else:
                difference, discordance = preview
                effect.setText(tr("mcnemar.power.note.effect", difference=show(difference),
                                  discordance=show(discordance)))
            if self.error_field in self.hidden:
                self.clear_field_error(self.error_field)

        goal.currentIndexChanged.connect(sync)
        first.textChanged.connect(sync)
        second.textChanged.connect(sync)
        sync()

    def _configure_cox_fields(self, form, saved_term):
        cox = cox_outputs
        graph = self.controls[cox.GRAPH][1]
        term = self.controls[cox.GRAPH_TERM][1]
        predictors = self.controls["Predictors"][1]
        categories = self.controls["Categorical predictors"][1]
        ties = self.controls[cox_exact.TIES][1]
        note = QLabel(tr("cox.exact.unavailable"))
        note.setWordWrap(True)
        form.addRow(note)

        def picked(box):
            return [box.item(i).text() for i in range(box.count())
                    if box.item(i).checkState() == Qt.CheckState.Checked]

        def update_terms(selected):
            terms = cox.model_terms(self.data, picked(predictors), picked(categories))
            if selected and selected not in terms:
                terms.append(selected)
            term.clear()
            for name in terms:
                term.addItem(name, name)
            term.setCurrentIndex(max(0, term.findData(selected)))

        def sync():
            checks = [self.controls[name][1].isChecked() for name in cox.OUTPUT_FIELDS]
            fields = cox.cox_visibility(checks[0], graph.currentData(), *checks[1:])
            self._set_field_visibility({name: fields[name] for name in (cox.GRAPH_TERM, cox.X_AXIS)})
            form.setRowVisible(note, ties.currentData() == cox_exact.EXACT)
            if self.error_field in self.hidden:
                self.clear_field_error(self.error_field)

        for box in (predictors, categories):
            box.itemChanged.connect(lambda _item: update_terms(term.currentData()))
        for name in cox.OUTPUT_FIELDS:
            self.controls[name][1].toggled.connect(sync)
        graph.currentIndexChanged.connect(sync)
        ties.currentIndexChanged.connect(sync)
        update_terms(saved_term)
        sync()

    def _sync_extraction_fields(self):
        output = self.controls[extraction.OUTPUT][1].currentData()
        active = extraction.EXTRACT_FIELDS.get(output, ())
        fields = {field: field in active for choices in extraction.EXTRACT_FIELDS.values() for field in choices}
        fields[extraction.COMPLETE] = output in extraction.EXTRACT_FIELDS and output != "Contingency"
        self._set_field_visibility(fields)
        if self.error_field in self.hidden:
            self.clear_field_error(self.error_field)

    def _show_lognormal_fields(self):
        names = (lognormal_tests.DESIGN, lognormal_tests.INPUT, *lognormal_tests.GROUP_FIELDS)
        options = {name: self.controls[name][1].currentData() for name in names}
        visibility = lognormal_tests.visibility(options[lognormal_tests.DESIGN], options[lognormal_tests.INPUT])
        self._set_field_visibility(visibility)
        if visibility[lognormal_tests.FIRST_GROUP]:
            control = self.controls[lognormal_tests.FIRST_GROUP][1]
            selected = control.currentText()
            labels = list(lognormal_tests.group_choices(self.data, options))
            if selected and selected not in labels:
                labels.append(selected)
            control.clear()
            control.addItems(labels)
            if selected:
                control.setCurrentText(selected)

    def _set_field_visibility(self, fields):
        for name, visible in fields.items():
            _, control, form = self.rows[name]
            form.setRowVisible(control, visible)
            if visible:
                self.hidden.discard(name)
            else:
                self.hidden.add(name)

    def focus_field(self, name, error=None):
        if self.reshape is not None:
            return self.reshape.focus(name, error)
        if self.join is not None:
            return self.join.focus(name, error)
        row = self.rows.get(name)
        if row is None:
            return False
        caption, widget, form = row
        for index in range(self.tabs.count()):
            scroll = self.tabs.widget(index)
            if scroll.widget().layout() is form:
                self.tabs.setCurrentIndex(index)
                scroll.ensureWidgetVisible(widget)
                break
        # A compound editor puts the cursor on the cell the error is about.
        if not (hasattr(widget, "focus_problem") and widget.focus_problem(error)):
            widget.setFocus()
        return True

    # -- values ----------------------------------------------------------------------------------
    def options(self):
        if self.reshape is not None:
            return self.reshape.options()
        if self.join is not None:
            return self.join.options()
        options = {}
        for name, (kind, control) in self.controls.items():
            if self.method == kappa.METHOD and name in kappa_form.TYPED_FIELDS:
                options[name] = kappa_text.read_typed(control.text())
                continue
            if name in self.hidden:
                continue
            if name in (REPORT_LOG_IC50, TTEST_ESTIMATION) and not control.isChecked():
                continue
            if self.method == "Nonlinear regression" and name == MERGE_REPLICATES and not control.isChecked():
                continue
            if kind == "kept":
                options[name] = deepcopy(control)
            elif kind in (MULTIPLE, OPTIONAL_MULTIPLE):
                value = [control.item(i).text() for i in range(control.count())
                         if control.item(i).checkState() == Qt.CheckState.Checked]
                if kind == MULTIPLE and not value:
                    raise FieldError(name, qt("qt.select_columns", name=field_label(name)))
                options[name] = value
            elif type(kind) is bool:
                options[name] = control.isChecked()
            elif self.method == power_plan.METHOD and name in power_plan.NUMBER_FIELDS:
                options[name] = control.toPlainText() if name == power_plan.GROUP_MEANS else control.text()
            elif self.method == mcnemar_power.METHOD and name in mcnemar_power.NUMBER_FIELDS:
                options[name] = control.text()
            elif self.method == rmst.METHOD and name in rmst_form.NUMBER_FIELDS:
                options[name] = rmst_dialog.read_number(control.text())
            elif self.method == rmst.METHOD and name == rmst.REFERENCE:
                options[name] = control.currentData()
            elif self.method == cox_outputs.METHOD and name == cox_outputs.GRAPH_TERM:
                options[name] = control.currentData() or ""
            elif isinstance(control, (Profiles, ordinal_options.OrderEditor, weibull_options.Times, kappa_options.CategoryOrder)):
                options[name] = control.values()
            elif type(kind) in (int, float):
                text = control.text().strip()
                try:
                    value = type(kind)(decimal_comma(text) if type(kind) is float else text)
                except ValueError:
                    raise FieldError(name, qt("qt.whole_number" if type(kind) is int else "qt.number",
                                              name=field_label(name))) from None
                if type(kind) is float and not np.isfinite(value):
                    raise FieldError(name, qt("qt.number", name=field_label(name)))
                options[name] = value
            elif kind == TEXT:
                options[name] = control.text()
            elif kind in (TERM_LIST, select_editor.EDITOR, plot_function.CURVE_LIST, transpose_xy.SETS_LIST,
                          PAIRWISE_PAIR_LIST):
                options[name] = control.values()
            elif kind == CONTRAST_LIST:
                options.update(control.values())  # the four planned-contrast keys, or none
            elif kind == EQUATION_TEXT:
                options[name] = control.toPlainText().strip()
            elif kind == PARAMETER_LIST:
                options[name] = control.values()
            elif kind == global_catalog.TABLE:
                options.update(control.values())
            elif kind in (global_fit.PARAMETER_LIST, global_fit.SERIES_LIST):
                value = control.values()
                if value or self.method != global_catalog.METHOD:
                    options[name] = value
            elif kind == GROUP_CHOICE:
                value = control.currentText()
                options[name] = value if self.method in ("Kaplan–Meier survival", lognormal_tests.LOGNORMAL) else value.strip()
            else:
                value = control.currentData()
                if value is None:
                    value = control.currentText()
                if kind == OPTIONAL:
                    value = value or None
                elif kind is None and not value:
                    raise FieldError(name, qt("qt.choose_column", name=field_label(name)))
                options[name] = value
        if self.method == ellipse_groups.METHOD:
            saved = self._saved()
            for name in self.hidden:
                if name in self.controls and name in saved:
                    options[name] = deepcopy(saved[name])
            if self.ellipse_groups.styles:
                options[ellipse_groups.GROUP_STYLES] = deepcopy(self.ellipse_groups.styles)
        if self.icc is not None:
            options = self.icc.ordered(options)  # raters in the order they were ticked
        if self.ecdf is not None:
            options = self.ecdf.ordered(options)  # series in the order they were ticked
        if self.pareto is not None:
            options = self.pareto.canonical(options)
        return self.anova.canonical(options) if self.anova is not None else options

    def accept(self):
        try:
            options = global_fit.confirm(self, self.options())
            if self.method == global_catalog.METHOD:
                global_catalog.check_global_weighting(self.data, options)
            if self.method == "Kaplan–Meier survival":
                check_survival_options(self.data, options)
            if self.method == "t-test":
                ttest_options.preserve_direction(options, self.data)
            if self.method == lognormal_tests.LOGNORMAL:
                lognormal_tests.check_grouped(self.data, options)
            if self.method in regression_range.METHODS:
                ranges = regression_range.normalize(options)
                fit_data = regression_range.fitting_rows(self.data, options.get("X"), ranges)
            if self.method == "Nonlinear regression" and options.get(MERGE_REPLICATES):
                replicate_groups(fit_data, options)
            if self.anova is not None:
                self.anova.check(options)  # the engine's cheap checks; the fit stays on the worker
            if self.stability is not None:
                self.stability.check(options)  # the engine's checks and budgets; the fits stay on the worker
            if self.repeated is not None:
                self.repeated.check(options)  # recipe and worksheet checks; the bootstrap stays on the worker
            if self.sphericity is not None:
                self.sphericity.check(options)  # the design check of the corrections; the fit stays on the worker
            if self.icc is not None:
                self.icc.check(options)  # recipe and worksheet checks; the bootstrap stays on the worker
            if self.ecdf is not None:
                self.ecdf.check(options)  # recipe and worksheet checks before the worker starts
            if self.interaction is not None:
                self.interaction.check(options)
            if self.precision is not None:
                self.precision.check(options)  # recipe and worksheet checks; the bootstrap stays on the worker
            if self.raincloud is not None:
                self.raincloud.check(options)
            if self.pareto is not None:
                self.pareto.check(options)
            if self.method == mean_permutation.METHOD:
                mean_permutation.check_options(self.data, options)
            if self.method == yuen.METHOD:
                if options.get(yuen.INPUT) == yuen.GROUPED and yuen.GROUP_ORDER in self._saved():
                    options[yuen.GROUP_ORDER] = self._saved()[yuen.GROUP_ORDER]
                yuen.check_options(self.data, options)
            if self.method == brunner_munzel.METHOD:
                brunner_munzel.check_options(self.data, options)
            if self.method == mood_median.METHOD:
                mood_median.check_options(self.data, options)
            if self.method == "Interpolate a standard curve":
                calibration.check_calibration_options(self.data, options)
            if self.method == XY_METHOD:
                converted = self.graph_type_source is not None and self.graph_type_source[0] != self.method
                check_xy_options(self.data, retain_recipe_options(options, self._saved()),
                                 "linear" if converted else self.xy_left_scale)
            if self.method == SELECT_TRANSFORM:
                check_select_transform(self.data, options)
            if self.method == extraction.EXTRACT_REARRANGE:
                extraction.check_options(self.data, options)
            if self.method == "Hierarchical clustering":
                check_hierarchical_options(self.data, options)
            if self.method == HIERARCHY_GRAPH:
                check_hierarchy_view(self.data, options)
            if self.method in kmeans_options.METHODS:
                kmeans_options.scale(options)
                kmeans_options.fit_options(self.method, self.data, options)
            if self.method == kmeans_reports.MODEL_GRAPH:
                kmeans_reports.check_model_plot(self.data, options)
            logistic_validation.check(self, options)  # Validate binary logistic model: no fit before the worker
            if self.reshape is not None:
                self.reshape.check(options)  # keys and levels only; the matrix is built on the worker
            if self.join is not None:
                self.join.check(options)
            if self.method == cluster_silhouette.METHOD:
                cluster_silhouette.check_options(self.data, options)
            if self.method == plot_function.PLOT_FUNCTION:
                model = plot_function.check_model(options)
                plot_function.check_curves(model, options.get(plot_function.CURVES))
            if self.method == power_plan.METHOD:
                options = power_plan.normalized_options(options, power_plan.check_options(options))
            if self.method == mcnemar_power.METHOD:
                options = mcnemar_power.normalized_options(options)
            if self.method == cox_outputs.METHOD:
                if cox_exact.is_exact(options):
                    cox_exact.check_outputs(options)
                else:
                    cox_outputs.graph_view(options)
            if self.method == "Descriptive statistics" and options.get(SUMMARY_FORMAT) == GEOMETRIC_REPORT:
                summary_confidence(options)
            if self.method == tolerance.TOLERANCE:
                tolerance.check_options(self.data, options)
            if self.method == weibull.METHOD:
                weibull.Settings(options)  # Worksheet validation and the fit run on the worker.
            if self.method == ordinal.ORDINAL_LOGIT:
                ordinal.check_dialog_options(self.data, options, self.controls[ordinal.ORDER][1].state.observed)
            if self.method == rmst.METHOD:
                rmst.check_options(self.data, options)
            if self.method == kappa.METHOD:
                kappa.check_options(self.data, options)
        except FieldError as error:
            self.show_error(self.anova.message(error) if self.anova is not None else error, error.field)
            return
        except (ValueError, OverflowError) as error:
            self.show_error(error)
            return
        self.result = (self.method, options)
        super().accept()

    def _message(self, error, field=None):
        if self.method == "Kaplan–Meier survival":
            return ui(str(error))
        if self.method == "t-test":
            return translate_message(str(error), "ttest.error.")
        if self.method == lognormal_tests.LOGNORMAL:
            return lognormal_tests.format_error(error)
        if self.method == curve_pipeline.CURVE_METHOD:
            return curve_pipeline_dialog.describe_error(error, field)
        if self.method in regression_range.METHODS and field in regression_range.FIELDS:
            return ui(str(error))
        if self.method in (global_fit.GLOBAL_CUSTOM_EQUATION, global_catalog.METHOD):
            return global_fit.describe_error(error, field)
        if self.method in (*kmeans_options.METHODS, kmeans_reports.MODEL_GRAPH):
            return ui(str(error))
        if self.stability is not None:  # K-means stability: engine messages in the active language
            return self.stability.message(error)
        if logistic_validation.applies(self):
            return logistic_validation.message(error)
        if self.repeated is not None:  # Bland–Altman for repeated pairs: engine messages in the active language
            return self.repeated.message(error)
        if self.sphericity is not None:  # Repeated measures ANOVA: engine messages in the active language
            return self.sphericity.message(error, field)
        if self.icc is not None:  # Intraclass correlation: engine messages in the active language
            return self.icc.message(error)
        if self.ecdf is not None:
            return self.ecdf.message(error)
        if self.interaction is not None:
            return self.interaction.message(error)
        if self.precision is not None:  # Precision–recall curve: engine messages in the active language
            return self.precision.message(error)
        if self.raincloud is not None:
            return self.raincloud.message(error)
        if self.pareto is not None:
            return self.pareto.message(error)
        if self.method == calibration_options.METHOD:
            return calibration_options.translate_error(error)
        if self.method == reshape_editor.METHOD:
            return reshape_editor.message(error)
        if self.method == SELECT_TRANSFORM:
            return select_editor.message(error)
        if self.method in ("Hierarchical clustering", HIERARCHY_GRAPH):
            return ui(str(error))
        if self.method == extraction.EXTRACT_REARRANGE:
            if str(error) == f"Choose a column for {field}.":
                return qt("qt.choose_column", name=field_label(field))
            return ui(str(error))
        if self.method == join_editor.wj.METHOD:
            return join_editor.message(error)
        if self.method == cluster_silhouette.METHOD:
            return translate_message(str(error), "silhouette.error.", convert={"field": field_label})
        if self.method == paired.PAIRED_PROPORTIONS:
            return translate_message(error, paired.ERROR_PREFIX,
                                     convert={"field": lambda name: tr(paired.LABEL_KEYS.get(name, name))})
        if self.method == power_plan.METHOD:
            thousands = lambda value: value.replace(",", ".")
            return translate_message(error, "power.error.", convert={
                "field": field_label, "low": thousands, "high": thousands, "limit": thousands, "count": thousands})
        if self.method == mcnemar_power.METHOD:
            return translate_message(str(error), mcnemar_power.ERROR_PREFIX, convert={"field": field_label})
        if self.method == cox_outputs.METHOD:
            return cox_outputs.cox_message(cox_exact.translate_error(error))
        if self.method == tolerance.TOLERANCE:
            return translate_message(error, tolerance.ERROR_PREFIX,
                                     convert={"field": lambda name: tr(tolerance.LABEL_KEYS.get(name, name))})
        if self.method == weibull.METHOD:
            return weibull_options.message(error)
        if self.method == ordinal.ORDINAL_LOGIT:
            return ordinal_options.describe_error(error, field)
        if self.method == rmst.METHOD:
            return rmst_dialog.describe_error(error, field)
        if self.method == kappa.METHOD:
            return kappa_text.describe_error(error, field)
        if self.method == mean_permutation.METHOD:
            return permutation_text.describe_error(error, field)
        if self.method == yuen.METHOD:
            return yuen.describe_error(error, field)
        if self.method == brunner_munzel.METHOD:
            return brunner_munzel.describe_error(error, field)
        if self.method == mood_median.METHOD:
            return mood_median.describe_error(error, field)
        if self.method == XY_METHOD:
            return translate_message(error, "xy.error.")
        return str(error)

    def show_error(self, error, field=None):
        self.error_field = field
        self.banner.setText(self._message(error, field))
        self.banner.setVisible(True)
        if field:
            self.focus_field(field, error)

    def clear_field_error(self, field):
        if self.error_field == field:
            self.banner.hide()
            self.error_field = None


def choose(parent, frame, **options):
    """Show the dialog; return (method, options) or None."""
    dialog = AnalysisDialog(parent, frame, **options)
    return dialog.result if dialog.exec() == QDialog.DialogCode.Accepted else None


__all__ = ["AnalysisDialog", "choose", "tr"]
