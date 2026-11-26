"""Multivariate bubble plot: English/Italian captions and engine/UI messages.

``analisi.interface_catalog`` merges these tables at the end of its own. Recipes and saved style
dictionaries keep canonical English keys and values; sheet names, column headings and worksheet
labels stay literal.
"""

CAPTIONS = {
    "Bubble values": "Valori delle bolle",
    "Marker area (pt²)": "Area del simbolo (pt²)",
    "Color position (u)": "Posizione nella scala colore (u)",
    "Color": "Colore",
    "Shape": "Forma",
    "Size mode": "Modalità dimensione",
    "From column": "Da colonna",
    "Fixed area": "Area fissa",
    "Fixed area (pt²)": "Area fissa (pt²)",
    "By category": "Per categoria",
    "Fixed color": "Colore fisso",
    "Continuous scale": "Scala continua",
    "Point color": "Colore dei punti",
    "Reverse palette": "Inverti tavolozza",
    "Color limits": "Limiti colore",
    "Manual": "Manuale",
    "Color minimum": "Minimo colore",
    "Diverging midpoint": "Centro divergente",
    "Color maximum": "Massimo colore",
    "Show color scale": "Mostra scala colore",
    "Color scale title": "Titolo scala colore",
    "Shape mode": "Modalità forma",
    "Fixed shape": "Forma fissa",
    "Symbol shape": "Forma simbolo",
    "Symbol map": "Mappa simboli",
    "Missing shape": "Forma mancanti",
    "Show shape legend": "Mostra legenda forme",
    "Cividis": "Cividis",
    "Magma": "Magma",
    "Cool–warm": "Freddo–caldo",
    "Purple–green": "Viola–verde",
}

MESSAGES = {
    "bubble.style.button": ("Symbols and encoding…", "Simboli e codifica…"),
    "bubble.style.title": ("Bubble encoding and symbols", "Codifica e simboli del grafico a bolle"),
    "bubble.style.preview": ("Preview", "Anteprima"),
    "bubble.style.apply": ("Apply", "Applica"),
    "bubble.style.cancel": ("Cancel", "Annulla"),
    "bubble.style.pick": ("Pick…", "Scegli…"),
    "bubble.style.tab.size": ("Size", "Dimensione"),
    "bubble.style.tab.color": ("Color", "Colore"),
    "bubble.style.tab.shape": ("Shapes", "Forme"),
    "bubble.style.tab.legends": ("Legends and labels", "Legende ed etichette"),
    "bubble.style.tab.levels": ("Level symbols", "Simboli per livello"),
    "bubble.style.group.size": ("Symbol area", "Area dei simboli"),
    "bubble.style.group.fill": ("Fill color", "Colore di riempimento"),
    "bubble.style.group.shape": ("Symbol shape", "Forma dei simboli"),
    "bubble.style.group.legends": ("Guides on figure", "Legende sulla figura"),
    "bubble.style.inspector.section": ("Bubble encoding", "Codifica bolle"),
    "bubble.style.edit_symbols": ("Edit level symbols…", "Modifica simboli per livello…"),
    "bubble.style.edit_colors": ("Edit category colors…", "Modifica colori categorie…"),
    "bubble.style.symbols_button": ("Symbols…", "Simboli…"),
    "bubble.style.colors_button": ("Colors…", "Colori…"),
    "bubble.style.levels_summary": ("{count} level(s)", "{count} livelli"),
    "bubble.style.levels_summary.none": ("No levels available", "Nessun livello disponibile"),
    "bubble.style.level_col.level": ("Level", "Livello"),
    "bubble.style.level_col.type": ("Type", "Tipo"),
    "bubble.style.level_col.symbol": ("Symbol", "Simbolo"),
    "bubble.style.level_col.color": ("Color", "Colore"),
    "bubble.style.type.number": ("Number", "Numero"),
    "bubble.style.type.text": ("Text", "Testo"),
    "bubble.style.type.bool": ("Boolean", "Booleano"),
    "bubble.style.type.other": ("Value", "Valore"),
    "bubble.style.reset_symbols": ("Reset symbols", "Ripristina simboli"),
    "bubble.style.warning.shape_repeat": (
        "More than {limit} shape levels (or duplicate assignments): some symbols repeat across levels.",
        "Più di {limit} livelli di forma (o assegnazioni duplicate): alcuni simboli si ripetono tra i livelli.",
    ),
    "bubble.legend.missing": ("Missing", "Mancanti"),
    "bubble.legend.all_missing": ("All values missing", "Tutti i valori mancanti"),
    "bubble.legend.unit_max": ("{name}: max {area} pt²", "{name}: max {area} pt²"),
    "bubble.legend.unit_fixed": ("Fixed area: {area} pt²", "Area fissa: {area} pt²"),
    "bubble.shape.o": ("Circle (o)", "Cerchio (o)"),
    "bubble.shape.s": ("Square (s)", "Quadrato (s)"),
    "bubble.shape.^": ("Triangle up (^)", "Triangolo su (^)"),
    "bubble.shape.D": ("Diamond (D)", "Rombo (D)"),
    "bubble.shape.v": ("Triangle down (v)", "Triangolo giù (v)"),
    "bubble.shape.p": ("Pentagon (p)", "Pentagono (p)"),
    "bubble.shape.*": ("Star (*)", "Stella (*)"),
    "bubble.shape.P": ("Filled plus (P)", "Croce piena (P)"),
    "bubble.shape.X": ("Filled X (X)", "X piena (X)"),
    "bubble.shape.h": ("Hexagon (h)", "Esagono (h)"),
    "bubble.shape.<": ("Triangle left (<)", "Triangolo sinistra (<)"),
    "bubble.shape.>": ("Triangle right (>)", "Triangolo destra (>)"),
    "bubble.shape.x": ("Cross (x)", "Croce (x)"),
    "bubble.shape.+": ("Plus (+)", "Più (+)"),
    "bubble.error.color_column": (
        "Choose a numeric column for Color, distinct from X, Y and Size.",
        "Scegli una colonna numerica per Colore, diversa da X, Y e Dimensione.",
    ),
    "bubble.error.shape_column": (
        "Choose an existing column for Shape.",
        "Scegli una colonna esistente per Forma.",
    ),
    "bubble.error.fixed_area": (
        "Fixed area must be greater than 0 and at most {limit} pt².",
        "L’area fissa deve essere maggiore di 0 e al massimo {limit} pt².",
    ),
    "bubble.error.max_area": (
        "Maximum area must be greater than 0 and at most {limit} pt².",
        "L’area massima deve essere maggiore di 0 e al massimo {limit} pt².",
    ),
    "bubble.error.color_limits_number": (
        "Color scale limits must be finite numbers.",
        "I limiti della scala colore devono essere numeri finiti.",
    ),
    "bubble.error.color_limits_order": (
        "Color minimum must be strictly less than color maximum.",
        "Il minimo del colore deve essere strettamente minore del massimo.",
    ),
    "bubble.error.midpoint_range": (
        "Diverging midpoint must lie strictly between Color minimum and Color maximum.",
        "Il centro divergente deve essere strettamente compreso tra Minimo e Massimo.",
    ),
    "bubble.error.color_value": (
        "Enter a valid color, for example #216a94.",
        "Inserisci un colore valido, ad esempio #216a94.",
    ),
    "bubble.error.shape_choice": (
        "Choose one of the supported symbol shapes.",
        "Scegli una delle forme simbolo supportate.",
    ),
}

_ENGLISH_TO_KEY = {
    "Choose a Color column different from X, Y and Size.": "bubble.error.color_column",
    "Choose an existing column for Shape.": "bubble.error.shape_column",
    "Enter finite Color minimum and Color maximum when limits are Manual.": "bubble.error.color_limits_number",
    "Color minimum must be strictly less than Color maximum.": "bubble.error.color_limits_order",
    "Diverging midpoint must lie strictly between Color minimum and Color maximum.": "bubble.error.midpoint_range",
    "Enter a valid color, for example #216a94.": "bubble.error.color_value",
    "Choose a valid symbol shape.": "bubble.error.shape_choice",
}


def translate_bubble_error(error):
    from .i18n import tr, ui

    text = str(error)
    if text in _ENGLISH_TO_KEY:
        return tr(_ENGLISH_TO_KEY[text])
    return ui(text)
