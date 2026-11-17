"""Conditional equation syntax (0.81): grammar, lazy evaluation per element, branch codes and breaks.

Expected values come from plain Python written here, never from the engine under test.
"""
import math
import unittest
from unittest.mock import patch

import numpy as np

from analisi import custom_equations as ce
from analisi.custom_equations import (ARITHMETIC, CONDITIONAL, MAX_NODES, ConditionError, compile_equation,
                                      curve_with_breaks)
from analisi.field_error import FieldError


def conditional(text, names=()):
    return compile_equation(text, list(names), syntax=CONDITIONAL)


class EvaluationTests(unittest.TestCase):
    def test_against_plain_python(self):
        cases = [
            ("if(X<0,A+B*X,A+C*X)", "ABC", dict(A=1., B=2., C=3.), lambda x: 1 + 2 * x if x < 0 else 1 + 3 * x),
            ("if((X>=-1) and (X<=1),A,if(X<-1,B,C))", "ABC", dict(A=10., B=20., C=30.),
             lambda x: 10 if -1 <= x <= 1 else 20 if x < -1 else 30),
            ("if(not (X<0) and (X<2) or (X==3),1,0)", "", {}, lambda x: 1 if (not x < 0 and x < 2) or x == 3 else 0),
            ("if(not X<0 or X>5 and X<6,1,0)", "", {}, lambda x: 1 if (not x < 0) or (x > 5 and x < 6) else 0),
            ("if((X+1)*2>3,X^2,-X^2)", "", {}, lambda x: x ** 2 if (x + 1) * 2 > 3 else -x ** 2),
            ("2*if(X!=0,1/X,0)+if(X<=1,1,0)", "", {}, lambda x: 2 * (1 / x if x != 0 else 0) + (1 if x <= 1 else 0)),
            ("if(if(X<0,T,-1)>0,5,6)", "T", dict(T=1.), lambda x: 5 if (1 if x < 0 else -1) > 0 else 6),
        ]
        x = [-3., -2., -1., -.5, 0., .5, 1., 2., 3., 5.5, 7.]
        for text, names, values, reference in cases:
            with self.subTest(text):
                np.testing.assert_allclose(conditional(text, names).evaluate(x, values), [reference(v) for v in x])

    def test_lazy_domain_example_of_the_specification(self):
        x = [-4., -1., 0., 1., math.e]
        np.testing.assert_allclose(conditional("if(X>0,log(X),sqrt(-X))").evaluate(x, {}), [2, 1, 0, 0, 1])

    def test_inactive_branch_and_short_circuit_never_see_their_elements(self):
        seen = []

        def spy(values):
            seen.append(np.array(values, copy=True))
            if np.any(np.asarray(values) <= 0):
                raise AssertionError("inactive element evaluated")
            return np.log(values)

        with patch.dict(ce.FUNCTIONS, {"log": spy}):
            np.testing.assert_allclose(conditional("if(X>0,log(X),0)").evaluate([-1., 1., 2.], {}),
                                       [0, 0, np.log(2)])
            np.testing.assert_allclose(conditional("if((X>0) and (log(X)>0),1,2)").evaluate([-1., 1., 3.], {}),
                                       [2, 2, 1])
            np.testing.assert_allclose(conditional("if((X<=0) or (log(X)>0),1,2)").evaluate([-1., .5, 3.], {}),
                                       [1, 2, 1])
        self.assertEqual([len(values) for values in seen], [2, 2, 2])
        # 1/0 is never computed for the element decided by the left side.
        np.testing.assert_allclose(conditional("if((X==0) or (1/X>0),1,2)").evaluate([-1., 0., 1.], {}), [2, 1, 1])

    def test_shapes_and_order(self):
        compiled = conditional("if(X<0,A,X)", "A")
        matrix = np.array([[-2., 3.], [4., -5.]])
        np.testing.assert_allclose(compiled.evaluate(matrix, {"A": 9.}), [[9, 3], [4, 9]])
        self.assertEqual(compiled.evaluate(np.array(-1.), {"A": 9.}).shape, ())
        self.assertEqual(float(compiled.evaluate(-1., {"A": 9.})), 9.)
        self.assertEqual(compiled.evaluate(np.array([]), {"A": 9.}).shape, (0,))
        self.assertEqual(compiled.evaluate(np.empty((0, 3)), {"A": 9.}).shape, (0, 3))
        self.assertEqual(conditional("if(X<0,1,2)").evaluate([5., -5.], {}).tolist(), [2., 1.])
        # The input is never modified, and a constant branch keeps the shape of x.
        source = np.array([-1., 1.])
        conditional("if(X<0,X,2)").evaluate(source, {})[0] = 99
        self.assertEqual(source.tolist(), [-1., 1.])

    def test_active_branch_may_still_be_undefined(self):
        values = conditional("if(X<0,log(X),1/X)").evaluate([-1., 0., 2.], {})
        self.assertTrue(np.isnan(values[0]) and np.isinf(values[1]))
        self.assertEqual(values[2], .5)

    def test_comparisons_are_exact(self):
        np.testing.assert_array_equal(conditional("if(X==0.3,1,0)").evaluate([0.1 + 0.2, 0.3], {}), [0, 1])
        np.testing.assert_array_equal(conditional("if(X!=0.3,1,0)").evaluate([0.1 + 0.2, 0.3], {}), [1, 0])

    def test_non_finite_active_condition_is_an_error_not_false(self):
        for text in ("if(log(X)>0,1,2)", "if(1/X>0,1,2)", "if(X<0,1,2)"):
            with self.subTest(text), self.assertRaises(ConditionError) as caught:
                conditional(text).evaluate([2., -1. if "log" in text else 0. if "1/X" in text else np.nan], {})
            self.assertEqual(caught.exception.field, "Equation")
            self.assertEqual(caught.exception.position, 1)
        with self.assertRaises(ConditionError) as caught:
            conditional("if(1/X>0,1,2)").evaluate(np.array([[1., 2.], [0., 3.]]), {})
        self.assertEqual(caught.exception.position, 2)  # flat index of the 0
        # Not evaluated, so not an error: the left side decides.
        conditional("if((X>0) and (log(X)>0),1,2)").evaluate([-1.], {})

    def test_condition_coefficients_and_missing_values(self):
        compiled = conditional("if(X<T*K,A,if(X>U,B,A))", "ABTUK")
        self.assertEqual(compiled.condition_parameters, ("T", "U", "K"))
        self.assertEqual(conditional("A+B*X", "AB").condition_parameters, ())
        with self.assertRaises(FieldError) as caught:
            compiled.evaluate([1.], {"A": 1.})
        self.assertEqual(caught.exception.field, "Parameters")


class BranchCodeTests(unittest.TestCase):
    def test_same_path_same_code(self):
        compiled = conditional("if(X<T,A+B*X,A+C*X)", "ABCT")
        values = dict(A=2., B=1., C=3., T=0.)
        codes = compiled.branch_codes([-2., -1., 0., 1.], values)
        self.assertEqual(codes.dtype.kind, "i")
        self.assertEqual(len(set(codes[:2])), 1)
        self.assertEqual(len(set(codes[2:])), 1)
        self.assertNotEqual(codes[0], codes[-1])

    def test_codes_do_not_depend_on_batching_or_shape(self):
        compiled = conditional("if(X<0,1,if(X<1,2,3))+if(X<2,0,1)")
        x = np.array([-1., .5, 1.5, 3.])
        together = compiled.branch_codes(x, {})
        alone = [int(compiled.branch_codes([value], {})[0]) for value in x]
        self.assertEqual(together.tolist(), alone)
        self.assertEqual(len(set(alone)), 4)
        self.assertEqual(compiled.branch_codes(x.reshape(2, 2), {}).shape, (2, 2))
        self.assertEqual(compiled.branch_codes(np.array(1.), {}).shape, ())

    def test_no_condition_is_code_zero(self):
        for syntax in (ARITHMETIC, CONDITIONAL):
            codes = compile_equation("A+X", ["A"], syntax=syntax).branch_codes([1., 2.], {"A": 1.})
            self.assertEqual(codes.tolist(), [0, 0])

    def test_breaks(self):
        x, y = np.array([0., 1., 2., 3., 4.]), np.array([0., 1., 5., 6., 7.])
        bx, by = curve_with_breaks(x, y, [1, 1, 2, 2, 1])
        np.testing.assert_array_equal(bx, [0, 1, np.nan, 2, 3, np.nan, 4])
        np.testing.assert_array_equal(by, [0, 1, np.nan, 5, 6, np.nan, 7])
        same_x, same_y = curve_with_breaks(x, y, np.zeros(5, dtype=int))
        np.testing.assert_array_equal(same_x, x)
        same_x[0] = 99
        self.assertEqual(x[0], 0.)  # a new array, never a view
        np.testing.assert_array_equal(curve_with_breaks([], [], [])[0], [])
        with self.assertRaises(ValueError):
            curve_with_breaks([1., 2.], [1.], [0, 0])


class GrammarTests(unittest.TestCase):
    def reject(self, text, names=(), field="Equation", syntax=CONDITIONAL):
        with self.assertRaises(FieldError) as caught:
            compile_equation(text, list(names), syntax=syntax)
        self.assertEqual(caught.exception.field, field, text)
        return str(caught.exception)

    def test_rejections(self):
        for text in ("if(X>0,1)", "if(X>0,1,2,3)", "if(X>0)", "if()", "if", "if X", "1+(X<0)", "X<0", "0<X<1",
                     "if(X,1,2)", "if(X>0,X<1,2)", "if(X>0,1,X.real)", "if(X>0,1,X[0])", "if(X>0,1,__import__(X))",
                     "if(X>0,'a',2)", "if(X>0,[1],2)", "if(X=0,1,2)", "if(X>0,1,2)=1", "X and 1", "not (X<0)",
                     "if(X<0 and,1,2)", "if(X <> 0,1,2)", "If(X<0,1,2)", "IF(X<0,1,2)", "if(X<0,1,2) if",
                     "if(X<0;1,2)", "lambda: X", "if((X<0),1,2", "if(X<0,1,2))", "if(True,1,2)", "max(X,1)"):
            with self.subTest(text):
                self.reject(text)

    def test_messages_guide_the_correction(self):
        self.assertIn("and", self.reject("if(0<X<1,1,2)"))
        self.assertIn("not a number", self.reject("1+(X<0)"))
        self.assertIn("three arguments", self.reject("if(X>0,1)"))
        self.assertIn("Conditional", self.reject("if(X<0,1,2)", syntax=ARITHMETIC))

    def test_arithmetic_is_unchanged(self):
        compiled = compile_equation("if+and*X-or/not", ["if", "and", "or", "not"])
        np.testing.assert_allclose(compiled.evaluate([2.], {"if": 1., "and": 2., "or": 6., "not": 3.}), [3.])
        self.assertEqual((compiled.syntax, compiled.branches, compiled.condition_parameters), (ARITHMETIC, 0, ()))
        np.testing.assert_allclose(compile_equation("-X^2", []).evaluate([2.], {}), [-4.])
        np.testing.assert_allclose(compile_equation("2^3^2", []).evaluate([0.], {}), [512.])
        self.assertEqual(compile_equation("A+X", ["A"]), compile_equation("A+X", ["A"], syntax=None))
        # Same tree and values in both syntaxes when the formula has no if(...).
        a = compile_equation("A*exp(-K*X)", ["A", "K"])
        c = compile_equation("A*exp(-K*X)", ["A", "K"], syntax=CONDITIONAL)
        self.assertEqual(a.tree, c.tree)
        x = np.linspace(-1, 1, 7)
        np.testing.assert_array_equal(a.evaluate(x, {"A": 2., "K": .3}), c.evaluate(x, {"A": 2., "K": .3}))

    def test_conditional_words_are_reserved_only_in_conditional(self):
        for name in ("if", "and", "or", "not"):
            with self.subTest(name):
                self.reject(f"{name}+X", [name], field="Parameters")
                compile_equation(f"{name}+X", [name])
        # Case-sensitive: other spellings stay coefficient names.
        np.testing.assert_allclose(conditional("If+And+X", ["If", "And"]).evaluate([1.], {"If": 1., "And": 1.}), [3.])

    def test_unknown_syntax(self):
        self.reject("A+X", ["A"], field="Equation syntax", syntax="conditional")
        self.reject("A+X", ["A"], field="Equation syntax", syntax="Python")

    def test_budgets_count_inactive_branches(self):
        deep = "if(X<0," * 33 + "1" + ",2)" * 33
        self.reject(deep)
        # 22 if(...) of 6 nodes each exceed the node budget although one branch of each never runs.
        self.assertIn(str(MAX_NODES), self.reject("+".join(["if(X<0,1,2)"] * 22)))
        self.assertIn("1024", self.reject("if(X<0,1," + "1+" * 520 + "1)"))
        # The largest legal nesting still compiles and its codes fit in 64-bit integers.
        # Nested and side by side: every if(...) is one base-3 digit of the code, well inside 64 bits.
        many = "+".join(["if(X<1,1," * 4 + "2" + ")" * 4] * 5)
        compiled = conditional(many)
        self.assertEqual(compiled.branches, 20)
        codes = compiled.branch_codes([0., 5.], {})
        self.assertEqual(int(codes[0]), sum(3 ** (4 * k) for k in range(5)))
        self.assertEqual(int(codes[1]), sum(2 * 3 ** k for k in range(20)))
        np.testing.assert_allclose(compiled.evaluate([0., 5.], {}), [5., 10.])

    def test_no_python_evaluation_machinery(self):
        import inspect
        import re
        source = inspect.getsource(ce)
        found = re.findall(r"(?<![\w.])(?:eval|exec|compile|__import__|getattr)\(|^\s*(?:import|from) ast\b", source, re.M)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
