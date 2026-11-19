"""Settings → Multicore calculation…: interface text (English and Italian)."""

EN = {
    "processes.command": "Multicore calculation…",
    "processes.title": "Multicore calculation",
    "processes.auto": "Automatic: {count} processes on this computer",
    "processes.single": "One process only (as in earlier versions)",
    "processes.fixed": "Fixed number of processes:",
    "processes.processors": "This computer has {count} logical processors.",
    "processes.note": ("Several processes compute independent analyses and the heavier k-means scans at the same "
                       "time. The results are the same with any number of processes. Each process uses about "
                       "150 MB of memory."),
    "processes.ok": "OK", "processes.cancel": "Cancel",
    "processes.saved": "Multicore calculation saved: {count} processes.",
    "processes.invalid": "Enter a whole number from 1 to {maximum}.",
    "processes.error": "The multicore preference could not be saved: {error}",
}

IT = {
    "processes.command": "Calcolo multicore…",
    "processes.title": "Calcolo multicore",
    "processes.auto": "Automatico: {count} processi su questo computer",
    "processes.single": "Un solo processo (come nelle versioni precedenti)",
    "processes.fixed": "Numero fisso di processi:",
    "processes.processors": "Questo computer ha {count} processori logici.",
    "processes.note": ("Più processi calcolano insieme le analisi indipendenti e le scansioni k-means più pesanti. "
                       "I risultati sono gli stessi con qualsiasi numero di processi. Ogni processo usa circa "
                       "150 MB di memoria."),
    "processes.ok": "OK", "processes.cancel": "Annulla",
    "processes.saved": "Calcolo multicore salvato: {count} processi.",
    "processes.invalid": "Inserisci un numero intero da 1 a {maximum}.",
    "processes.error": "Impossibile salvare la preferenza del calcolo multicore: {error}",
}
