"""Italian text of the power planning dialog (Tools → Power and sample size).

The engine raises English messages; ``translate_message`` matches them against the ``power.error.`` entries below
(placeholders keep field names and numbers literal; the entry with two examples comes first so it matches before
the one with a single example). Recipes keep the English field names and values.
``i18n`` registers ``CAPTIONS`` (dialog fields, tabs and fixed choices), ``EN`` and ``IT`` at startup.
"""

CAPTIONS = {
    "Effect": "Effetto",
    "Effect input": "Dati dell’effetto",
    "Means and SD": "Medie e deviazioni standard",
    "Mean A": "Media A",
    "Mean B": "Media B",
    "Common SD": "Deviazione standard comune",
    "Group means": "Medie dei gruppi",
    "Paired SD input": "Deviazione standard delle coppie",
    "SD of differences": "SD delle differenze",
    "Marginal SDs and correlation": "SD marginali e correlazione",
    "Difference SD": "SD della differenza",
    "SD A": "SD A",
    "SD B": "SD B",
    "Pair correlation": "Correlazione tra le coppie",
    "Allocation A:B": "Allocazione A:B",
    "Show power curve": "Mostra la curva di potenza",
    "Effect size": "Dimensione dell’effetto",
    "Groups": "Gruppi",
    "Alpha": "Alfa",
    "Power curve": "Curva di potenza",
}

# Every entry of "power.error." matches an English message of the engine exactly.
EN = {
    "power.sheet": "Power analysis",
    "power.error.group_item_number": "{field}: item {position} ({shown}) must be a number.",
    "power.error.group_item_finite": "{field}: item {position} ({shown}) must be finite.",
    "power.error.group_item_empty": "{field}: item {position} is empty. Separate the means with semicolons or new lines.",
    "power.error.group_count": "{field} must list from {low} to {high} means; {count} found.",
    "power.error.group_list": "{field} must be a list of numbers separated by semicolons or new lines.",
    "power.error.group_equal": "The group means are all equal, so the effect is zero.",
    "power.error.number": "{field} must be a number.",
    "power.error.finite": "{field} must be finite.",
    "power.error.whole": "{field} must be a whole number from {low} to {high}.",
    "power.error.probability": "{field} must be strictly between 0 and 1.",
    "power.error.positive_measure": "Effect size must be positive ({measure}).",
    "power.error.positive": "{field} must be greater than 0.",
    "power.error.correlation": "{field} must be between -1 and 1.",
    "power.error.choice": "Choose a valid value for {field}.",
    "power.error.zero_null": "The effect is zero: Mean A equals the null mean.",
    "power.error.zero_means": "The effect is zero: Mean A equals Mean B.",
    "power.error.range": "The effect cannot be computed: the means and the SD give a value outside the supported "
                         "numeric range.",
    "power.error.tiny": "The effect cannot be computed: the difference is too small compared with the SD.",
    "power.error.paired_range": "The SD of the paired difference is outside the supported numeric range.",
    "power.error.paired_zero": "The SD of the paired difference is zero: SD A equals SD B and the correlation is 1. "
                               "Choose a correlation below 1.",
    "power.error.allocation": "{field} must be two whole numbers from 1 to {high}, separated by a colon, "
                              "for example 2:3.",
    "power.error.multiple_two": "N must be a multiple of {step} to keep Allocation {a}:{b} exact, for example "
                                "{lower} or {upper}.",
    "power.error.multiple": "N must be a multiple of {step} to keep Allocation {a}:{b} exact, for example {example}.",
    "power.error.small_group": "Each group needs at least 2 observations: Allocation {a}:{b} gives Group B only "
                               "{count} with this N. The smallest N is {smallest}.",
    "power.error.large_group": "Each group is limited to {limit} observations: Allocation {a}:{b} gives Group B "
                               "{count} with this N.",
    "power.error.limit": "Target power exceeds the sample size limit of {limit}.",
    "power.error.numeric": "Power calculation is outside the supported numeric range.",
    "power.note.design": "Allocation A:B fixes the ratio of the two groups for every design the search considers: "
                         "2:3 means n A = 2m and n B = 3m. In Power mode N is the size of group A.",
    "power.note.effect": "Means and SD turn the expected values into the standardized effect. Separate group means "
                         "with semicolons or new lines; a comma is a decimal mark (13,5 is one value).",
    "power.note.curve": "The curve draws power against the total sample size for the same design, at most 200 "
                        "points. The chosen N is marked; with Sample size, so is the target power.",
}

IT = {
    "power.sheet": "Analisi di potenza",
    "power.error.group_item_number": "{field}: l’elemento {position} ({shown}) deve essere un numero.",
    "power.error.group_item_finite": "{field}: l’elemento {position} ({shown}) deve essere finito.",
    "power.error.group_item_empty": "{field}: l’elemento {position} è vuoto. Separa le medie con punti e virgola "
                                    "o con a capo.",
    "power.error.group_count": "{field} deve elencare da {low} a {high} medie; ne risultano {count}.",
    "power.error.group_list": "{field} deve essere un elenco di numeri separati da punti e virgola o da a capo.",
    "power.error.group_equal": "Le medie dei gruppi sono tutte uguali, quindi l’effetto è zero.",
    "power.error.number": "{field} deve essere un numero.",
    "power.error.finite": "{field} deve essere finito.",
    "power.error.whole": "{field} deve essere un numero intero da {low} a {high}.",
    "power.error.probability": "{field} deve essere compreso tra 0 e 1, estremi esclusi.",
    "power.error.positive_measure": "La dimensione dell’effetto deve essere positiva ({measure}).",
    "power.error.positive": "{field} deve essere maggiore di 0.",
    "power.error.correlation": "{field} deve essere compresa tra -1 e 1.",
    "power.error.choice": "Scegli un valore valido per {field}.",
    "power.error.zero_null": "L’effetto è zero: la Media A coincide con la media sotto l’ipotesi nulla.",
    "power.error.zero_means": "L’effetto è zero: la Media A coincide con la Media B.",
    "power.error.range": "L’effetto non è calcolabile: medie e deviazione standard danno un valore fuori "
                         "dall’intervallo numerico supportato.",
    "power.error.tiny": "L’effetto non è calcolabile: la differenza è troppo piccola rispetto alla deviazione "
                        "standard.",
    "power.error.paired_range": "La deviazione standard della differenza appaiata è fuori dall’intervallo "
                                "numerico supportato.",
    "power.error.paired_zero": "La deviazione standard della differenza appaiata è zero: SD A coincide con SD B e la "
                               "correlazione è 1. Scegli una correlazione minore di 1.",
    "power.error.allocation": "{field} deve essere formata da due numeri interi da 1 a {high}, separati da due "
                              "punti, per esempio 2:3.",
    "power.error.multiple_two": "N deve essere un multiplo di {step} per mantenere esatta l’allocazione {a}:{b}, "
                                "per esempio {lower} o {upper}.",
    "power.error.multiple": "N deve essere un multiplo di {step} per mantenere esatta l’allocazione {a}:{b}, per "
                            "esempio {example}.",
    "power.error.small_group": "Ogni gruppo richiede almeno 2 osservazioni: con l’allocazione {a}:{b} il gruppo B "
                               "avrebbe solo {count} osservazioni con questo N. Il più piccolo N valido è {smallest}.",
    "power.error.large_group": "Ogni gruppo è limitato a {limit} osservazioni: con l’allocazione {a}:{b} il gruppo B "
                               "ne avrebbe {count} con questo N.",
    "power.error.limit": "La potenza desiderata supera il limite di {limit} osservazioni per gruppo.",
    "power.error.numeric": "Il calcolo della potenza è fuori dall’intervallo numerico supportato.",
    "power.note.design": "L’allocazione A:B fissa il rapporto tra i due gruppi in ogni disegno che la ricerca "
                         "considera: 2:3 significa n A = 2m e n B = 3m. Con Potenza, N è la dimensione del gruppo A.",
    "power.note.effect": "Medie e SD convertono i valori attesi nell’effetto standardizzato. Separa le medie dei "
                         "gruppi con punti e virgola o con a capo; la virgola è il separatore decimale (13,5 è un "
                         "solo valore).",
    "power.note.curve": "La curva mostra la potenza in funzione della numerosità totale per lo stesso disegno, con al "
                        "più 200 punti. L’N scelto è evidenziato; con Dimensione del campione lo è anche la potenza "
                        "desiderata.",
}
