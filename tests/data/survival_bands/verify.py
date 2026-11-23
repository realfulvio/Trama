"""Oracle for conservative log-log Hall–Wellner bands. Run standalone or against Trama."""
import argparse
from collections import defaultdict
import csv
import json
from math import exp, inf, isclose, isfinite, log, sqrt
from pathlib import Path
import sys


HERE = Path(__file__).parent
LOW, HIGH = "Simultaneous CI lower", "Simultaneous CI upper"


def kolmogorov_critical(level):
    def tail(x):
        return 2 * sum((-1) ** (k - 1) * exp(-2 * k * k * x * x) for k in range(1, 100))

    lo, hi = .3, 5.
    for _ in range(80):
        mid = (lo + hi) / 2
        if tail(mid) > 1 - level / 100:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def g(z):
    return exp(-exp(z)) if z < 710 else 0.


def oracle(rows, level):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["Group"]].append((float(row["Time"]), int(row["Event"])))
    output = {}
    critical = kolmogorov_critical(level)
    for group, records in grouped.items():
        initial = risk = len(records)
        survival, greenwood = 1., 0.
        for time in sorted({time for time, _ in records}):
            values = [event for t, event in records if t == time]
            events = sum(values)
            survival *= 1 - events / risk
            if events:
                greenwood += events / (risk * (risk - events)) if risk > events else inf
            lower = upper = None
            if 0 < survival < 1 and isfinite(greenwood):
                transform = log(-log(survival))
                width = critical * (1 + initial * greenwood) / (sqrt(initial) * abs(log(survival)))
                lower, upper = g(transform + width), g(transform - width)
            output[(str(group), time)] = [risk, events, survival, greenwood, lower, upper]
            risk -= len(values)
    return output


def compare(rows, expected):
    import pandas as pd

    found = {(str(row["Group"]), float(row["Time"])): row for row in rows.to_dict("records")}
    assert len(found) == len(rows) and found.keys() == expected.keys()
    for key, (risk, events, survival, greenwood, lower, upper) in expected.items():
        row = found[key]
        assert (row["At risk"], row["Events"]) == (risk, events), key
        assert isclose(row["Survival"], survival, abs_tol=1e-14), key
        if isfinite(greenwood):
            assert isclose(row["Greenwood factor"], greenwood, rel_tol=2e-12, abs_tol=1e-14), key
        if lower is None:
            assert pd.isna(row[LOW]) and pd.isna(row[HIGH]) and row["Status"] == "Unavailable", key
        else:
            assert isclose(row[LOW], lower, abs_tol=1e-12), key
            assert isclose(row[HIGH], upper, abs_tol=1e-12), key
            assert row["Status"] == "Available", key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    with (HERE / "fixture.csv").open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    checks = []

    def check(label, test):
        try:
            test()
        except Exception as error:
            checks.append({"name": label, "passed": False, "error": repr(error)})
        else:
            checks.append({"name": label, "passed": True})

    def critical():
        assert abs(kolmogorov_critical(95) - 1.3580986393225505) < 1e-12

    def finite():
        results = oracle(rows, 95)
        event = results[("Control", 1.)]
        assert event[0:2] == [8, 2]
        assert abs(event[2] - .75) < 1e-12 and abs(event[3] - 1/24) < 1e-12
        assert results[("Control", 2.)][2:] == event[2:]
        assert results[("Control", 8.)][-2:] == [None, None]
        assert all(row[-2:] == [None, None] for key, row in results.items() if key[0] == "Censored")

    def widths():
        for key, points in oracle(rows, 95).items():
            if points[-2] is not None:
                low, high = oracle(rows, 99)[key][-2:]
                assert low <= points[-2] <= points[2] <= points[-1] <= high

    check("oracle/critical", critical)
    check("oracle/risk-sets-and-boundaries", finite)
    check("oracle/nested-levels", widths)

    if args.repo:
        sys.path.insert(0, str(args.repo.resolve()))
        import os
        os.environ.setdefault("MPLBACKEND", "Agg")
        import pandas as pd
        from analisi.workbench import analyse

        data = pd.read_csv(HERE / "fixture.csv")
        keys = {"Time": "Time", "Event": "Event", "Group": "Group"}
        method = "Kaplan–Meier survival"
        for level in (90, 95, 99):
            for view in ("Survival", "Cumulative events"):
                def run(level=level, view=view):
                    saved = {"Confidence level (%)": level, "Curve": view, "Display units": "Percent", **keys}
                    plain = analyse(method, data, saved)
                    result = analyse(method, data, {**saved, "Uncertainty": "Hall–Wellner simultaneous band"})
                    compare(result.tables["Simultaneous confidence bands"], oracle(rows, level))
                    for sheet, table in plain.tables.items():
                        pd.testing.assert_frame_equal(table, result.tables[sheet])

                check(f"dispatcher/{level}/{view}", run)
    report = {"passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks}
    value = json.dumps(report, indent=2)
    if args.json:
        args.json.write_text(value + "\n", encoding="utf-8")
    print(value)
    return int(report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())

