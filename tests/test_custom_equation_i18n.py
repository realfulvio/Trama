"""Every message that Fit custom equation can show before the fit has an Italian text (0.61)."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import custom_fit, i18n
from analisi.custom_equation_dialog import translate_error
from analisi.custom_equations import compile_equation
from analisi.field_error import FieldError
from tests.test_custom_fit import DECAY, GROUPED, LINE, MISSING, recipe, row, run

WEIGHTED = {"Weighting": "Inverse variance (column)", "SD column": "SD"}


def calls():
    parse = ["X.__class__", "A+B", "A+Y", "exp(X,2)", "exp(X", "exp", "A(X)", "", "A+", "(A+X", "A+X)", "1j", "1e999",
             "A+" * 70 + "A", "(" * 40 + "X" + ")" * 40, "1" * 1025, "A $ X"]
    for text in parse:
        yield lambda text=text: compile_equation(text, ["A"])
    for names in (["X"], ["A", "A"], ["a" * 33], ["1A"], ["P%d" % i for i in range(13)], []):
        yield lambda names=names: compile_equation("A+X", names)
    yield lambda: compile_equation("X", ["A"])
    yield lambda: compile_equation("A", ["A"]).evaluate(np.array([1.]), {})
    for extra in (
            {"Equation": "A+B*log(X)"}, {"Parameters": "A,B"}, {"Parameters": [1]},
            {"Parameters": [row("A", 1), row("A", 2)]}, {"Parameters": [row("A", 1, fixed="yes"), row("B", 1)]},
            {"Parameters": [row("A", "x"), row("B", 1)]}, {"Parameters": [row("A", 1, fixed=True), row("B", "x", fixed=True)]},
            {"Parameters": [row("A", 5, lower=6), row("B", 1)]}, {"Parameters": [row("A", 5, upper=1, fixed=True), row("B", 1)]},
            {"Parameters": [row("A", 1, lower=2, upper=1), row("B", 1)]},
            {"Parameters": [row("A", 1, lower="x"), row("B", 1)]}, {"Parameters": [row("A", 1, upper="x"), row("B", 1)]},
            {"Parameters": [row("A", 1), row("B", 1), row("C", 1)]},
            {"X": "nope"}, {"Y": "X"}, {"Group": "X"}, {"Weighting": "1/Y"}, {"Weighting": WEIGHTED["Weighting"]},
            {**WEIGHTED, "SD column": "X"}, {"Confidence level (%)": 100}, {"Curve points": 3},
            {"Equation": "A+B*X+C*X", "Parameters": [row("A", 1), row("B", 1), row("C", 1)]}):
        yield lambda extra=extra: run(**extra)
    yield lambda: run(LINE.head(2), Equation="A+B*X+C*X**2", Parameters=[row("A", 1), row("B", 1), row("C", 1)])
    yield lambda: run(LINE.assign(X=["a"] + list(LINE.X[1:])))
    yield lambda: run(LINE.assign(Y=[np.inf] + list(LINE.Y[1:])))
    yield lambda: run(LINE.assign(SD=[0.] + list(LINE.SD[1:])), **WEIGHTED)
    yield lambda: run(GROUPED.assign(Group=[1, "1"] + ["x"] * 14), Group="Group")
    yield lambda: run(GROUPED.assign(Group=range(16)), Group="Group")
    yield lambda: run(GROUPED.assign(Group=np.nan), Group="Group")
    yield lambda: run(GROUPED.assign(Y=GROUPED.Y.where(GROUPED.Group != "Treated")), Group="Group")
    yield lambda: run(pd.concat([GROUPED] * 6000), Group="Group")
    yield lambda: run(GROUPED.assign(X=GROUPED.X + 1), Group="Group", Equation="A+B*log(X-1)")
    yield lambda: run(pd.DataFrame({"X": [2.] * 5, "Y": [1., 2, 3, 4, 5]}))
    yield lambda: run(pd.DataFrame({"X": [1., 2, 3, 4], "Y": [1., 1, 1, 1]}), Equation="1/(A*X-A*2.5)+B*0*X",
                      Parameters=[row("A", 1), row("B", 1)])
    with patch.object(custom_fit, "MAX_EVALUATIONS", 1):
        yield lambda: run(DECAY, Equation="A*exp(-K*X)+C", Parameters=[row("A", 3), row("K", 3), row("C", 0)])


def messages():
    found = []
    for call in calls():
        try:
            call()
        except FieldError as error:
            found.append(str(error))
    return found


class ItalianMessageTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_every_engine_message_is_translated(self):
        found = messages()
        self.assertGreater(len(found), 55)
        i18n.set_language("it")
        missing = sorted({text for text in found if translate_error(text) == text})
        self.assertEqual(missing, [])

    def test_english_is_unchanged_and_values_are_literal(self):
        i18n.set_language("en")
        self.assertEqual(translate_error("Missing ) to close a parenthesis."), "Missing ) to close a parenthesis.")
        i18n.set_language("it")
        text = translate_error("Group {x}: B: the starting value 2 lies outside its limits.".replace("B:", "{B}:"))
        self.assertIn("{x}", text)
        self.assertIn("{B}", text)
        self.assertTrue(text.startswith("Gruppo {x}:"))

    def test_group_prefix_is_not_confused_with_the_group_column_message(self):
        i18n.set_language("it")
        text = translate_error("Group must be an existing column different from X and Y.")
        self.assertTrue(text.startswith("Il gruppo deve"), text)


if __name__ == "__main__":
    unittest.main()
