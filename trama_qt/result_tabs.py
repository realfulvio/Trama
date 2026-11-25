"""Use a result list when the output tabs do not fit on the sheet."""

from PySide6.QtWidgets import QComboBox, QTabWidget, QVBoxLayout, QWidget

from analisi.distribution_graphs import BOX_VIOLIN

from .strings import qt


_TAB_KEYS = {
    BOX_VIOLIN: {
        "Group summary": "qt.result_group_summary",
        "Plotted observations": "qt.result_plotted",
        "Violin density": "qt.result_violin_density",
        "Settings": "qt.result_settings",
    },
    "Descriptive statistics": {"Summary": "qt.result_summary"},
    "Linear regression": {
        "Regression": "qt.result_regression",
        "Residuals": "qt.result_residuals",
        "Curve coordinates": "qt.result_curve_coordinates",
        "Pointwise confidence band": "qt.result_confidence_band",
        "Pointwise prediction band": "qt.result_prediction_band",
        "Linear estimates": "qt.result_linear_estimates",
    },
}
_DISTRIBUTION_HEADERS = {
    "Row": "qt.result_row", "Group": "qt.result_group", "Value": "qt.result_value",
    "Median": "qt.result_median", "Minimum": "qt.result_minimum", "Maximum": "qt.result_maximum",
    "Mean": "qt.result_mean", "Bandwidth": "qt.result_bandwidth", "Note": "qt.result_note",
    "Lower whisker": "qt.result_lower_whisker", "Upper whisker": "qt.result_upper_whisker",
    "Outside whiskers": "qt.result_outside_whiskers", "Role": "qt.result_role", "Density": "qt.result_density",
    "Half-width": "qt.result_half_width",
}


def result_labels(method, title):
    """Localize the view while keeping the result keys and frame columns for linked recipes."""
    key = _TAB_KEYS.get(method, {}).get(title)
    if key is None:
        return str(title), {}
    headers = {name: qt(label) for name, label in _DISTRIBUTION_HEADERS.items()} if method == BOX_VIOLIN else {}
    return qt(key), headers


class ResultTabs(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox()
        self.choice.setAccessibleName(qt("qt.result_table"))
        self.choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.choice.setMinimumContentsLength(12)
        self.choice.hide()
        layout.addWidget(self.choice)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        layout.addWidget(self.tabs, 1)
        self.choice.currentIndexChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.choice.setCurrentIndex)

    def add_table(self, view, title):
        self.choice.addItem(title)
        self.tabs.addTab(view, title)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        bar = self.tabs.tabBar()
        use_list = self.tabs.count() > 1 and bar.sizeHint().width() > self.width()
        bar.setVisible(not use_list)
        self.choice.setVisible(use_list)
