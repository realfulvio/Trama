"""Small independent reference for synthetic fixtures. Python standard library only."""

import csv
from fractions import Fraction
from itertools import product
from math import erfc, exp, log, sqrt
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent  # Trama copy: the fixtures sit in fixtures/ beside this file


def records(name):
    with (ROOT / "fixtures" / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def readable_rows(rows, horizon, level=95.0):
    """Use direct risk counts and the full covariance matrix of the KM steps."""
    tau = Fraction(str(horizon))
    observed = [(Fraction(str(time)), int(event)) for time, event in rows]
    if not observed or tau <= 0 or max(t for t, _ in observed) < tau:
        raise ValueError("The fixture has insufficient follow-up.")
    cuts = sorted({Fraction(0), tau} | {t for t, event in observed if event and 0 < t < tau})
    events = sorted({t for t, event in observed if event and t < tau})
    effects = []
    for time in events:
        risk = sum(t >= time for t, _ in observed)
        deaths = sum(t == time and event for t, event in observed)
        effects.append((time, Fraction(risk - deaths, risk),
                        Fraction(deaths, risk * (risk - deaths)) if risk > deaths else 0))
    segments = []
    for left, right in zip(cuts, cuts[1:]):
        survival = Fraction(1)
        for time, multiplier, _ in effects:
            if time <= left:
                survival *= multiplier
        segments.append((left, right, survival, (right - left) * survival))
    mean = sum((area for _, _, _, area in segments), Fraction(0))
    variance = Fraction(0)
    for first, second in product(segments, repeat=2):
        shared_history = sum(factor for time, _, factor in effects
                             if time <= min(first[0], second[0]))
        variance += first[3] * second[3] * shared_history
    estimate = float(mean)
    se = sqrt(float(variance))
    z = -NormalDist().inv_cdf((100 - level) / 200)
    return {
        "N": len(observed),
        "Events through horizon": sum(event for time, event in observed if time <= tau),
        "Max follow-up": float(max(time for time, _ in observed)),
        "Horizon": float(tau),
        "RMST": estimate,
        "SE": se,
        "CI lower": estimate - z * se if se else None,
        "CI upper": estimate + z * se if se else None,
        "Status": "OK" if se else "Zero variance",
        "exact_mean": str(mean),
        "exact_variance": str(variance),
        "steps": [[float(value) for value in segment] for segment in segments],
    }


def contrast(compared, reference, level=95.0):
    a, b = compared["RMST"], reference["RMST"]
    va, vb = compared["SE"] ** 2, reference["SE"] ** 2
    z = -NormalDist().inv_cdf((100 - level) / 200)
    delta, se = a - b, sqrt(va + vb)
    difference = {
        "Estimate": delta, "Inference SE": se, "Scale": "Identity",
        "CI lower": delta - z * se if se else None,
        "CI upper": delta + z * se if se else None,
        "p": erfc(abs(delta / se) / sqrt(2)) if se else None,
        "Status": "OK" if se else "Zero variance",
    }
    ratio = dict.fromkeys(("Estimate", "Inference SE", "CI lower", "CI upper", "p"))
    ratio.update(Scale="Log", Status="Undefined ratio")
    if b > 0:
        ratio["Estimate"] = a / b
        ratio["Status"] = "Log inference unavailable"
    if a > 0 and b > 0:
        log_ratio = log(a / b)
        se = sqrt(va / a ** 2 + vb / b ** 2)
        ratio["Inference SE"] = se
        ratio["Status"] = "OK" if se else "Zero variance"
        if se:
            ratio.update({"CI lower": exp(log_ratio - z * se),
                          "CI upper": exp(log_ratio + z * se),
                          "p": erfc(abs(log_ratio / se) / sqrt(2))})
    return {"Difference": difference, "Ratio": ratio}


def fixture_expectations():
    rows = records("cohorts.csv")
    arm_names = ("Reference", "Series $B")
    arms = {name: readable_rows([(r["Time"], r["Event"]) for r in rows if r["Group"] == name], 6.5)
            for name in arm_names}
    degenerate = records("degenerate.csv")
    terminal = readable_rows([(r["Time"], r["Event"]) for r in degenerate
                              if r["Group"] == "Terminal event"], 3)
    censored = readable_rows([(r["Time"], r["Event"]) for r in degenerate
                              if r["Group"] == "All censored"], 5)
    text = [r for r in records("text-status.csv") if all(r.values())]
    text_arms = {
        name: readable_rows([(r["Time"], r["Status"] == "event") for r in text if r["Cohort"] == name],
                            4, level=90) for name in ("Ref", "Active")
    }
    return {"arms": arms, "contrasts": contrast(arms[arm_names[1]], arms[arm_names[0]]),
            "terminal": terminal, "all_censored": censored, "text_arms": text_arms}


if __name__ == "__main__":
    import json

    print(json.dumps(fixture_expectations(), indent=2, allow_nan=False))
