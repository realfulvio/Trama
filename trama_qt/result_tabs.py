"""Use a result list when the output tabs do not fit on the sheet."""

from PySide6.QtWidgets import QComboBox, QTabWidget, QVBoxLayout, QWidget

from .strings import qt


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
