"""Classic Tk dialog: no planned-contrast editor (that lives in the Qt window), but a saved recipe keeps them."""
import unittest

from analisi import anova_planned_contrasts as planned
from tests.test_anova_terms_dialog import FACTORS, DialogCase


class ClassicDialogTests(DialogCase):
    def test_no_planned_contrast_fields_and_legacy_recipe_stays_free_of_the_keys(self):
        def action(dialog, seen):
            seen["fields"] = set(dialog.controls)
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action)
        self.assertTrue(seen["ok"])
        self.assertFalse(seen["fields"] & set(planned.KEYS))
        self.assertFalse(set(seen["options"]) & set(planned.KEYS))

    def test_saved_planned_contrasts_survive_the_classic_dialog(self):
        contrasts = [{"name": "A1 − A0", "weights": [{"levels": ["A1"], "coefficient": 1},
                                                    {"levels": ["A0"], "coefficient": -1}]}]
        current = {"Response": "Response", "Factors": FACTORS, "Interaction order": 2,
                   planned.FACTORS: ["A dose"], planned.CONTRASTS: contrasts,
                   planned.CORRECTION: "Bonferroni", planned.ALPHA: 0.1}

        def action(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action, current=current, factors=None)
        self.assertTrue(seen["ok"])
        for key in planned.KEYS:
            self.assertEqual(seen["options"][key], current[key])
        self.assertIsNot(seen["options"][planned.CONTRASTS], contrasts)


if __name__ == "__main__":
    unittest.main()
