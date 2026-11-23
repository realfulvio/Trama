"""Canonical worksheet join choices and translated validation messages."""
from . import worksheet_join as wj
from .i18n import active_language, tr, translate_message


TYPE_KEYS = {wj.INNER: "join.choice.inner", wj.LEFT: "join.choice.left", wj.FULL: "join.choice.full"}
CARDINALITY_KEYS = {wj.ONE_TO_ONE: "join.choice.one_one", wj.ONE_TO_MANY: "join.choice.one_many",
                    wj.MANY_TO_ONE: "join.choice.many_one", wj.MANY_TO_MANY: "join.choice.many_many"}
FIELD_KEYS = {wj.RIGHT_SHEET: "join.field.sheet", wj.LEFT_KEYS: "join.field.left_keys",
              wj.RIGHT_KEYS: "join.field.right_keys", wj.JOIN_TYPE: "join.field.type",
              wj.CARDINALITY: "join.field.cardinality"}
_NUMBER = ("rows", "cells", "max_rows", "max_cells", "count", "limit")


def _thousands(text):
    """Thousands separators of an English number, in the active language."""
    return text.replace(",", ".") if active_language() == "it" else text


def message(error):
    """An engine or dialog error of the join in the active language."""
    convert = {name: _thousands for name in _NUMBER}
    convert["rule"] = lambda rule: tr(CARDINALITY_KEYS[rule]) if rule in CARDINALITY_KEYS else rule
    return translate_message(str(error), "join.error.", convert)
