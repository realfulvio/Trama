"""Conflicts of File → Update from file… decided row by row (analisi.source_link and Project.update_from_source):
the package case and its inverse, the two commands for all, decisions bound to row identities and checked before the
worksheet changes, Undo/Redo, save and reopen, a second update from the confirmed file, TSV, and a conflict past the
rows a preview draws. The Qt panel is tested in test_qt_source_link_conflicts.py."""
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from analisi import source_link as engine
from analisi.source_link import (CONFLICT, DELETED_CONFLICT, FILE, LOCAL, PROJECT, REMOVED_CONFLICT)
from analisi.worksheet_row_identity import row_tokens
from tests.test_source_link import _project, column, link_file, plan_for

DATA = Path(__file__).resolve().parent / "data" / "source_link" / "per_riga"
CASE = {"B": PROJECT, "D": PROJECT, "C": FILE, "E": FILE}
INVERSE = {"B": FILE, "D": FILE, "C": PROJECT, "E": PROJECT}


def key_of(plan, item):
    return plan.frame["ID"][item.row] if item.row >= 0 else plan.raw["ID"][item.position]


def decisions(plan, by_key):
    return {item.identity: by_key[key_of(plan, item)] for item in plan.conflict_items if key_of(plan, item) in by_key}


def rows_of(project, title):
    return project.tables[title].raw[["ID", "Y"]].values.tolist()


def expected(name):
    return pd.read_csv(DATA / name).values.tolist()


class RowByRowConflictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "dati.csv"

    def edited(self, suffix=".csv"):
        """The package case: import iniziale linked by ID, B 21, C 31, D 41, E deleted, then aggiornato on disk."""
        self.path = self.folder / f"dati{suffix}"
        self.write("iniziale.csv")
        project, title = link_file(self.path)
        ids = column(project, title, "ID")
        for key, value in (("B", "21"), ("C", "31"), ("D", "41")):
            project.edit_cell(title, ids.index(key), 1, value)
        project.delete_rows(title, [ids.index("E")])
        self.write("aggiornato.csv")
        return project, title

    def write(self, name):
        text = (DATA / name).read_text(encoding="utf-8")
        if self.path.suffix == ".tsv":
            text = text.replace(",", "\t")
        self.path.write_text(text, encoding="utf-8", newline="")

    def test_four_conflicts_of_three_kinds_by_identity(self):
        project, title = self.edited()
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        kinds = {key_of(plan, item): item.kind for item in plan.conflict_items}
        self.assertEqual(kinds, {"E": DELETED_CONFLICT, "C": CONFLICT, "B": CONFLICT, "D": REMOVED_CONFLICT})
        self.assertEqual(plan.conflicts, 4)
        raw = project.tables[title].raw
        for item in plan.conflict_items:  # A decision names the worksheet row identity, never a line of a view.
            if item.position >= 0:
                self.assertEqual(item.identity, row_tokens(raw, [item.position])[0])
        self.assertEqual(len({item.identity for item in plan.conflict_items}), 4)

    def test_package_case_and_its_inverse(self):
        for by_key, name in ((CASE, "atteso.csv"), (INVERSE, "atteso-inverso.csv")):
            with self.subTest(expected=name):
                project, title = self.edited()
                plan = plan_for(project, title)
                project.update_from_source(title, plan, decisions=decisions(plan, by_key))
                self.assertEqual(rows_of(project, title), expected(name))

    def test_the_commands_for_all(self):
        for choice, rows in ((PROJECT, [["C", 31], ["A", 10], ["B", 21], ["F", 60], ["G", 75], ["D", 41]]),
                             (FILE, [["E", 55], ["C", 32], ["A", 10], ["B", 24], ["F", 60], ["G", 75]])):
            with self.subTest(choice=choice):
                project, title = self.edited()
                plan = plan_for(project, title)
                every = {item.identity: choice for item in plan.conflict_items}
                self.assertEqual(engine.decisions_for(plan, choice=choice), every)
                project.update_from_source(title, plan, choice=choice)
                self.assertEqual(rows_of(project, title), rows)

    def test_missing_or_foreign_decisions_change_nothing(self):
        project, title = self.edited()
        before = project.tables[title].raw
        plan = plan_for(project, title)
        partial = decisions(plan, {"B": PROJECT, "C": FILE, "E": FILE})
        problem = engine.can_apply(plan, decisions=partial)
        self.assertEqual(str(problem), "1 conflict(s) still need a decision: keep the project or use the file.")
        with self.assertRaisesRegex(ValueError, "1 conflict"):
            project.update_from_source(title, plan, decisions=partial)
        for foreign in ({**partial, "base:99": FILE}, {**decisions(plan, CASE), next(iter(partial)): "both"}):
            with self.assertRaisesRegex(ValueError, "do not match this preview"):
                project.update_from_source(title, plan, decisions=foreign)
        self.assertIs(project.tables[title].raw, before)
        # A decision made in another preview does not travel: the plan of a new reading has its own conflicts.
        other = plan_for(project, title)
        self.assertIsNone(engine.can_apply(other, decisions=decisions(plan, CASE)))  # Same rows, same identities.
        self.write("iniziale.csv")
        calm = plan_for(project, title)
        self.assertEqual(calm.conflict_items, [])
        past = decisions(plan, CASE)
        self.assertIn("do not match this preview", str(engine.can_apply(calm, decisions=past)))
        with self.assertRaisesRegex(ValueError, "do not match this preview"):
            project.update_from_source(title, calm, decisions=past)

    def test_explicit_replacement_does_not_read_conflict_decisions(self):
        project, title = self.edited()
        plan = plan_for(project, title)
        self.assertEqual(plan.conflicts, 4)
        self.assertIsNone(engine.can_apply(plan, replace_rows=True))
        project.update_from_source(title, plan, replace_rows=True)
        self.assertEqual(rows_of(project, title), expected("aggiornato.csv"))

    def test_undo_redo_save_reopen_and_a_second_update(self):
        project, title = self.edited()
        before = rows_of(project, title)
        plan = plan_for(project, title)
        project.update_from_source(title, plan, decisions=decisions(plan, CASE))
        after = rows_of(project, title)
        self.assertEqual(after, expected("atteso.csv"))
        project.undo()
        self.assertEqual(rows_of(project, title), before)
        project.undo(redo=True)
        self.assertEqual(rows_of(project, title), after)
        saved = self.folder / "conflitti.alab"
        project.save(saved)
        reopened = _project()
        reopened.load(saved)
        self.assertEqual(rows_of(reopened, title), after)
        again = plan_for(reopened, title)  # The file just confirmed: B keeps the project edit, D is a project row.
        self.assertEqual(again.conflict_items, [])
        self.assertEqual(again.count(LOCAL), 1)
        self.assertEqual([reopened.tables[title].raw["ID"][row] for row in again.project_rows], ["D"])
        self.assertIsNone(engine.can_apply(again))
        reopened.update_from_source(title, again)
        self.assertEqual(rows_of(reopened, title), after)

    def test_tsv(self):
        project, title = self.edited(".tsv")
        self.assertEqual(project.tables[title].source_link.delimiter, "\t")
        plan = plan_for(project, title)
        project.update_from_source(title, plan, decisions=decisions(plan, INVERSE))
        self.assertEqual(rows_of(project, title), expected("atteso-inverso.csv"))

    def test_exclusions_and_identities_stay_with_the_rows_that_remain(self):
        project, title = self.edited()
        ids = column(project, title, "ID")
        project.toggle_exclusion(title, [(ids.index("B"), 1), (ids.index("D"), 1)])
        tokens = dict(zip(ids, row_tokens(project.tables[title].raw, range(len(ids)))))
        plan = plan_for(project, title)
        project.update_from_source(title, plan, decisions=decisions(plan, CASE))
        ids = column(project, title, "ID")
        self.assertEqual(project.tables[title].excluded, {(ids.index("B"), 1), (ids.index("D"), 1)})
        now = dict(zip(ids, row_tokens(project.tables[title].raw, range(len(ids)))))
        for key in ("A", "B", "C", "D"):
            self.assertEqual(now[key], tokens[key])
        self.assertTrue(now["E"].startswith("base:"))  # Restored with the identity it was confirmed with.

    def test_a_conflict_past_the_rows_a_preview_draws(self):
        count = 1_200
        lines = ["ID,Y"] + [f"K{row:04d},{row}" for row in range(count)]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        project, title = link_file(self.path)
        raw = project.tables[title].raw.copy()
        raw["Y"] = raw["Y"] + 1000  # Every row edited in the project…
        project.edit(title, "Edit", lambda dataset: setattr(dataset, "raw", raw))
        self.path.write_text("\n".join(["ID,Y"] + [f"K{row:04d},{row + 5}" for row in range(count)]) + "\n",
                             encoding="utf-8")  # …and in the file.
        plan = plan_for(project, title)
        self.assertEqual(len(plan.conflict_items), count)
        last = plan.conflict_items[-1]
        chosen = {item.identity: PROJECT for item in plan.conflict_items[:-1]}
        self.assertIsNotNone(engine.can_apply(plan, decisions=chosen))
        chosen[last.identity] = FILE
        project.update_from_source(title, plan, decisions=chosen)
        values = column(project, title, "Y")
        self.assertEqual(values[-1], count - 1 + 5)
        self.assertEqual(values[0], 1000)


if __name__ == "__main__":
    unittest.main()
