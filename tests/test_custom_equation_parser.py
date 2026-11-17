"""Restricted grammar of user equations (0.61): accepted syntax, budgets and rejected constructs."""
import unittest

import numpy as np

from analisi.custom_equations import MAX_NODES, compile_equation
from analisi.field_error import FieldError


def evaluate(text, names=(), x=(1.0, 2.0, 3.0), **values):
    return compile_equation(text, names).evaluate(np.asarray(x, dtype=float), values)


class GrammarTests(unittest.TestCase):
    def test_precedence_and_aliases(self):
        np.testing.assert_allclose(evaluate("2 + 3*X^2"), [5, 14, 29])
        np.testing.assert_allclose(evaluate("-X**2"), [-1, -4, -9])
        np.testing.assert_allclose(evaluate("2^-X"), [.5, .25, .125])
        np.testing.assert_allclose(evaluate("2**3**2", x=(0,)), [512])
        np.testing.assert_allclose(evaluate("X^2"), evaluate("X**2"))

    def test_functions_and_constants(self):
        np.testing.assert_allclose(evaluate("A*exp(-K*X)+C", list("AKC"), A=2., K=.5, C=1.),
                                   2 * np.exp(-.5 * np.array([1, 2, 3.])) + 1)
        np.testing.assert_allclose(evaluate("sin(pi*X/2) + log(e) + log10(100) + sqrt(4) + abs(-1) + cos(0) + tan(0)",
                                            x=(1,)), [1 + 1 + 2 + 2 + 1 + 1 + 0])

    def test_constant_model_keeps_the_shape_of_x(self):
        self.assertEqual(evaluate("A", ["A"], A=3.).shape, (3,))
        self.assertEqual(evaluate("5").tolist(), [5.0, 5.0, 5.0])

    def test_domain_errors_are_not_repaired(self):
        self.assertTrue(np.isnan(evaluate("sqrt(X)", x=(-1.,)))[0])
        self.assertTrue(np.isinf(evaluate("1/X", x=(0.,)))[0])
        self.assertTrue(np.isinf(evaluate("10**400"))[0])  # float power, never a big Python integer
        self.assertTrue(np.isinf(evaluate("2**99999999999999"))[0])

    def test_object_is_immutable(self):
        compiled = compile_equation("A+X", ["A"])
        with self.assertRaises(Exception):
            compiled.text = "other"


class RejectionTests(unittest.TestCase):
    def reject(self, text, names=("A",), field="Equation"):
        with self.assertRaises(FieldError) as caught:
            compile_equation(text, names)
        self.assertEqual(caught.exception.field, field, text)

    def test_unsafe_constructs(self):
        for text in ("__import__('os')", "X.__class__", "A[0]", "[a for a in X]", "lambda x:x", "open(X)",
                     "RND()", "GAUSS()", "A=1", "X==1", "A if X else A", "'a'", "{1:2}", "(1,2)", "X;A", "A@X",
                     "A//X", "A%X", "~A", "X<<1", "A&X", "A|X"):
            with self.subTest(text):
                self.reject(text)

    def test_literals(self):
        for text in ("1j", "1+2j", "0x10", "1_000", "1e999", "True", "None", "A+1.2.3", "1e", "3A"):
            with self.subTest(text):
                self.reject(text)

    def test_names_and_arity(self):
        self.reject("A+B")  # B is not declared
        self.reject("a+X")  # case sensitive
        self.reject("A+Y")
        self.reject("exp(X,2)")
        self.reject("exp()")
        self.reject("exp")
        self.reject("A(X)")
        self.reject("")
        self.reject("   ")
        self.reject("A + ")
        self.reject("(A + X")
        self.reject("A + X)")

    def test_declaration_rules(self):
        self.reject("X", ("A",), "Parameters")  # declared but unused
        self.reject("A+X", ("A", "A"), "Parameters")
        for name in ("X", "Y", "pi", "e", "exp", "1A", "_A", "A-B", "É", "a" * 33, ""):
            with self.subTest(name):
                self.reject("X+1", (name,), "Parameters")
        self.reject("+".join(f"P{i}" for i in range(13)), tuple(f"P{i}" for i in range(13)), "Parameters")
        self.assertEqual(compile_equation("A" * 32 + "*X", ["A" * 32]).parameters, ("A" * 32,))

    def test_budgets_are_checked_before_evaluation(self):
        self.reject("A" + "+A" * MAX_NODES)  # nodes
        self.reject("(" * 500 + "X" + ")" * 500)  # parser recursion
        self.reject("-" * 500 + "X")
        self.reject("X^" * 500 + "X")
        self.reject("X+" * 40 + "X")  # depth 32
        self.reject("1" * 1025)  # length
        compile_equation("+".join(["X"] * 20), [])  # within the budget

    def test_twelve_coefficients_are_accepted(self):
        names = [f"P{i}" for i in range(12)]
        compiled = compile_equation("+".join(f"{n}*X" for n in names[:6]) + "+" + "+".join(names[6:]), names)
        self.assertEqual(len(compiled.parameters), 12)


if __name__ == "__main__":
    unittest.main()
