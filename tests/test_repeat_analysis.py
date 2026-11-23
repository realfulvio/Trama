"""Analysis → Repeat analysis on other sheets…: the engine (plan, staging, calculation)."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
from unittest import TestCase
from uuid import uuid4

import pandas as pd

from analisi.analysis_chain import ChainCancelled, ResultSource
from analisi.data import Dataset, load_project, project_bytes, save_project
from analisi.graph_shapes import SHAPES
from analisi.repeat_analysis import (CONTRACTS, RepeatError, calculate_repeat, describe_repeat, plan_repeat,
                                     project_state, propose_columns, stage_repeat, target_problems)
from analisi.workbench import analyse

PARENT, CHILD = str(uuid4()), str(uuid4())
LOT_B = {"X": "Tempo", "Y": "Segnale"}
LOT_C = {"X": "Concentrazione", "Y": "Risposta"}


def lots():
    base = Dataset(pd.DataFrame({"X": [0., 1., 4.], "Y": [1., 2., 5.]}), analyses=[
        ("Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"}),
        ("Linear regression", {"X": "X", "Y": "Y"}),
    ], analysis_ids={0: PARENT, 1: CHILD}, analysis_sources={1: ResultSource(PARENT, "Transformed")})
    return {"Original": base,
            "Lot B": Dataset(pd.DataFrame({"Tempo": [0., 1., 4.], "Segnale": [1., 3., 9.]})),
            "Lot C": Dataset(pd.DataFrame({"Concentrazione": [0., 1., 4.], "Risposta": [4., 9., 24.]}))}


def slope(dataset, slot, inputs=None):
    """Calculate a staged chain the way the windows do and read the fitted slope of ``slot``."""
    results = {}
    for index in range(slot + 1):
        method, options = dataset.analyses[index]
        source = dataset.analysis_sources.get(index)
        if source is None:
            frame = (inputs if inputs is not None else dataset.frame(mask_excluded=True))
        else:
            parent = next(i for i, uid in dataset.analysis_ids.items() if uid == source.analysis_id)
            from analisi.analysis_chain import result_frame
            frame = result_frame(results[parent], source.table)
        results[index] = analyse(method, frame, options)
    return results[slot].tables["Regression"].at["Slope", "Value"]


class AcceptanceTests(TestCase):
    def setUp(self):
        self.tables = lots()
        self.before = project_bytes(self.tables)

    def test_two_lots_receive_the_chain_with_their_own_slopes(self):
        plan = plan_repeat(self.tables, ("Original", 0), {"Lot B": LOT_B, "Lot C": LOT_C}, follow=True)
        staged = stage_repeat(self.tables, plan)
        self.assertEqual(project_bytes(self.tables), self.before)
        ids = {PARENT, CHILD}
        for title, expected in (("Lot B", 2.0), ("Lot C", 5.0)):
            dataset = staged[title]
            self.assertIsNot(dataset, self.tables[title])
            self.assertEqual(len(dataset.analyses), 2)
            parent, child = dataset.analysis_ids[0], dataset.analysis_ids[1]
            self.assertTrue({parent, child}.isdisjoint(ids))
            ids.update((parent, child))
            self.assertEqual(dataset.analysis_sources, {1: ResultSource(parent, "Transformed")})
            self.assertAlmostEqual(slope(dataset, 1), expected)
        self.assertEqual(staged["Lot B"].analyses[0][1]["Variables"], ["Tempo", "Segnale"])
        self.assertEqual(staged["Lot B"].analyses[1][1], {"X": "Tempo", "Y": "Segnale"})
        self.assertIs(staged["Original"], self.tables["Original"])

    def test_the_copy_follows_its_own_sheet(self):
        plan = plan_repeat(self.tables, ("Original", 0), {"Lot B": LOT_B, "Lot C": LOT_C}, follow=True)
        staged = stage_repeat(self.tables, plan)
        staged["Lot B"].raw.loc[1, "Segnale"] = 16.
        self.assertAlmostEqual(slope(staged["Lot B"], 1), 1.0)
        self.assertAlmostEqual(slope(staged["Lot C"], 1), 5.0)
        self.assertEqual(self.tables["Lot B"].raw.loc[1, "Segnale"], 3.)
        self.assertEqual(project_bytes(self.tables), self.before)

    def test_wrong_destination_name_changes_nothing(self):
        with self.assertRaises(RepeatError) as caught:
            plan_repeat(self.tables, ("Original", 0), {"Lot B": {"X": "Tempi", "Y": "Segnale"}}, follow=True)
        self.assertEqual(caught.exception.code, "missing-column")
        self.assertEqual(caught.exception.sheet, "Lot B")
        self.assertEqual(project_bytes(self.tables), self.before)

    def test_two_columns_on_one_variable_are_refused(self):
        with self.assertRaises(RepeatError) as caught:
            plan_repeat(self.tables, ("Original", 0), {"Lot B": {"X": "Tempo", "Y": "Tempo"}}, follow=True)
        self.assertEqual(caught.exception.code, "duplicate")
        self.assertEqual(len(caught.exception.problems), 2)
        self.assertEqual(project_bytes(self.tables), self.before)

    def test_cancelling_a_larger_batch_changes_nothing(self):
        tables = dict(self.tables)
        targets = {}
        for number in range(30):
            title = f"Lot {number}"
            tables[title] = Dataset(pd.DataFrame({"A": [0., 1., 4., 9.], "B": [1., 2., 3., 4.]}))
            targets[title] = {"X": "A", "Y": "B"}
        before = project_bytes(tables)
        plan = plan_repeat(tables, ("Original", 0), targets, follow=True)
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 25

        with self.assertRaises(ChainCancelled):
            stage_repeat(tables, plan, cancel=cancel)
        self.assertEqual(project_bytes(tables), before)
        staged = stage_repeat(tables, plan)
        event = threading.Event()
        seen = []

        def progress(done, total):
            seen.append(done)
            if done == 7:
                event.set()

        inputs = {title: staged[title].frame(mask_excluded=True) for title in targets}
        with self.assertRaises(ChainCancelled):
            calculate_repeat(staged, plan, inputs, cancel=event, progress=progress)
        self.assertEqual(seen[-1], 7)
        self.assertEqual(project_bytes(tables), before)

    def test_editing_the_copy_keeps_the_source(self):
        plan = plan_repeat(self.tables, ("Original", 0), {"Lot B": LOT_B}, follow=True)
        staged = stage_repeat(self.tables, plan)
        staged["Lot B"].analyses[0][1]["Operation"] = "Square"
        staged["Lot B"].analyses[1][1]["Y"] = "Tempo"
        self.assertEqual(self.tables["Original"].analyses[0][1]["Operation"], "Absolute value")
        self.assertEqual(self.tables["Original"].analyses[1][1], {"X": "X", "Y": "Y"})
        self.assertEqual(plan.recipe.steps[0].options["Operation"], "Absolute value")
        again = stage_repeat(self.tables, plan)
        self.assertEqual(again["Lot B"].analyses[0][1]["Operation"], "Absolute value")
        self.assertEqual(project_bytes(self.tables), self.before)

    def test_save_and_reopen_keeps_identities_producers_and_results(self):
        plan = plan_repeat(self.tables, ("Original", 0), {"Lot B": LOT_B, "Lot C": LOT_C}, follow=True)
        staged = stage_repeat(self.tables, plan)
        inputs = {title: staged[title].frame(mask_excluded=True) for title in ("Lot B", "Lot C")}
        calculated = calculate_repeat(staged, plan, inputs)
        self.assertAlmostEqual(calculated.results["Lot C", 1].tables["Regression"].at["Slope", "Value"], 5.)
        self.assertIsNotNone(calculated.results["Lot C", 1].figure)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "repeat.alab"
            save_project(path, staged)
            reopened = load_project(path)
        for title, expected in (("Lot B", 2.), ("Lot C", 5.)):
            self.assertEqual(reopened[title].analysis_ids, staged[title].analysis_ids)
            self.assertEqual(reopened[title].analysis_sources, staged[title].analysis_sources)
            self.assertEqual(reopened[title].analyses, staged[title].analyses)
            self.assertAlmostEqual(slope(reopened[title], 1), expected)
            method, options = reopened[title].analyses[0]
            result = analyse(method, reopened[title].frame(), options)
            self.assertIsNotNone(analyse(reopened[title].analyses[1][0],
                                         result.tables["Transformed"], reopened[title].analyses[1][1]).figure)
        self.assertEqual(reopened["Original"].analysis_ids, {0: PARENT, 1: CHILD})


class RecipeTests(TestCase):
    def test_contract_registry_lists_the_five_methods(self):
        self.assertEqual(set(CONTRACTS), {"Transform", "Normalize", "Descriptive statistics", "Linear regression",
                                          "Nonlinear regression"})
        from analisi.workbench import METHODS, MULTIPLE, OPTIONAL, OPTIONAL_MULTIPLE
        for method, contract in CONTRACTS.items():
            declared = {name for name, kind in METHODS[method].items()
                        if kind is None or kind in (OPTIONAL, MULTIPLE, OPTIONAL_MULTIPLE)}
            self.assertEqual({item.name for item in contract.fields}, declared, method)

    def test_follow_false_copies_only_the_selected_recipe(self):
        tables = lots()
        recipe = describe_repeat(tables, ("Original", 0))
        self.assertEqual(len(recipe.steps), 1)
        self.assertEqual(recipe.columns, ("X", "Y"))
        staged = stage_repeat(tables, plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B}))
        self.assertEqual(len(staged["Lot B"].analyses), 1)
        self.assertEqual(staged["Lot B"].analysis_sources, {})

    def test_a_child_cannot_be_the_origin(self):
        with self.assertRaises(RepeatError) as caught:
            describe_repeat(lots(), ("Original", 1))
        self.assertEqual(caught.exception.code, "reads-result")

    def test_unsupported_origin_is_explained(self):
        tables = lots()
        tables["Original"].analyses.append(("t-test", {"Response": "Y", "Design": "Welch"}))
        with self.assertRaises(RepeatError) as caught:
            describe_repeat(tables, ("Original", 2))
        self.assertEqual(caught.exception.code, "unsupported")
        tables["Original"].analyses.append(("Linear regression", {"X": "X", "Y": "Y", "Legacy import notes": "x"}))
        with self.assertRaises(RepeatError) as caught:
            describe_repeat(tables, ("Original", 3))
        self.assertEqual(caught.exception.code, "external")
        tables["Original"].analyses.append(("Linear regression", {"X": "X", "Y": "Missing"}))
        with self.assertRaises(RepeatError) as caught:
            describe_repeat(tables, ("Original", 4))
        self.assertEqual(caught.exception.code, "missing-column")

    def test_passthrough_chain_is_renamed_at_every_step(self):
        ids = [str(uuid4()) for _ in range(4)]
        source = Dataset(pd.DataFrame({"Dose": [1., 2., 3., 4.], "Peso": [2., 4., 7., 8.]}), analyses=[
            ("Transform", {"Variables": ["Dose", "Peso"], "Operation": "Square root"}),
            ("Normalize", {"Variables": ["Peso", "Dose"], "Method": "Subtract first value"}),
            ("Linear regression", {"X": "Dose", "Y": "Peso"}),
            ("Descriptive statistics", {"Variables": ["Value"]}),
        ], analysis_ids=dict(enumerate(ids)), analysis_sources={
            1: ResultSource(ids[0], "Transformed"), 2: ResultSource(ids[1], "Normalized"),
            3: ResultSource(ids[2], "Regression")})
        target = Dataset(pd.DataFrame({"D": [1., 4., 9., 16.], "P": [4., 9., 25., 36.]}))
        tables = {"S": source, "T": target}
        plan = plan_repeat(tables, ("S", 0), {"T": {"Dose": "D", "Peso": "P"}}, follow=True)
        self.assertEqual([step.method for step in plan.recipe.steps],
                         ["Transform", "Normalize", "Linear regression", "Descriptive statistics"])
        staged = stage_repeat(tables, plan)["T"]
        self.assertEqual(staged.analyses[1][1]["Variables"], ["P", "D"])
        self.assertEqual(staged.analyses[2][1], {"X": "D", "Y": "P"})
        self.assertEqual(staged.analyses[3][1], {"Variables": ["Value"]})  # fixed output column, unchanged
        calculated = calculate_repeat({"T": staged}, plan, {"T": staged.frame()})
        self.assertAlmostEqual(calculated.results["T", 2].tables["Regression"].at["Slope", "Value"], 1.4)
        requirement = {item.column: item for item in plan.recipe.required}
        self.assertEqual(requirement["Dose"].fields, ((0, "Variables"), (1, "Variables"), (2, "X")))

    def test_incompatible_descendants_are_skipped_with_a_reason(self):
        ids = [str(uuid4()) for _ in range(5)]
        source = Dataset(pd.DataFrame({"X": [1., 2., 3.], "Y": [2., 4., 7.], "W": [1., 1., 2.]}), analyses=[
            ("Transform", {"Variables": ["X"], "Operation": "Square"}),
            ("Linear regression", {"X": "X", "Y": "W"}),          # W is not in Transformed
            ("t-test", {"Response": "X", "Design": "One-sample"}),
            ("Descriptive statistics", {"Variables": ["X"]}),     # reads a table Transform never makes
            ("Descriptive statistics", {"Variables": ["Value"]}),  # below a skipped analysis
        ], analysis_ids=dict(enumerate(ids)), analysis_sources={
            1: ResultSource(ids[0], "Transformed"), 2: ResultSource(ids[0], "Transformed"),
            3: ResultSource(ids[0], "Other"), 4: ResultSource(ids[1], "Regression")})
        recipe = describe_repeat({"S": source}, ("S", 0), follow=True)
        self.assertEqual(len(recipe.steps), 1)
        reasons = {item.slot: item.code for item in recipe.skipped}
        self.assertEqual(reasons, {1: "output", 2: "unsupported", 3: "output", 4: "parent-skipped"})

    def test_literals_and_options_that_look_like_columns_stay(self):
        tables = lots()
        tables["Original"].analyses.append(("Linear regression", {"X": "X", "Y": "Y", "Note": "X",
                                                                  "Fit X minimum": ""}))
        tables["Original"].analysis_labels = {2: "Y"}
        tables["Original"].graph_styles = {2: {"title": "X", "xlabel": "X", "ylabel": "Y",
                                               "series": {"scatter:1:": {"color": "#ff0000"}},
                                               SHAPES: [{"kind": "line"}]}}
        plan = plan_repeat(tables, ("Original", 2), {"Lot B": LOT_B})
        dataset = stage_repeat(tables, plan)["Lot B"]
        self.assertEqual(dataset.analyses[0][1], {"X": "Tempo", "Y": "Segnale", "Note": "X", "Fit X minimum": ""})
        self.assertEqual(dataset.analysis_labels, {0: "Y"})
        style = dataset.graph_styles[0]
        self.assertEqual((style["title"], style["xlabel"], style["ylabel"]), ("X", "X", "Y"))
        self.assertNotIn(SHAPES, style)

    def test_optional_groups_and_nonlinear_series(self):
        frame = pd.DataFrame({"Dose": [0., 1., 2., 3., 4., 5.] * 2, "R1": [1., 1.5, 2.3, 3.4, 5.1, 7.6] * 2,
                              "Lab": ["a"] * 6 + ["b"] * 6})
        other = pd.DataFrame({"t": [0., 1., 2., 3., 4., 5.] * 2, "y": [2., 2.9, 4.4, 6.8, 10.1, 15.3] * 2,
                              "Site": ["n"] * 6 + ["s"] * 6, "Lab": ["x"] * 12})
        uid = str(uuid4())
        options = {"X": "Dose", "Y columns": ["R1"], "Grouping variables": ["Lab"], "Model": "Exponential growth",
                   "SD column": None}
        source = Dataset(frame, analyses=[("Nonlinear regression", options)], analysis_ids={0: uid},
                         graph_styles={0: {"series": {"scatter:1:a": {"color": "#123456"},
                                                      "scatter:2:R1": {"color": "#654321"}}}})
        tables = {"S": source, "T": Dataset(other)}
        recipe = describe_repeat(tables, ("S", 0))
        self.assertEqual(recipe.columns, ("Dose", "R1", "Lab"))
        self.assertEqual(propose_columns(recipe, tables["T"]), {"Lab": "Lab"})
        self.assertFalse(next(item for item in recipe.required if item.column == "Lab").numeric)
        plan = plan_repeat(tables, ("S", 0), {"T": {"Dose": "t", "R1": "y", "Lab": "Site"}})
        staged = stage_repeat(tables, plan)
        self.assertEqual(staged["T"].analyses[0][1]["Grouping variables"], ["Site"])
        self.assertIsNone(staged["T"].analyses[0][1]["SD column"])
        self.assertIn("scatter:2:y", staged["T"].graph_styles[0]["series"])
        calculated = calculate_repeat(staged, plan, {"T": staged["T"].frame()})
        # One fit per group: the sheet names carry the group, so no downstream analysis can rely on them.
        self.assertIn("Parameters: n", calculated.results["T", 0].tables)
        # Series the new graph does not draw are left out of the reused format.
        kept = staged["T"].graph_styles.get(0, {}).get("series", {})
        self.assertNotIn("scatter:1:a", kept)

    def test_not_numeric_unknown_and_incomplete_choices(self):
        tables = lots()
        tables["Lot B"].raw["Nota"] = ["a", "b", "c"]
        recipe = describe_repeat(tables, ("Original", 0), follow=True)
        codes = [problem.code for problem in target_problems(tables, recipe, "Lot B", {"X": "Nota"})]
        self.assertEqual(sorted(codes), ["not-numeric", "unmapped"])
        codes = [problem.code for problem in target_problems(tables, recipe, "Lot B",
                                                             {"X": "Tempo", "Y": "Segnale", "Z": "Tempo"})]
        self.assertEqual(codes, ["unknown-column"])
        self.assertEqual([p.code for p in target_problems(tables, recipe, "Original", LOT_B)], ["source-sheet"])
        self.assertEqual([p.code for p in target_problems(tables, recipe, "Nope", LOT_B)], ["unknown-sheet"])
        with self.assertRaises(RepeatError) as caught:
            plan_repeat(tables, ("Original", 0), {})
        self.assertEqual(caught.exception.code, "no-targets")

    def test_formula_column_and_exclusions_of_the_destination(self):
        tables = lots()
        target = tables["Lot B"] = Dataset(pd.DataFrame({"Tempo": [0., 1., 4., 5.], "Segnale": [1., 3., 9., 30.]}))
        target.formulas = {"Doppio": "=2*Segnale"}
        target.excluded = {(3, 1)}
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": {"X": "Tempo", "Y": "Doppio"}}, follow=True)
        staged = stage_repeat(tables, plan)["Lot B"]
        self.assertEqual(staged.formulas, {"Doppio": "=2*Segnale"})
        self.assertEqual(staged.excluded, {(3, 1)})
        # The excluded cell leaves no value in the formula column: the line uses the first three rows only.
        self.assertAlmostEqual(slope(staged, 1), 4.0)

    def test_repeated_names_follow_the_trama_convention(self):
        tables = lots()
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B}, follow=True)
        once = stage_repeat(tables, plan)
        self.assertEqual(once["Lot B"].analysis_labels, {})
        tables["Lot B"] = once["Lot B"]
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B}, follow=True)
        twice = stage_repeat(tables, plan)["Lot B"]
        self.assertEqual(twice.analysis_labels, {2: "Transform of Lot B (2)", 3: "Linear regression of Transformed (2)"})
        self.assertEqual(len(twice.analyses), 4)
        self.assertEqual(twice.analysis_sources[3].analysis_id, twice.analysis_ids[2])

    def test_existing_content_of_the_destination_is_preserved(self):
        tables = lots()
        own = str(uuid4())
        target = tables["Lot C"]
        target.analyses = [("Descriptive statistics", {"Variables": ["Risposta"]})]
        target.analysis_ids = {0: own}
        target.graph_styles = {0: {"title": "Mine"}}
        target.result_backgrounds = {0: {"Summary": {(0, 0): "#ffff00"}}}
        target.cell_backgrounds = {(0, "Risposta"): "#00ff00"}
        tables["Original"].result_backgrounds = {1: {"Regression": {(0, 0): "#ff0000"}}}
        plan = plan_repeat(tables, ("Original", 0), {"Lot C": LOT_C}, follow=True)
        staged = stage_repeat(tables, plan)["Lot C"]
        self.assertEqual(staged.analyses[0], ("Descriptive statistics", {"Variables": ["Risposta"]}))
        self.assertEqual(staged.analysis_ids[0], own)
        self.assertEqual(staged.graph_styles, {0: {"title": "Mine"}})
        self.assertEqual(staged.result_backgrounds, {0: {"Summary": {(0, 0): "#ffff00"}}})
        self.assertEqual(staged.cell_backgrounds, {(0, "Risposta"): "#00ff00"})
        self.assertEqual(staged.analysis_sources, {2: ResultSource(staged.analysis_ids[1], "Transformed")})

    def test_read_only_and_budget_destinations(self):
        tables = lots()
        tables["Archive"] = Dataset(pd.DataFrame({"X": [1.], "Y": [2.]}),
                                    analyses=[("Imported saved results", {})])
        tables["Full"] = Dataset(pd.DataFrame({"X": [1., 2.], "Y": [2., 3.]}),
                                 analyses=[("Descriptive statistics", {"Variables": ["X"]})] * 256)
        recipe = describe_repeat(tables, ("Original", 0))
        self.assertEqual([p.code for p in target_problems(tables, recipe, "Archive", {"X": "X", "Y": "Y"})],
                         ["read-only"])
        self.assertEqual([p.code for p in target_problems(tables, recipe, "Full", {"X": "X", "Y": "Y"})],
                         ["budget"])

    def test_a_method_that_cannot_be_calculated_names_sheet_and_method(self):
        tables = lots()
        tables["Original"].analyses[0] = ("Transform", {"Variables": ["X", "Y"], "Operation": "Log10"})
        tables["Lot B"].raw.loc[0, "Tempo"] = -1.
        tables["Original"].raw.loc[0, "X"] = 1.
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B, "Lot C": LOT_C}, follow=True)
        staged = stage_repeat(tables, plan)
        before = project_bytes(tables)
        with self.assertRaises(RepeatError) as caught:
            calculate_repeat(staged, plan, {title: staged[title].frame() for title in ("Lot B", "Lot C")})
        error = caught.exception
        self.assertEqual((error.code, error.sheet, error.method), ("calculation", "Lot B", "Transform"))
        self.assertIn("domain", error.detail["reason"])
        self.assertEqual(project_bytes(tables), before)

    def test_staging_refuses_a_project_that_changed(self):
        tables = lots()
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B}, follow=True)
        tables["Original"].analyses[0][1]["Operation"] = "Square"
        with self.assertRaises(RepeatError) as caught:
            stage_repeat(tables, plan)
        self.assertEqual(caught.exception.code, "changed")
        tables = lots()
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B}, follow=True)
        tables["Lot B"].analyses.append(("Descriptive statistics", {"Variables": ["Tempo"]}))
        with self.assertRaises(RepeatError):
            stage_repeat(tables, plan)

    def test_project_state_sees_edits(self):
        tables = lots()
        state = project_state(tables, ["Lot B", "Original"])
        self.assertEqual(state, project_state(tables, ["Original", "Lot B"]))
        tables["Lot B"].raw.loc[1, "Segnale"] = 16.
        self.assertNotEqual(state, project_state(tables, ["Lot B", "Original"]))
        state = project_state(tables, ["Lot B"])
        tables["Lot B"].excluded.add((0, 0))
        self.assertNotEqual(state, project_state(tables, ["Lot B"]))

    def test_inputs_are_never_changed(self):
        tables = lots()
        snapshot = deepcopy({title: (dataset.analyses, dataset.analysis_ids, dataset.analysis_sources,
                                     dataset.graph_styles, dataset.raw.copy()) for title, dataset in tables.items()})
        plan = plan_repeat(tables, ("Original", 0), {"Lot B": LOT_B, "Lot C": LOT_C}, follow=True)
        staged = stage_repeat(tables, plan)
        calculate_repeat(staged, plan, {title: staged[title].frame() for title in ("Lot B", "Lot C")})
        for title, (analyses, ids, sources, styles, raw) in snapshot.items():
            dataset = tables[title]
            self.assertEqual(dataset.analyses, analyses)
            self.assertEqual(dataset.analysis_ids, ids)
            self.assertEqual(dataset.analysis_sources, sources)
            self.assertEqual(dataset.graph_styles, styles)
            pd.testing.assert_frame_equal(dataset.raw, raw)
