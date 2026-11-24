"""Standard-curve calibration bindings for the Qt analysis dialog.

Keeps all existing calibration choices intact while adding dynamic field visibility,
X-unit model captions, contextual notes for Padé (1,1) and nonlinear inverse intervals,
cheap dialog-side checks (keeping the fit on the analysis worker), and IT/EN error
messages from the existing ``analisi.i18n`` catalog.
"""
from PySide6.QtWidgets import QLabel

from analisi import nonlinear_calibration as cal
from analisi.i18n import tr, translate_message, ui

METHOD = "Interpolate a standard curve"
WATCHED = (cal.DIRECTION, "Curve", "Model", cal.UNCERTAINTY)


def translate_error(error):
    """Translate a standard-curve engine error into the active UI language."""
    raw = str(error)
    for prefix in ("calib.pade.", "calib.inverse_nonlinear."):
        translated = translate_message(raw, prefix)
        if translated != raw:
            return translated
    return ui(raw)


class StandardCurveBinding:
    """Binds dynamic visibility, captions, notes and validation for standard-curve calibration."""

    def __init__(self, dialog):
        self.dialog = dialog
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        _caption, _widget, options_form = dialog.rows["Model"]
        self.options_form = options_form
        options_form.addRow(self.note)

        for name in WATCHED:
            dialog.controls[name][1].currentIndexChanged.connect(self._on_choice_changed)
        dialog.controls[cal.MISSING_X_ONLY][1].toggled.connect(
            lambda _: dialog.clear_field_error(cal.UNKNOWN_RESPONSES))
        for name in ("X", "Y", cal.UNKNOWN_RESPONSES, cal.UNKNOWN_X, cal.LEVEL, cal.COUNT):
            kind, widget = dialog.controls[name]
            signal = widget.textChanged if type(kind) in (int, float) else widget.currentIndexChanged
            signal.connect(lambda _value=None, field=name: dialog.clear_field_error(field))
        self.sync(interactive=False)

    def _value(self, name):
        return self.dialog.controls[name][1].currentData()

    def _reset_uncertainty_to_none(self):
        combo = self.dialog.controls[cal.UNCERTAINTY][1]
        position = combo.findData(cal.UNCERTAINTIES[0])
        if position >= 0 and combo.currentIndex() != position:
            combo.blockSignals(True)
            combo.setCurrentIndex(position)
            combo.blockSignals(False)

    def _on_choice_changed(self, *_):
        self.sync(interactive=True)
        if self.dialog.error_field in WATCHED or self.dialog.error_field in self.dialog.hidden:
            self.dialog.clear_field_error(self.dialog.error_field)

    def sync(self, *, interactive):
        direction = self._value(cal.DIRECTION)
        curve = self._value("Curve")
        model = self._value("Model")
        uncertainty = self._value(cal.UNCERTAINTY) or cal.UNCERTAINTIES[0]

        visibility = cal.calibration_visibility(direction, curve, uncertainty, model, pade_rows=True)
        if not visibility[cal.UNCERTAINTY]:
            if interactive:
                # Switching from an interval-capable model to a point-only model (e.g. Padé (1,1))
                # resets Uncertainty back to None so the recipe stays runnable.
                self._reset_uncertainty_to_none()
                uncertainty = cal.UNCERTAINTIES[0]
            elif uncertainty != cal.UNCERTAINTIES[0]:
                # Keep Uncertainty visible when reopening a saved/invalid recipe that asks for
                # intervals on a point-only model so the user can see the error and switch to None.
                visibility[cal.UNCERTAINTY] = True
                visibility[cal.LEVEL] = False
                visibility[cal.COUNT] = False

        self.dialog._set_field_visibility(visibility)

        self.dialog.rows["Model"][0].setText(tr(cal.model_field_key(model)))

        # Contextual note for Padé (1,1) or nonlinear inverse intervals.
        if curve == "Nonlinear" and model == cal.PADE_MODEL:
            self.note.setText(tr("calib.pade.note"))
            self.options_form.setRowVisible(self.note, True)
        elif (direction != cal.DIRECTIONS[1] and curve == "Nonlinear"
              and model in cal.INVERSE_INTERVAL_MODELS and uncertainty != cal.UNCERTAINTIES[0]):
            self.note.setText(tr("calib.inverse_nonlinear.note"))
            self.options_form.setRowVisible(self.note, True)
        else:
            self.options_form.setRowVisible(self.note, False)

    @staticmethod
    def message(error):
        return translate_error(error)


def attach(dialog):
    return StandardCurveBinding(dialog) if dialog.method == METHOD else None
