"""File → Export with options… on Qt: format, physical width, DPI, transparency and SVG text.

Same settings as the classic dialog (``analisi.figure_export_dialog`` needs Tk); ``analisi.figure_export``
plans and writes the file.
"""
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit

from analisi import figure_export as fe
from analisi.data import decimal_comma
from analisi.i18n import active_language, ui

CUSTOM = "Custom"
FORMAT_NAMES = {"PNG": "png", "TIFF": "tiff", "SVG": "svg", "PDF": "pdf"}
SESSION = {"preset": "Screen", **fe.PRESETS["Screen"]}  # Choices last for the session.
_ITALIAN = {"Export with options": "Esporta con opzioni", "Preset": "Predefinito", "Screen": "Schermo",
            "Print": "Stampa", "Vector": "Vettoriale", "Custom": "Personalizzato", "Format": "Formato",
            "Width (mm)": "Larghezza (mm)", "SVG text": "Testo SVG", "Text": "Testo", "Paths": "Tracciati",
            "Transparent background": "Sfondo trasparente",
            "Empty width keeps the current figure size.": "Senza larghezza resta la dimensione attuale.",
            "Empty width keeps the layout's original page size.":
                "Senza larghezza resta la dimensione originale della pagina del layout.",
            "Final size": "Dimensione finale",
            "TIFF is opaque RGB with LZW compression.": "Il TIFF è RGB opaco con compressione LZW.",
            "Vector output; any raster element is drawn at 300 DPI.":
                "Uscita vettoriale; gli elementi raster sono disegnati a 300 DPI.",
            "PNG and TIFF draw the layout as a raster image. Choose SVG or PDF to preserve vector graphics.":
                "PNG e TIFF disegnano il layout come immagine raster. Scegli SVG o PDF per la grafica vettoriale.",
            "This layout embeds its panels as images, so they stay raster even in SVG and PDF.":
                "Questo layout contiene i pannelli come immagini, quindi restano raster anche in SVG e PDF.",
            "Width must be a number in millimetres.": "La larghezza deve essere un numero in millimetri.",
            "DPI must be a whole number.": "I DPI devono essere un numero intero."}


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


class ExportOptionsDialog(QDialog):
    """``size`` is the figure size in inches, ``layout_size`` the page size of a native layout.

    ``result`` is a settings dict for ``figure_export`` after OK.
    """

    def __init__(self, parent, size, *, raster_panels=False, layout_size=None):
        super().__init__(parent)
        self.setWindowTitle(t("Export with options"))
        self.size, self.raster_panels, self.layout_size, self.result = size, raster_panels, layout_size, None
        self.loading = False
        form = QFormLayout(self)
        self.preset = QComboBox()
        for name in (*fe.PRESETS, CUSTOM):
            self.preset.addItem(t(name), name)
        self.preset.setCurrentIndex(self.preset.findData(SESSION.get("preset", CUSTOM)))
        form.addRow(t("Preset"), self.preset)
        self.format = QComboBox()
        self.format.addItems(list(FORMAT_NAMES))
        self.format.setCurrentText(next(k for k, v in FORMAT_NAMES.items() if v == SESSION.get("format", "png")))
        form.addRow(t("Format"), self.format)
        self.width = QLineEdit("" if SESSION.get("width_mm") is None else f"{SESSION['width_mm']:g}")
        form.addRow(t("Width (mm)"), self.width)
        self.dpi = QLineEdit(f"{SESSION.get('dpi', fe.DEFAULT_DPI):g}")
        form.addRow("DPI", self.dpi)
        self.svg_text = QComboBox()
        self.svg_text.addItem(t("Text"), "text")
        self.svg_text.addItem(t("Paths"), "paths")
        self.svg_text.setCurrentIndex(1 if SESSION.get("svg_text") == "paths" else 0)
        form.addRow(t("SVG text"), self.svg_text)
        self.transparent = QCheckBox(t("Transparent background"))
        self.transparent.setChecked(bool(SESSION.get("transparent", False)))
        form.addRow(self.transparent)
        note = QLabel(t("Empty width keeps the layout's original page size." if layout_size is not None
                        else "Empty width keeps the current figure size."))
        note.setObjectName("muted")
        form.addRow(note)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        form.addRow(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.form = form
        self.preset.currentIndexChanged.connect(self.apply_preset)
        for signal in (self.format.currentIndexChanged, self.width.textChanged, self.dpi.textChanged,
                       self.transparent.toggled, self.svg_text.currentIndexChanged):
            signal.connect(self.edited)
        self.refresh()

    def apply_preset(self, *_):
        values = fe.PRESETS.get(self.preset.currentData())
        if values is None:
            return
        self.loading = True
        self.format.setCurrentText(next(k for k, v in FORMAT_NAMES.items() if v == values["format"]))
        self.width.setText(f"{values['width_mm']:g}")
        self.dpi.setText(str(values.get("dpi", fe.DEFAULT_DPI)))
        self.transparent.setChecked(values["transparent"])
        self.loading = False
        self.refresh()

    def edited(self, *_):
        if not self.loading and self.preset.currentData() != CUSTOM:
            self.loading = True
            self.preset.setCurrentIndex(self.preset.findData(CUSTOM))
            self.loading = False
        self.refresh()

    def settings(self):
        fmt = FORMAT_NAMES[self.format.currentText()]
        settings = {"format": fmt, "transparent": self.transparent.isChecked(), "svg_text": self.svg_text.currentData()}
        text = self.width.text().strip()
        try:
            settings["width_mm"] = float(decimal_comma(text)) if text else None
        except ValueError:
            raise ValueError(t("Width must be a number in millimetres.")) from None
        if fmt in {"png", "tiff"}:
            try:
                settings["dpi"] = float(decimal_comma(self.dpi.text().strip()))
            except ValueError:
                raise ValueError(t("DPI must be a whole number.")) from None
        return settings

    def plan(self):
        return fe.plan_export(self.layout_size if self.layout_size is not None else self.size, self.settings())

    def _show(self, widget, visible):
        widget.setVisible(visible)
        label = self.form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def refresh(self, *_):
        fmt = self.format.currentText()
        raster = fmt in {"PNG", "TIFF"}
        self._show(self.dpi, raster)
        self._show(self.svg_text, fmt == "SVG")
        self.transparent.setVisible(fmt != "TIFF")
        try:
            plan = self.plan()
        except ValueError as error:
            self.summary.setObjectName("errorBanner")
            self.summary.setText(ui(str(error)))
            self.note.setText("")
            self.summary.style().polish(self.summary)
            return
        self.summary.setObjectName("")
        self.summary.style().polish(self.summary)
        text = f"{t('Final size')}: {plan['width_mm']:.1f} × {plan['height_mm']:.1f} mm"
        if plan["pixels"]:
            width, height = plan["pixels"]
            text += f" · {width} × {height} px ({width * height / 1e6:.1f} Mpx)"
        self.summary.setText(text)
        notes = []
        if plan["format"] == "tiff":
            notes.append(t("TIFF is opaque RGB with LZW compression."))
        if self.layout_size is not None and raster:
            notes.append(t("PNG and TIFF draw the layout as a raster image. Choose SVG or PDF to preserve vector "
                           "graphics."))
        elif self.raster_panels:
            notes.append(t("This layout embeds its panels as images, so they stay raster even in SVG and PDF."))
        elif not raster:
            notes.append(t("Vector output; any raster element is drawn at 300 DPI."))
        self.note.setText(" ".join(notes))

    def accept(self):
        try:
            self.plan()
            settings = self.settings()
        except ValueError as error:
            self.summary.setObjectName("errorBanner")
            self.summary.setText(ui(str(error)))
            return
        SESSION.clear()
        SESSION.update(preset=self.preset.currentData(),
                       **{k: v for k, v in settings.items() if k in {"format", "width_mm", "dpi", "transparent"}})
        self.result = settings
        super().accept()
