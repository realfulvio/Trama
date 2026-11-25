"""Trama on PySide6/Qt.

The statistical engine in ``analisi`` is shared with the classic Tk interface; this package
only contains the Qt window, pages and dialogs. Importing the package does not import Qt:
``trama_qt.app.main`` does.
"""
import importlib.util


def qt_available():
    """True when PySide6 can be imported."""
    return importlib.util.find_spec("PySide6") is not None
