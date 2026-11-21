"""Restore single-series dose fits and their min/max normalization from PCFFGRA4 projects."""
from hashlib import sha256
from struct import error as StructError, pack, unpack

from pandas.api.types import is_numeric_dtype

from .prism_binary_editable import _one, _subgroups
from .prism_binary_results import _column_ids, _title
from .prism_restore import PRISM_NOTES, PRISM_TITLE, _append_linked_recipe
from .prism_xml_binding import indexed_analyses
from .reference_normalization import INDEPENDENT, KEEP, MAXIMUM, METHOD, MINIMUM, NORMALIZED, PERCENTAGES, RAW


# Verified profiles include the solver settings and the entire model/constraint group.
# A different equation, weight, constraint or confidence setting needs separate verification.
_PROFILES = {
    "f04c3279ac8c191d88a9b747caa6225c7a68f6b3260b363a3c455de683ab13b0": "Inhibition (standard slope)",
    "32556fad554e88638605b30435ee5b4ba6495db2b59308adddfed7aab388f049": "Inhibition (standard slope, log10 X)",
    "5c57872f1692212ed2e23cb874b3e7b0792883497b4dafb58dc0e9e2d03b49a6": "Inhibition (variable slope)",
    "6818de067ac49d738c94a7ee479e46b2757b27b2fc07fc07b0d2e547bd197f8a": "Inhibition (variable slope, log10 X)",
    "d5fc64ab35abc09358f75b3ef828b6bf586ca4553082a24fd406e48810fee521": "Normalized inhibition (standard slope)",
    "73a4cc22b914eee060d646bd2acd79afd73a9ab0d8480392f2346980b489c5ab": "Normalized inhibition (standard slope, log10 X)",
    "115d1d8bca767633a765e81dbc50a3a74e2c8039b94eb55ed50754133ba37392": "Normalized inhibition (variable slope)",
    "2fdead24263eced73f71ad2ed981f6f0c24601060f42eac5ba5b3db684d36240": "Normalized inhibition (variable slope, log10 X)",
    "6077a82968fd7453abbea87b063262374ebd4ba793cdd32ae3c76e92c57a9587": "Normalized stimulation (standard slope)",
    "608d8dc4c27c67916273e8cf58d50dc078dd54120426881f0b891ad7784a88ae": "Normalized stimulation (standard slope, log10 X)",
    "d4c87fd18a867d685897b3e170df5dc2872fd2ccc329335c072106d67112af08": "Normalized stimulation (variable slope)",
    "0316c927f25f1e263fd4e02a73dcd98cdc477e9e06d322030ee8d78a2a994054": "Normalized stimulation (variable slope, log10 X)",
    "b12a5f1ed9a19db12ebbe9d21f526caa895bf78930d31ad14f1c35a5561fe060": "Stimulation (standard slope)",
    "fcdfb5b6bfd1430f453779c4628ef39d0482aff1e7d3fd1e07dfa5be0c0d1094": "Stimulation (standard slope, log10 X)",
    "fc1206fa4cce5e0ce81bb87adc3a4f854f42d16ec84e989b1f70b32086faa47e": "Stimulation (variable slope)",
    "12c8a0eef04bef32a03fc27dbe027a46af7015d94422cdf248f99ca3c57dbfa3": "Stimulation (variable slope, log10 X)",
}
_NORMALIZATIONS = {
    "11a6a5f92e1e06d0ccd3b39278046970dd922142635b33e6d3aa3fa511141f84",
    "d1cdccc48615e7d72dddd3368637a8eed01f4af74fdb57e2b0be5a7acadc595d",
}


def _model(records, settings):
    (header, contents), = _subgroups(records, 0x8047)
    fingerprint = sha256(settings)
    fingerprint.update(pack("<I", len(header)))
    fingerprint.update(header)
    for tag, parents, data in contents:
        fingerprint.update(pack("<H", len(parents)))
        for parent in parents:
            fingerprint.update(pack("<H", parent))
        fingerprint.update(pack("<HI", tag, len(data)))
        fingerprint.update(data)
    return _PROFILES.get(fingerprint.hexdigest())


def restore_dose_recipes(data, sources, sheets, snapshots, pending):
    """Attach native recipes only where the input, output and saved column selection agree."""
    try:
        indexed, analyses = indexed_analyses(data)
    except (ValueError, StructError):
        return set()
    normalized = {}
    restored = set()
    # Normalizations may follow the models that consume them in the project index.
    for uid, sheet, kind, records in sorted(analyses, key=lambda a: a[2][0] != 4):
        if uid not in pending or sheets.get(sheet) is None:
            continue
        parent = normalized.get(sheet)
        frame = parent[0] if parent else sources.get(sheet)
        if (frame is None or frame.attrs.get("table_format") != "xy" or len(frame.columns) != 2
                or not all(is_numeric_dtype(dtype) for dtype in frame.dtypes)):
            continue
        x, y = frame.columns
        try:
            count, column, first, last = unpack("<H3i", _one(records, 0x3D))
            if (count != 1 or (column,) != _column_ids(sheets[sheet][0]) or first != last
                    or first < 0 or (parent is None and first != 0)):
                continue
            settings = _one(records, 0x46)
            if len(settings) != 1348:
                continue
            outputs = _one(records, 0x3C)
            title = _title(_one(records, 9))[:160]
            recipes = frame.attrs.get("prism_recipes", [])
            if len(recipes) >= 256:
                continue
            if kind[:2] == (4, 255) and kind[2:6] == (uid, 1, 191, 0) and kind[-1] == 65535:
                if parent or sha256(settings).hexdigest() not in _NORMALIZATIONS:
                    continue
                slots, output, *rest = unpack("<11i", outputs)
                if (slots != 10 or output in indexed or output < 0 or set(rest) != {-1}
                        or snapshots.get(output) != (uid, sheet, 0)):
                    continue
                normalized[output] = frame, len(recipes)
                frame.attrs.setdefault("prism_recipes", []).append((METHOD, {
                    PRISM_TITLE: title, "Input": RAW, "X": x, "Variables": [y], "Replicates": INDEPENDENT,
                    "Zero reference": MINIMUM, "One reference": MAXIMUM, "Units": PERCENTAGES,
                    "Reference values in output": KEEP, "Graph results": False,
                }))
            elif kind == (0, 5, uid, 1, 255, 1, 65535, 0):
                slots, first_slot, report, curve, *rest = unpack("<10i", outputs)
                if (slots != 9 or first_slot != -1 or set(rest) != {-1} or curve < 0 or curve == report
                        or snapshots.get(report) != (uid, sheet, 1)):
                    continue
                model = _model(records, settings)
                if not model or model.startswith("Normalized ") != (parent is not None):
                    continue
                options = {
                    PRISM_TITLE: title, "Model": model, "X": x, "Y": y, "Weighting": "Unweighted",
                    "Runs test": True, PRISM_NOTES: "Refits the dose response from the linked observations. "
                                                   "The saved result tables retain the original estimates.",
                }
                if parent:
                    _append_linked_recipe(frame, parent[1], NORMALIZED, "Nonlinear regression", options)
                else:
                    frame.attrs.setdefault("prism_recipes", []).append(("Nonlinear regression", options))
            else:
                continue
            restored.add(uid)
        except (ValueError, StructError, TypeError, KeyError):
            continue
    return restored
