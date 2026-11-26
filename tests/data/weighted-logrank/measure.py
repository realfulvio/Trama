"""Run the Kaplan–Meier recipe and write misurato.json in the shape of atteso.json.

The global weights are read from the step curve that the figure actually draws. The
chi-square, the pairs and the Holm values are read from the result sheets. The same
recipe is saved, opened again and measured a second time.

    python measure.py
    python confronta.py misurato.json
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from analisi.data import Dataset, load_project, save_project  # noqa: E402
from analisi.weighted_logrank import (CUSTOM, DETAIL, EARLY, GAMMA, GEHAN, INTERMEDIATE, LATE, LOG_RANK,  # noqa: E402
                                      RHO, TARONE, WEIGHTING, reference_record)
from analisi.workbench import analyse  # noqa: E402

HERE = Path(__file__).resolve().parent
METHOD = "Kaplan–Meier survival"
ORDER = (
    ("logrank", LOG_RANK, None),
    ("tarone_ware", TARONE, None),
    ("gehan", GEHAN, None),
    ("fh_1_0", EARLY, None),
    ("fh_0_1", LATE, None),
    ("fh_1_1", INTERMEDIATE, None),
    ("fh_0_0", CUSTOM, (0.0, 0.0)),
)


def cohort():
    return pd.read_csv(HERE / "coorti.csv")


def recipe(choice, exponents=None):
    options = {"Time": "tempo", "Event": "evento", "Group": "gruppo", "Pairwise correction": "Holm",
               "Pairwise scope": "All pairs", WEIGHTING: choice, DETAIL: True}
    if exponents is not None:
        options[RHO], options[GAMMA] = exponents
    return options


def measure(frame, choice, exponents=None):
    """One block of atteso.json from the normal analysis, including the drawn weights."""
    return reference_record(analyse(METHOD, frame, recipe(choice, exponents)))


def measured_document(frame=None):
    frame = cohort() if frame is None else frame
    return {key: measure(frame, choice, exponents) for key, choice, exponents in ORDER}


def save_example(path, frame=None):
    """A project that reopens on the Tarone–Ware comparison of this cohort."""
    frame = cohort() if frame is None else frame
    table = Dataset(frame.copy())
    table.analyses = [(METHOD, recipe(TARONE))]
    save_project(path, {"Coorti": table})


def measure_reopened(path):
    loaded = load_project(path)["Coorti"]
    method, options = loaded.analyses[0]
    return reference_record(analyse(method, loaded.frame(), options))


def main():
    document = measured_document()
    destination = HERE / "misurato.json"
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    example = HERE / "sopravvivenza-pesata.alab"
    save_example(example)
    again = measure_reopened(example)
    if again != document["tarone_ware"]:
        # Floats written through JSON and back are not the comparison; compare the live records.
        raise SystemExit("The reopened Tarone–Ware result differs from the result just calculated.")
    print(f"Wrote {destination.name} and {example.name}. Reopen matches Tarone–Ware.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
