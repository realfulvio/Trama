"""Tarone–Ware and Fleming–Harrington weights on the Kaplan–Meier path."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import resource
import tempfile
import threading
import time
import tracemalloc
import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.field_error import FieldError
from analisi.stats import survival_comparisons
from analisi.survival_input import EVENT_CODE, CENSOR_CODE
from analisi.weighted_logrank import (CHI2, CUSTOM, DETAIL, DETAIL_SHEET, EARLY, EMPTY_GROUP, GAMMA, GEHAN, GLOBAL,
                                      INTERMEDIATE, LATE, LOG_RANK, LOW_RANK, NEED_GROUPS, NO_EVENTS, PAIRS, RHO,
                                      TARONE, WEIGHTING, WeightedComparisonCancelled, contribute, fit_arrays,
                                      reference_record)
from analisi.workbench import analyse

HERE = Path(__file__).resolve().parent / "data" / "weighted-logrank"
KM = "Kaplan–Meier survival"
TARONE_CHI2 = 1.350941601454316
TARONE_P = 0.5089167658137421


def cohort():
    return pd.read_csv(HERE / "coorti.csv")


def _load(name, path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recipe(choice=TARONE, **extra):
    options = {"Time": "tempo", "Event": "evento", "Group": "gruppo", WEIGHTING: choice, DETAIL: True,
               "Pairwise correction": "Holm", "Pairwise scope": "All pairs"}
    options.update(extra)
    return options


class EngineTests(unittest.TestCase):
    def test_reference_cohort_matches_the_oracle_including_the_drawn_weights(self):
        result = analyse(KM, cohort(), recipe())
        record = reference_record(result)
        self.assertAlmostEqual(record["global_test"]["chi2"], TARONE_CHI2, delta=1e-12)
        self.assertAlmostEqual(record["global_test"]["p"], TARONE_P, delta=1e-12)
        late = fit_arrays(cohort().tempo, cohort().evento, cohort().gruppo, LATE)
        self.assertEqual(late["weight"][0], 0.0)
        plain = analyse(KM, cohort(), {"Time": "tempo", "Event": "evento", "Group": "gruppo"})
        self.assertNotIn(GLOBAL, plain.tables)
        for label, curve in result.tables.items():
            if label.startswith("Curve"):
                pd.testing.assert_series_equal(curve["Survival"], plain.tables[label]["Survival"])
        pd.testing.assert_frame_equal(result.tables["Number at risk"], plain.tables["Number at risk"])
        self.assertAlmostEqual(result.tables["Log-rank test"].at["Log-rank χ²", "Value"],
                               plain.tables["Log-rank test"].at["Log-rank χ²", "Value"])

    def test_zero_exponents_match_log_rank_and_gehan_matches_the_existing_test(self):
        frame = cohort()
        logrank = fit_arrays(frame.tempo, frame.evento, frame.gruppo, LOG_RANK)
        custom = fit_arrays(frame.tempo, frame.evento, frame.gruppo, CUSTOM, 0, 0)
        self.assertEqual(logrank["χ²"], custom["χ²"])
        np.testing.assert_array_equal(logrank["weight"], custom["weight"])
        np.testing.assert_array_equal(logrank["weight"], np.ones(len(logrank["weight"])))
        gehan = fit_arrays(frame.tempo, frame.evento, frame.gruppo, GEHAN)
        existing = survival_comparisons(frame, "tempo", "evento", "gruppo", gbw=True)["gbw"]["χ²"]
        self.assertAlmostEqual(gehan["χ²"], existing, places=12)

    def test_a_censored_subject_at_the_event_time_stays_at_risk(self):
        found = fit_arrays(cohort().tempo, cohort().evento, cohort().gruppo, LOG_RANK)
        self.assertEqual(found["at_risk"][0], 18)
        self.assertEqual(found["events"][0], 1)

    def test_a_group_with_only_censoring_still_enters_the_risk_sets(self):
        frame = cohort()
        frame.loc[frame.gruppo == "C", "evento"] = 0
        found = fit_arrays(frame.tempo, frame.evento, frame.gruppo, TARONE)
        self.assertTrue(found["available"])
        group = found["groups"].index("C")
        self.assertGreater(found["group_at_risk"][0, group], 0)
        self.assertEqual(found["observed"][:, group].sum(), 0)

    def test_everyone_censored_is_not_estimable(self):
        frame = cohort()
        frame["evento"] = 0
        found = fit_arrays(frame.tempo, frame.evento, frame.gruppo, TARONE)
        self.assertFalse(found["available"])
        self.assertEqual(found["note"], NO_EVENTS)

    def test_one_time_shared_by_everyone(self):
        groups = np.repeat(["A", "B", "C"], 4)
        found = fit_arrays(np.full(12, 5.0), [1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0], groups, TARONE)
        self.assertTrue(found["available"])
        self.assertEqual(found["at_risk"][0], 12)
        self.assertEqual(found["df"], 2)

    def test_rank_failure_is_explained(self):
        found = fit_arrays([1, 1, 0], [1, 1, 0], ["A", "A", "B"], TARONE)
        self.assertFalse(found["available"])
        self.assertEqual(found["note"], LOW_RANK)

    def test_two_of_three_pairs_rebuild_their_own_weights_and_their_own_holm_family(self):
        frame = cohort()
        full = analyse(KM, frame, recipe())
        selected = analyse(KM, frame, recipe(**{"Selected survival pairs": [["A", "B"], ["B", "C"]],
                                               "Pairwise scope": "Selected pairs"}))
        full_pairs, chosen = full.tables[PAIRS], selected.tables[PAIRS]
        self.assertEqual(list(chosen.index), ["A / B", "B / C"])
        self.assertNotIn("A / C", chosen.index)
        for name in ("A / B", "B / C"):
            self.assertAlmostEqual(chosen.at[name, "p"], full_pairs.at[name, "p"])
        values = chosen["p"].to_numpy(dtype=float)
        adjusted = np.empty(len(values))
        largest = 0.0
        for rank, index in enumerate(np.argsort(values)):
            largest = max(largest, (len(values) - rank) * values[index])
            adjusted[index] = min(1.0, largest)
        np.testing.assert_allclose(chosen["Adjusted p"], adjusted)
        detail = selected.tables[DETAIL_SHEET]
        pair = detail[detail["Comparison"] == "A / B"].drop_duplicates("Time")
        everyone = detail[detail["Comparison"] == "All groups"].drop_duplicates("Time")
        self.assertNotEqual(pair["At risk"].iloc[0], everyone["At risk"].iloc[0])

    def test_custom_event_code_exclusion_and_a_second_response(self):
        frame = cohort()
        frame["stato"] = frame.evento.map({1: "death", 0: "alive"})
        coded = analyse(KM, frame, recipe(**{"Event": "stato", EVENT_CODE: "death", CENSOR_CODE: "alive"}))
        self.assertAlmostEqual(coded.tables[GLOBAL].at[CHI2, "Value"], TARONE_CHI2, delta=1e-12)
        table = Dataset(frame.copy())
        column = list(frame.columns).index("gruppo")
        table.excluded.update((index, column) for index, group in enumerate(frame.gruppo) if group == "C")
        excluded = analyse(KM, table.frame(mask_excluded=True), recipe())
        only_ab = fit_arrays(frame.loc[frame.gruppo != "C", "tempo"], frame.loc[frame.gruppo != "C", "evento"],
                             frame.loc[frame.gruppo != "C", "gruppo"], TARONE)
        self.assertAlmostEqual(excluded.tables[GLOBAL].at[CHI2, "Value"], only_ab["χ²"])
        self.assertEqual(excluded.tables[GLOBAL].at["df", "Value"], 1)
        frame["altro"] = frame.evento
        both = analyse(KM, frame, {"Time": "tempo", "Event columns": ["evento", "altro"],
                                   "Grouping variables": ["gruppo"], WEIGHTING: EARLY, DETAIL: True})
        sheet = both.tables[GLOBAL]
        self.assertEqual(set(sheet["Response variable"]), {"evento", "altro"})
        self.assertIn("Response variable", both.tables[DETAIL_SHEET].columns)
        labels = [label for _times, _weights, label in __import__(
            "analisi.weighted_logrank", fromlist=["artist_weights"]).artist_weights(both.figure)]
        self.assertTrue(any("evento" in label for label in labels))
        self.assertTrue(any("altro" in label for label in labels))

    def test_missing_group_and_invalid_exponents_are_explained(self):
        with self.assertRaises(FieldError) as missing:
            analyse(KM, cohort(), recipe(**{"Selected survival pairs": [["A", "Z"]],
                                           "Pairwise scope": "Selected pairs"}))
        self.assertIn("observed groups", str(missing.exception))
        from matplotlib.figure import Figure
        figure = Figure()
        figure.add_subplot()
        sheets = contribute(cohort(), recipe(**{"Selected survival pairs": [["A", "Z"]],
                                               "Pairwise scope": "Selected pairs"}),
                            {label: None for label in ("A", "B", "C")}, figure)
        row = sheets[PAIRS].loc["A / Z"]
        self.assertEqual(row["Reason"], EMPTY_GROUP)
        self.assertTrue(np.isnan(row["p"]))
        with self.assertRaises(FieldError) as raised:
            analyse(KM, cohort(), recipe(**{WEIGHTING: CUSTOM, RHO: -1, GAMMA: 0}))
        self.assertEqual(raised.exception.field, RHO)
        with self.assertRaises(FieldError):
            analyse(KM, cohort(), recipe(**{GAMMA: float("nan"), WEIGHTING: CUSTOM, RHO: 1}))
        alone = analyse(KM, cohort().iloc[:1], recipe())
        self.assertEqual(alone.tables[GLOBAL].at["Reason", "Value"], NEED_GROUPS)

    def test_cancel_stops_before_publishing_and_leaves_the_table_unchanged(self):
        frame = cohort()
        original = frame.copy()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(WeightedComparisonCancelled):
            analyse(KM, frame, recipe(), cancel=cancel)
        pd.testing.assert_frame_equal(frame, original)

    def test_reopen_recalculates_the_same_tarone_ware_result(self):
        frame = cohort()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.alab"
            table = Dataset(frame.copy())
            table.analyses = [(KM, recipe())]
            save_project(path, {"Coorti": table})
            loaded = load_project(path)["Coorti"]
            method, options = loaded.analyses[0]
            self.assertEqual(options[WEIGHTING], TARONE)
            self.assertNotIn(RHO, options)
            again = reference_record(analyse(method, loaded.frame(), options))
            self.assertAlmostEqual(again["global_test"]["chi2"], TARONE_CHI2, delta=1e-12)
            self.assertAlmostEqual(again["global_test"]["p"], TARONE_P, delta=1e-12)

    def test_adapter_matches_atteso_and_the_reopened_project(self):
        measure = _load("weighted_measure", HERE / "measure.py")
        compare = _load("weighted_compare", HERE / "confronta.py")
        self.assertEqual(measure.main(), 0)
        expected = __import__("json").loads((HERE / "atteso.json").read_text(encoding="utf-8"))
        actual = __import__("json").loads((HERE / "misurato.json").read_text(encoding="utf-8"))
        compare.compare(expected, actual, "risultato", 1e-9)
        reopened = measure.measure_reopened(HERE / "sopravvivenza-pesata.alab")
        self.assertEqual(reopened["global_test"]["chi2"], actual["tarone_ware"]["global_test"]["chi2"])
        self.assertEqual(reopened["global_test"]["p"], actual["tarone_ware"]["global_test"]["p"])

    def test_large_cohort_stays_on_one_pass_over_the_risk_sets(self):
        rng = np.random.default_rng(116)
        size = 50_000
        frame = pd.DataFrame({"time": rng.integers(0, 80, size), "event": rng.integers(0, 2, size),
                              "group": rng.integers(0, 8, size).astype(str)})
        tracemalloc.start()
        started = time.perf_counter()
        global_fit = fit_arrays(frame.time, frame.event, frame.group, INTERMEDIATE, 1, 1)
        global_seconds = time.perf_counter() - started
        _current, global_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        names = sorted(frame.group.unique())
        tracemalloc.start()
        started = time.perf_counter()
        for first, second in ((names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))):
            chosen = frame.group.isin((first, second))
            fit_arrays(frame.loc[chosen, "time"], frame.loc[chosen, "event"], frame.loc[chosen, "group"],
                       INTERMEDIATE, 1, 1)
        pair_seconds = time.perf_counter() - started
        _current, pair_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(f"WEIGHTED_BENCH global_s={global_seconds:.3f} pairs_s={pair_seconds:.3f} "
              f"global_peak_mb={global_peak / 1e6:.1f} pairs_peak_mb={pair_peak / 1e6:.1f} "
              f"process_rss_kb={rss_kb}", flush=True)
        self.assertTrue(global_fit["available"])
        self.assertLess(global_seconds, 15)
        self.assertLess(pair_seconds, 30)


if __name__ == "__main__":
    unittest.main()
