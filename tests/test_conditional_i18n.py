"""English and Italian messages of the conditional equation syntax (0.81): every engine and fit message has
an Italian catalogue entry, and the two catalogues hold the same keys."""
import unittest

from analisi import custom_fit, global_custom_fit, i18n
from analisi.field_error import FieldError
from tests.test_conditional_fit import FRAME, GLOBAL, global_options, parameters, single


class TranslationTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_catalog_parity(self):
        english = {key for key in i18n._EN if key.startswith("conditional.")}
        italian = {key for key in i18n._IT if key.startswith("conditional.")}
        self.assertEqual(english, italian)

    def test_engine_messages_are_translated(self):
        from analisi.custom_equation_dialog import translate_error
        from analisi.custom_equations import compile_equation
        from analisi.global_custom_dialog import translate_error as translate_global
        messages = []
        for text, syntax, names in (("if(X=0,1,2)", "Conditional", []), ("if(X<0,1,2)", "Arithmetic", []),
                                    ("1+(X<0)", "Conditional", []), ("X and 1", "Conditional", []),
                                    ("if X", "Conditional", []), ("if(X<0,1)", "Conditional", []),
                                    ("if(X<0,1,2", "Conditional", []), ("if(X,1,2)", "Conditional", []),
                                    ("if(X+1", "Conditional", []), ("if(0<X<1,1,2)", "Conditional", []),
                                    ("if+X", "Conditional", ["if"]), ("X", "Python", [])):
            with self.assertRaises(FieldError) as caught:
                compile_equation(text, names, syntax=syntax)
            messages.append(str(caught.exception))
        for call in (lambda: custom_fit.check_options(FRAME, single(Parameters=parameters(threshold_fixed=False))),
                     lambda: custom_fit.check_options(FRAME, single(Equation="if(1/X>T,A+B*X,A+C*X)")),
                     lambda: global_custom_fit.check_options(GLOBAL, global_options(
                         Parameters=parameters(threshold_fixed=False, shared={"A", "T"}))),
                     lambda: global_custom_fit.check_options(GLOBAL, global_options(
                         Parameters=parameters(threshold_fixed=False, shared={"A"}))),
                     lambda: global_custom_fit.check_options(GLOBAL, global_options(
                         Equation="if(1/X>T,A+B*X,A+C*X)"))):
            with self.assertRaises(FieldError) as caught:
                call()
            messages.append(str(caught.exception))
        i18n.set_language("it")
        for message in messages:
            with self.subTest(message):
                for translate in (translate_error, translate_global):
                    translated = translate(message)
                    self.assertNotEqual(translated, message)
                    for english in ("Compare with", "need the Conditional", "is not a finite number",
                                    "appears in a condition", "Unexpected"):
                        self.assertNotIn(english, translated)


if __name__ == "__main__":
    unittest.main()
