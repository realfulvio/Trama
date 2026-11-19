"""Change input result… on Qt: the source analysis and result table an analysis reads.

Same choices as the classic dialog (``analisi.analysis_source_dialog`` needs Tk); the window validates the
link against the analysis graph before the parameters are reviewed.
"""
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel

from analisi.analysis_chain import ResultSource
from analisi.i18n import tr

CYCLE = "Analysis input links contain a cycle."


class AnalysisSourceDialog(QDialog):
    """``result`` is a one-item tuple ``(source,)`` after Continue; ``(None,)`` means the data table."""

    def __init__(self, parent, run, runs, validate_source):
        super().__init__(parent)
        self.setWindowTitle(tr("chain.change_input"))
        self.run, self.validate_source, self.result = run, validate_source, None
        self.parents = [None, *(other for other in runs if other.uid != run.uid
                                and other.result is not None and not other.calculation_error)]
        form = QFormLayout(self)
        self.source = QComboBox()
        self.source.addItem(tr("chain.original_data", title=run.title))
        for number, other in enumerate(self.parents[1:], 1):
            self.source.addItem(f"{other.name} [{number}]")
        form.addRow(tr("chain.source_analysis"), self.source)
        self.table = QComboBox()
        form.addRow(tr("chain.result_table"), self.table)
        note = QLabel(tr("chain.review_note"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        form.addRow(self.problem)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("chain.continue"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("chain.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.source.currentIndexChanged.connect(self.sync_tables)
        current = 0
        if run.source is not None:
            current = next((i for i, other in enumerate(self.parents)
                            if other is not None and other.uid == run.source.analysis_id), -1)
        self.source.setCurrentIndex(current)
        self.sync_tables()
        if run.source is not None:
            position = self.table.findText(run.source.table)
            self.table.setCurrentIndex(position)
            if current < 0 or position < 0:
                self.show_problem(tr("chain.current_unavailable"))
        self.resize(560, self.sizeHint().height())

    def show_problem(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    def parent_run(self):
        index = self.source.currentIndex()
        return (True, self.parents[index]) if index >= 0 else (False, None)

    def sync_tables(self, *_):
        _, parent = self.parent_run()
        tables = [str(name) for name in parent.result.tables] if parent is not None else []
        self.table.clear()
        self.table.addItems(tables)
        self.table.setEnabled(bool(tables))

    def accept(self):
        chosen, parent = self.parent_run()
        if not chosen:
            self.show_problem(tr("chain.choose_source"))
            self.source.setFocus()
            return
        name = self.table.currentText()
        if parent is not None:
            table = next((key for key in parent.result.tables if str(key) == name), None)
            if table is None:
                self.show_problem(tr("chain.choose_table"))
                self.table.setFocus()
                return
            candidate = ResultSource(parent.uid, table)
        else:
            candidate = None
        try:
            self.validate_source(candidate)
        except ValueError as error:
            message = tr("chain.error.cycle") if str(error) == CYCLE else str(error)
            self.show_problem(tr("chain.invalid_source", error=message))
            self.source.setFocus()
            return
        self.result = (candidate,)
        super().accept()
