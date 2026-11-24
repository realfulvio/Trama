"""Native drawing objects in bounded Unicode clipboard text."""
import json
from .graph_shapes import validate_shape, validate_shapes
from .i18n import tr
from .shape_objects import duplicate_object, object_key

# Serialized clipboard identifier: preserve compatibility across the Trama rename.
FORMAT = 'TramaStat/native-drawing'
MAX_TEXT = 65536


def dump_shape(record):
    """Serialize a validated drawing without modifying it or inserting defaults."""
    shape = validate_shape(record)
    return json.dumps({'format': FORMAT, 'version': 1, 'shape': shape},
                      ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def dump_object(records):
    """Use the original clipboard format for a single shape."""
    records = validate_shapes(records)
    if len(records) == 1:
        return dump_shape(records[0])
    if len(records) < 2 or len({object_key(record) for record in records}) != 1:
        raise ValueError(tr("shape.clipboard.invalid"))
    return json.dumps({"format": FORMAT, "version": 2, "shapes": records},
                      ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate clipboard key.')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite clipboard number.')


def _load_object(text, *, groups):
    try:
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError("Invalid clipboard text.")
        envelope = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        if (not isinstance(envelope, dict) or envelope.get("format") != FORMAT
                or type(envelope.get("version")) is not int):
            raise ValueError("Unsupported clipboard format.")
        version = envelope["version"]
        if version == 1 and set(envelope) == {"format", "version", "shape"}:
            return [validate_shape(envelope["shape"])]
        if groups and version == 2 and set(envelope) == {"format", "version", "shapes"}:
            records = validate_shapes(envelope["shapes"])
            if len(records) >= 2 and len({object_key(record) for record in records}) == 1:
                return records
        raise ValueError("Unsupported clipboard format.")
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError(tr("shape.clipboard.invalid")) from error


def load_shape(text):
    """Accept the original single-shape clipboard format."""
    return _load_object(text, groups=False)[0]


def paste_shape(records, text):
    """Append an independent copy of a drawing object, with fresh identities."""
    candidate = validate_shapes(records)
    copies = duplicate_object(_load_object(text, groups=True))
    candidate.extend(copies)
    return validate_shapes(candidate), copies[0]["id"]
