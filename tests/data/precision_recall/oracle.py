"""Evaluate every threshold by a fresh scan and sum AP with exact fractions."""
from fractions import Fraction
from math import isclose
import csv


def thresholds(rows, column, lower):
    values = [Fraction(row[column]) for row in rows]
    statuses = [row["Event"] == "case" for row in rows]
    n, positives = len(statuses), sum(statuses)
    previous_recall, area = Fraction(0), Fraction(0)
    records = []
    for threshold in sorted(set(values), reverse=not lower):
        predicted = [value <= threshold if lower else value >= threshold for value in values]
        tp = sum(a and b for a, b in zip(statuses, predicted, strict=True))
        fp = sum(predicted) - tp
        precision, recall = Fraction(tp, tp + fp), Fraction(tp, positives)
        area += (recall - previous_recall) * precision
        previous_recall = recall
        records.append([str(threshold), tp, fp, n - positives - fp, positives - tp, str(precision), str(recall)])
    return {"N": n, "Positives": positives, "prevalence": str(Fraction(positives, n)),
            "AP": str(area), "thresholds": records}


def reference(folder):
    with (folder / "scores.csv").open(newline="", encoding="utf-8") as file:
        rows = [row for row in csv.DictReader(file) if row["Event"] and row["Signal A"] and row["Signal B"]]
    first = thresholds(rows, "Signal A", lower=False)
    second = thresholds(rows, "Signal B", lower=True)
    return {"scores": {"Signal A": first, "Signal B": second},
            "difference": str(Fraction(second["AP"]) - Fraction(first["AP"]))}


def verify_candidate(folder, expected, analyse, pd):
    frame = pd.read_csv(folder / "scores.csv")
    result = analyse("Precision–recall curve", frame, {
        "Outcome": "Event", "Positive": "case", "Negative": "control", "Score": "Signal A",
        "Second score": "Signal B", "Direction": "Higher is positive", "Second direction": "Lower is positive",
    })
    for column, answer in result.tables["Summary"].set_index("Score").iterrows():
        entry = expected["scores"][column]
        yield f"{column}: AP", (answer["N"] == entry["N"] and answer["Positives"] == entry["Positives"]
                               and isclose(answer["Prevalence"], float(Fraction(entry["prevalence"])), rel_tol=1e-12)
                               and isclose(answer["Average precision"], float(Fraction(entry["AP"])), rel_tol=1e-12))
    yield "both scores in summary", result.tables["Summary"]["Score"].tolist() == list(expected["scores"])
    for column, entry in expected["scores"].items():
        table = result.tables[f"Thresholds: {column}"]
        names = ["Threshold", "TP", "FP", "TN", "FN", "Precision", "Recall"]
        actual = table[names].itertuples(index=False, name=None)
        yield f"{column}: thresholds", len(table) == len(entry["thresholds"]) and all(
            all(isclose(a, float(Fraction(e)), rel_tol=1e-12, abs_tol=1e-14)
                for a, e in zip(row, target, strict=True))
            for row, target in zip(actual, entry["thresholds"], strict=True)
        )
    yield "paired difference", isclose(result.tables["Comparison"].iloc[0]["AP difference"],
                                       float(Fraction(expected["difference"])), rel_tol=1e-12, abs_tol=1e-14)
