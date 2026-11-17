"""One native drawing in bounded Unicode clipboard text; no executable content."""
import json
import uuid

from .graph_shapes import validate_shape, validate_shapes
from .i18n import tr

# Serialized clipboard identifier: preserve compatibility across the Trama rename.
FORMAT = 'TramaStat/native-drawing'
MAX_TEXT = 65536


def dump_shape(record):
    """Serialize a validated drawing without modifying it or inserting defaults."""
    shape = validate_shape(record)
    return json.dumps({'format': FORMAT, 'version': 1, 'shape': shape},
                      ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate clipboard key.')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite clipboard number.')


def load_shape(text):
    """Accept only the closed v1 envelope and the existing canonical drawing schema."""
    try:
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError('Invalid clipboard text.')
        envelope = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        if (not isinstance(envelope, dict) or set(envelope) != {'format', 'version', 'shape'}
                or envelope['format'] != FORMAT or type(envelope['version']) is not int
                or envelope['version'] != 1):
            raise ValueError('Unsupported clipboard format.')
        return validate_shape(envelope['shape'])
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError(tr('shape.clipboard.invalid')) from error


def paste_shape(records, text):
    """Append an independent drawing with a new identity, validating the complete result."""
    candidate = validate_shapes(records)
    shape = load_shape(text)
    shape['id'] = str(uuid.uuid4())
    candidate.append(shape)
    return validate_shapes(candidate), shape['id']
