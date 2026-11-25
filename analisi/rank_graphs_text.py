"""English and Italian strings for Mann–Whitney and Wilcoxon rank/difference plots."""

RANK_PLOT = "Plot ranks"
WILCOXON_DIFFERENCES = "Plot paired differences"
RANK_PLOTS = (RANK_PLOT, WILCOXON_DIFFERENCES)
LEGACY_P_METHOD = "__legacy__"

LABEL_KEYS = {
    RANK_PLOT: "rank.field.plot_ranks",
    WILCOXON_DIFFERENCES: "interface.Plot paired differences",
}
CHOICE_KEYS = {
    LEGACY_P_METHOD: "rank.choice.legacy",
}

EN = {
    "rank.field.plot_ranks": "Plot ranks",
    "rank.choice.legacy": "Legacy (original test)",
    "rank.hint.legacy": (
        "This analysis uses a legacy recipe (saved before P value options). Keeping Legacy preserves the original "
        "p-values, statistics, and tables even if you enable graphs."
    ),
    "rank.legacy.migrate_title": "Switch from legacy rank test?",
    "rank.legacy.migrate_body": (
        "Switching from Legacy to exact/normal P value options may change p-values, statistics, and add a Ranks "
        "table when recalculated. Continue?"
    ),
    "rank.plot.mw_title": "Observation ranks",
    "rank.plot.mean_rank": "Rank",
    "rank.plot.signed_ranks_title": "Signed ranks ({policy})",
    "rank.plot.signed_rank": "Signed rank",
    "rank.plot.positive_ranks": "Positive (+)",
    "rank.plot.negative_ranks": "Negative (−)",
    "rank.plot.pratt_zeros": "Zero differences (Pratt)",
    "rank.plot.all_zeros": "All complete pairs have zero difference.",
    "rank.plot.sampled": "Showing {shown} of {total} points (visual reduction only; inference and Ranks use all rows).",
}

IT = {
    "rank.field.plot_ranks": "Grafico dei ranghi",
    "rank.choice.legacy": "Metodo storico (test originale)",
    "rank.hint.legacy": (
        "Questa analisi usa una ricetta storica (anteriore alle opzioni Valore p). Mantenendo Metodo storico "
        "vengono conservati i p-value, le statistiche e le tabelle originali anche attivando i grafici."
    ),
    "rank.legacy.migrate_title": "Cambiare dal test storico?",
    "rank.legacy.migrate_body": (
        "Passando dal Metodo storico alle opzioni esatte/normali, i p-value e le statistiche possono cambiare e "
        "verrà aggiunta la tabella Ranks al ricalcolo. Continuare?"
    ),
    "rank.plot.mw_title": "Ranghi delle osservazioni",
    "rank.plot.mean_rank": "Rango",
    "rank.plot.signed_ranks_title": "Ranghi con segno ({policy})",
    "rank.plot.signed_rank": "Rango con segno",
    "rank.plot.positive_ranks": "Positivi (+)",
    "rank.plot.negative_ranks": "Negativi (−)",
    "rank.plot.pratt_zeros": "Differenze nulle (Pratt)",
    "rank.plot.all_zeros": "Tutte le coppie complete hanno differenza nulla.",
    "rank.plot.sampled": "Mostrati {shown} punti su {total} (solo riduzione visiva; inferenza e Ranks usano tutte le righe).",
}
