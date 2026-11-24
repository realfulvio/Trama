"""Category edits check the live and saved result inputs that use the changed levels."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from analisi import worksheet_join as join
from analisi.analysis_chain import ResultSource
from analisi.category_levels import LevelEditDraft, LevelEditError
from analisi.select_transform import FILTERS, SELECT_TRANSFORM
from trama_qt.project import Project, compute


def add_run(project, title, method, options, *, source=None):
    run = project.candidate(title, method, options, source=source)
    result = compute(run, project.input_frame(run), join_data=project.join_data(run))
    project.add_result(run, result)
    return run


def refresh(project, runs):
    job = project.plan_refresh(runs)
    return project.apply_refresh(job, Project.run_refresh(job))


def rename(project, title, column, old, new):
    draft = LevelEditDraft(project.tables[title], column)
    draft.apply_mapping({old: new})
    return draft.validate()


def add_tables(project):
    left = pd.DataFrame({
        "ID": ["Ctrl", "A", "B", "Ctrl", "A", "B"],
        "Visit": [1, 1, 1, 2, 2, 2],
        "Y": [1.0, 2.0, 3.0, 1.4, 2.4, 3.8],
        "Group": ["Left C", "Left A", "Left B", "Left C", "Left A", "Left B"],
    })
    right = pd.DataFrame({
        "ID": left["ID"],
        "Visit": left["Visit"],
        "Group": ["Right C", "Right A", "Right B", "Right C", "Right A", "Right B"],
    })
    return project.add_tables({"Left": left, "Right": right})


def add_join(project, left, right, *, source=None):
    return add_run(project, left, join.METHOD, {
        join.RIGHT_SHEET: right, join.LEFT_KEYS: ["ID", "Visit"], join.RIGHT_KEYS: ["ID", "Visit"],
        join.JOIN_TYPE: join.LEFT,
    }, source=source)


def add_dunnett(project, title, linked_join, group, control):
    return add_run(project, title, "One-way ANOVA", {
        "Response": "Y", "Group": group, "Method": "Ordinary", "Post-hoc": "Dunnett", "Control group": control,
    }, source=ResultSource(linked_join.uid, join.JOINED))


def reopen(project):
    with TemporaryDirectory() as folder:
        path = Path(folder) / "joined.alab"
        project.save(path)
        reopened = Project()
        reopened.load(path)
    return reopened


class CategoryLevelDependencyTests(unittest.TestCase):
    def test_right_key_does_not_supply_the_left_join_output_key(self):
        project = Project()
        left, right = add_tables(project)
        linked_join = add_join(project, left, right)
        analysis = add_dunnett(project, left, linked_join, "ID", "Ctrl")
        previous = analysis.result.tables
        plan = rename(project, right, "ID", "Ctrl", "Placebo")

        self.assertEqual(project.category_level_blockers(right, plan), [])
        self.assertEqual(refresh(project, project.apply_category_levels(right, plan)), [])
        self.assertEqual(linked_join.result.tables[join.JOINED]["ID"].tolist(), ["Ctrl", "A", "B", "Ctrl", "A", "B"])
        for table, before in previous.items():
            pd.testing.assert_frame_equal(analysis.result.tables[table], before)

    def test_right_payload_blocker_survives_reopen_with_left_result_unloaded(self):
        project = Project()
        left, right = add_tables(project)
        selected = add_run(project, left, SELECT_TRANSFORM, {})
        linked_join = add_join(project, left, right, source=ResultSource(selected.uid, "Selected data"))
        add_dunnett(project, left, linked_join, "Group [right]", "Right C")
        warm = project.category_level_blockers(right, rename(project, right, "Group", "Right C", "Placebo"))
        self.assertEqual(len(warm), 1)
        self.assertEqual(warm[0].levels, ("Right C",))

        reopened = reopen(project)
        self.assertTrue(all(run.result is None for run in reopened.runs))
        plan = rename(reopened, right, "Group", "Right C", "Placebo")
        self.assertEqual(reopened.category_level_blockers(right, plan), warm)
        with self.assertRaises(LevelEditError):
            reopened.apply_category_levels(right, plan)
        self.assertEqual(reopened.tables[right].raw["Group"].tolist(),
                         ["Right C", "Right A", "Right B", "Right C", "Right A", "Right B"])
        self.assertFalse(reopened.dirty)

    def test_right_payload_blocker_survives_reopen_with_nested_join(self):
        project = Project()
        left, right = add_tables(project)
        aux = project.tables[left].raw[["ID", "Visit"]].assign(Extra="Label")
        third, = project.add_tables({"Auxiliary": aux})
        intermediate = add_join(project, left, third)
        linked_join = add_join(project, left, right, source=ResultSource(intermediate.uid, join.JOINED))
        add_dunnett(project, left, linked_join, "Group [right]", "Right C")

        reopened = reopen(project)
        plan = rename(reopened, right, "Group", "Right C", "Placebo")
        blockers = reopened.category_level_blockers(right, plan)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].levels, ("Right C",))

    def test_uncached_result_schema_is_needed_only_for_a_potential_reference(self):
        project = Project()
        left, right = add_tables(project)
        pruned = add_run(project, left, "Prune rows", {
            "X": "Visit", "Method": "Keep rows within an X range", "X minimum (blank = no limit)": "1",
        })
        linked_join = add_join(project, left, right, source=ResultSource(pruned.uid, "Pruned data"))
        add_dunnett(project, left, linked_join, "Group [right]", "Right C")

        reopened = reopen(project)
        unreferenced = rename(reopened, right, "Group", "Right A", "Other")
        self.assertEqual(reopened.category_level_blockers(right, unreferenced), [])
        reopened.apply_category_levels(right, unreferenced)
        referenced = rename(reopened, right, "Group", "Right C", "Placebo")
        with self.assertRaises(LevelEditError) as error:
            reopened.apply_category_levels(right, referenced)
        self.assertEqual(error.exception.code, "join_source_unavailable")
        self.assertEqual(reopened.tables[right].raw["Group"].tolist(),
                         ["Right C", "Other", "Right B", "Right C", "Other", "Right B"])

        self.assertEqual(refresh(reopened, [reopened.runs[0]]), [])
        blockers = reopened.category_level_blockers(right, referenced)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].levels, ("Right C",))

    def test_saved_text_filter_blocks_removing_its_literal(self):
        project = Project()
        title, = project.add_tables({"Source": pd.DataFrame({
            "Group": ["C", "C", "T", "T"], "Y": [1.0, 1.7, 2.6, 3.0],
        })})
        run = add_run(project, title, SELECT_TRANSFORM, {
            FILTERS: [{"column": "Group", "operator": "=", "target": "Text", "value": "C"}],
        })
        plan = rename(project, title, "Group", "C", "Placebo")
        with self.assertRaises(LevelEditError):
            project.apply_category_levels(title, plan)
        self.assertEqual(run.result.tables["Selected data"]["Y"].tolist(), [1.0, 1.7])
        self.assertEqual(project.tables[title].raw["Group"].tolist(), ["C", "C", "T", "T"])

    def test_saved_grouped_t_test_order_blocks_removing_its_label(self):
        project = Project()
        title, = project.add_tables({"Source": pd.DataFrame({
            "Group": ["C", "C", "T", "T"], "Y": [1.0, 1.7, 2.6, 3.0],
        })})
        run = add_run(project, title, "t-test", {
            "Design": "Welch", "Response": "Y", "Group": "Group", "Group order": ["C", "T"],
        })
        plan = rename(project, title, "Group", "C", "Placebo")
        with self.assertRaises(LevelEditError):
            project.apply_category_levels(title, plan)
        self.assertEqual(run.options["Group order"], ["C", "T"])
        self.assertEqual(project.tables[title].raw["Group"].tolist(), ["C", "C", "T", "T"])
