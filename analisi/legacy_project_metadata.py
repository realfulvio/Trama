"""Stable names for application-owned metadata in imported projects."""

from hashlib import sha256


LEGACY_METADATA_VERSION = 4
XML_ERROR_BARS = "Legacy XML XY errors"
IMPORT_OPTION_PREFIX = "Legacy "
_RETIRED_OPTION_PREFIX = "f8ea2124fa5c166f915801f2e295cf105f8f3ba81d0a5c374985de7884aa2e42"

IMPORTED_METHODS = frozenset({
    'Imported XY graph',
    'Imported archived graph',
    'Imported archived layout',
    'Imported editable graph',
    'Imported saved results',
})
IMPORTED_FORMATS = frozenset({
    'Imported editable EMF XY',
    'Imported editable PDF stacks',
    'Imported editable XY',
    'Imported editable columns',
    'Imported graph collection',
    'Imported graph snapshot',
    'Imported layout collection',
    'Imported result snapshot',
})
IMPORTED_FIELDS = frozenset({
    XML_ERROR_BARS,
    'Legacy XML binding graph',
    'Legacy XML generated XY graph',
    'Legacy XML linked descriptive graph',
    'Legacy ZIP XY data',
    'Legacy ZIP aligned column',
    'Legacy ZIP layout',
    'Legacy editable layout panels',
    'Legacy graph preview',
    'Legacy import notes',
    'Legacy layout panel data',
    'Legacy layout panel edits',
    'Legacy layout panels',
    'Legacy notes',
    'Legacy original graph link',
    'Legacy original graph style',
    'Legacy result provenance',
    'Legacy result sheet',
    'Legacy sheet title',
    'Legacy title',
})

# Exact UTF-8 digests of the retired identifiers emitted in versions 1 to 3.
# Limit translation to these known values. Worksheet labels and payloads are ordinary data.
_RETIRED_NAMES = {
    "9517e9058e8f8cfddf9cf1aaa5bd97a90240e88e6f09b87f5eeff28217bce3d7": 'Imported XY graph',
    "2c54787318304da72fe19bd56e58fe4798fc77d92729da9b6ff06c2b8334bb71": 'Imported archived graph',
    "531f037326d0d2f0370961f789eae4b2e6c2dfc567ad4ec58d646d0a56116b0d": 'Imported archived layout',
    "a4709a5d0928cb646d1574294112d9f2cbcd08bb7dd9616d8e9008596b83d28c": 'Imported editable graph',
    "feccebbe08e1001c632c174e4d606e78182eba81ede8755659d3e5fd1b298c33": 'Imported saved results',
    "a9bcf7259b443882f047f003165d175e678e9fed0cf6136af171b77209d91bc7": 'Imported editable XY',
    "150fccd7315c5c9a6a05377c42e8bad73462714cbbf19c6b6b8326fa1d8a49d3": 'Imported editable columns',
    "bb893dbf174509b716e06bd8a225ea61c6fd72e1ae5cc397105d1f00bd31ab7c": 'Imported editable PDF stacks',
    "2a90c07f9952c8f614fb2f7a4e2dc645ab7ceb8d762fccf4991bacd5398c7a3f": 'Imported editable EMF XY',
    "0adbe5c3978510ad2129a9096f1ceb0f670805a3dc3e73b9adc61145ea1c0334": 'Imported graph collection',
    "c94dad26017c2a8c295642c636e5109c9a7ac72cd2d9a73b9a1d6c71e46ba3b4": 'Imported layout collection',
    "d5f8cc56619f514e462df8eb039e25cf68bef664fb474e3d73d73e2442aa0119": 'Imported graph snapshot',
    "4f895d19892b7504c4c5fda6e7f7a5adf0745731bddd5e8127fadf7a4c0bced5": 'Imported result snapshot',
    "5eb77c6ef2fb7b6d008b862df33d6f50a792f7516c3f7cfb8824d83aecf099bc": 'Legacy original graph link',
    "247390c3daae2a4da07f3b593cb6a099e60218f137e456ae21861c4088eac108": 'Legacy original graph style',
    "04243c9f52ff06e00aca10367b2e7fad097ff41ea0fc1a16e4612f9489f15c3d": 'Legacy layout panels',
    "a92956f272b70888ab823bd417090e76461e8011ed0e8fc8745989288a454afb": 'Legacy graph preview',
    "01fbd814c627a91fd29f0adec44d78891ff95e1d4c79ae19d93fc9627ee78799": 'Legacy result sheet',
    "ee8def1629493e479ed1d1577d14d6a7bf92d4a5dc5a07ec62630e9e4da1543f": 'Legacy sheet title',
    "c1b7352e4d9f6550f9c86bc378d258a0729c1673a5a3332beaf90ea41309b279": 'Legacy import notes',
    "a4e525b3fbaa0ca01b450ba56e315c628a4311d4bf53fcc773901a6d6d2e40a0": 'Legacy result provenance',
    "08df0e8447bb43f784ee00df2ada0223b42a05c8dd657fc69c3300cc35f963ad": 'Legacy editable layout panels',
    "1c062c14729b4b798d72a964e1d124c2824ee18a37fd8b11562991623f081d5c": 'Legacy layout panel edits',
    "705540c398b7ae3616e0a8f13db6170bebb6f9c12689a01c3ce2339518cedab6": 'Legacy layout panel data',
    "fc093464e9ad6dac6f8e4fa5922354387313c0a468bd8904536675d1a4068e14": 'Legacy XML binding graph',
    "9cb7c4388440789f5b7f5def47ea59ebe616a92277a99efbcc14d08d77fa892c": 'Legacy XML linked descriptive graph',
    "32b56f86746cb9dbb7263b11ac64349e2e1d75aa7b5f3c53b0b73d5706f21064": 'Legacy ZIP layout',
    "dee091c07ab6859694aa1af5afb24406205e84dc0cd3db25b6f8fa38a3901176": 'Legacy XML generated XY graph',
    "141e47793a6aee198ee44593af0900dc3fcfb834514cc6ad7f14aefbe0c87296": 'Legacy XML XY errors',
    "ad7279c5d1936c39b77f46620a451693f658ebe9d4ded55b8db6d2699e972219": 'Legacy ZIP aligned column',
    "ce623e88d435293e44230aac0f9551eeedfbfcc27c98d42d94b348c2abbd5d2e": 'Legacy ZIP XY data',
    "7748125076ba0eae087a2f2d532ad848b6b4d74f801dc10a623149ffc30f31ce": 'Legacy title',
    "5aebaa0227cd8a90af04579b4f945dbc89b07886d197c1126006104001e3b7b3": 'Legacy notes',
}


def saved_name(value):
    """Translate a retired saved identifier, or leave the name as received."""
    return _RETIRED_NAMES.get(sha256(value.encode()).hexdigest(), value)


def saved_table_format(value):
    """Normalize the earlier XML name used by multiple-variables worksheets."""
    name = saved_name(value)
    return "multivariable" if name.casefold() == "multiplevariables" else name


def saved_analysis(method, options, *, row_frame=None):
    translated = {}
    for key, value in options.items():
        name = saved_name(key)
        if name in translated:
            raise ValueError(f"Duplicate versioned analysis option: {name}.")
        translated[name] = value
    if row_frame is not None and XML_ERROR_BARS in translated:
        from .legacy_xml_xy import pin_error_directions

        translated[XML_ERROR_BARS] = pin_error_directions(translated[XML_ERROR_BARS], row_frame)
    return saved_name(method), translated


def is_import_option(name):
    return (name.startswith(IMPORT_OPTION_PREFIX)
            or sha256(name[:6].encode()).hexdigest() == _RETIRED_OPTION_PREFIX)


def uses_import_metadata(table_format, analyses):
    return table_format in IMPORTED_FORMATS or any(
        method in IMPORTED_METHODS or not IMPORTED_FIELDS.isdisjoint(options)
        for method, options in analyses
    )
