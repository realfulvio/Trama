"""Validation error that names the dialog field to correct.

It lives in a leaf module so engine modules such as ``stats`` can raise it without importing
``processing`` (which depends on ``stats``). ``processing.FieldError`` is the same class.
"""


class FieldError(ValueError):
    """A validation error that names the dialog field the user should change."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
