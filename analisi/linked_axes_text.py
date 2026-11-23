"""English and Italian text of the linked secondary axes (editor captions, notes and engine messages).

The ``linked_axes.error.`` entries are the exact English messages of ``analisi.linked_axes``;
``i18n.translate_message`` matches them and copies the placeholder values literally.
"""

EN = {
    "linked_axes.button": "Secondary axes…",
    "linked_axes.title": "Linked secondary axes",
    "linked_axes.summary_none": "None",
    "linked_axes.summary.x": "top X",
    "linked_axes.summary.y": "right Y",
    "linked_axes.group.x": "Top X axis",
    "linked_axes.group.y": "Right Y axis",
    "linked_axes.field.label": "Label",
    "linked_axes.field.multiplier": "Multiplier",
    "linked_axes.field.offset": "Offset",
    "linked_axes.formula": "secondary = multiplier × primary + offset",
    "linked_axes.preview": "Reference values: {first} → {second}, {third} → {fourth}",
    "linked_axes.preview_invalid": "Reference values: enter a multiplier and an offset first.",
    "linked_axes.hint.label": "Up to 160 characters. Unicode, µ and $math$ are accepted.",
    "linked_axes.hint.log": "Logarithmic scale: only a change of unit is allowed, so the offset stays 0.",
    "linked_axes.hint.intro": (
        "The same coordinate shown in a second unit. No series, data or analysis changes. "
        "The secondary axis follows pan, zoom, inversion and recalculation of the primary axis."),
    "linked_axes.unavailable": "Not available: {reason}",
    "linked_axes.status.ignored": "Secondary axes are saved but not drawn: {reason}",
    "linked_axes.status.on": "Secondary axes: {items}",
    "linked_axes.note.graph": "Not available for this graph: {reason}",
    "linked_axes.btn.ok": "Apply",
    "linked_axes.btn.cancel": "Cancel",
    "linked_axes.error.type": "Linked axes need an X and/or a Y record with a multiplier, an offset and a label.",
    "linked_axes.error.multiplier": "Linked {axis} axis: enter a finite multiplier greater than 0.",
    "linked_axes.error.offset": "Linked {axis} axis: enter a finite offset.",
    "linked_axes.error.label": (
        "Linked {axis} axis: the label takes up to 160 characters, without line breaks or control characters."),
    "linked_axes.error.log_offset": (
        "Linked {axis} axis: on a logarithmic scale only a change of unit is allowed, so the offset must be 0."),
    "linked_axes.error.range": (
        "Linked {axis} axis: with this multiplier and offset the limits of the axis overflow or collapse."),
    "linked_axes.error.support": (
        "Linked axes are available for XY series, XY error bars, regression and survival curves, "
        "and for the value axis of column and grouped graphs."),
    "linked_axes.error.native": "Linked axes need a native graph, not an imported picture.",
    "linked_axes.error.categorical": "Linked axes need a numeric {axis} axis.",
    "linked_axes.error.scale": "Linked axes need a linear or logarithmic {axis} axis.",
    "linked_axes.error.breaks": "Linked axes cannot be combined with axis breaks. Remove the axis breaks first.",
    "linked_axes.error.right": (
        "A linked right Y axis cannot be combined with an independent right Y axis. "
        "Move every series to the left axis first."),
    "linked_axes.error.panels": "Linked axes need a graph with a single plot panel.",
    "linked_axes.error.p_log_offset": (
        "On a logarithmic {axis} axis a linked axis only changes the unit: the offset must be 0."),
    "linked_axes.error.p_range": (
        "The linked {axis} axis cannot show this range: the converted limits overflow or collapse."),
    "linked_axes.error.failed": "The linked axes could not be drawn ({kind}: {message}).",
}

IT = {
    "linked_axes.button": "Assi secondari…",
    "linked_axes.title": "Assi secondari sincronizzati",
    "linked_axes.summary_none": "Nessuno",
    "linked_axes.summary.x": "X superiore",
    "linked_axes.summary.y": "Y destro",
    "linked_axes.group.x": "Asse X superiore",
    "linked_axes.group.y": "Asse Y destro",
    "linked_axes.field.label": "Etichetta",
    "linked_axes.field.multiplier": "Moltiplicatore",
    "linked_axes.field.offset": "Scostamento",
    "linked_axes.formula": "secondario = moltiplicatore × principale + scostamento",
    "linked_axes.preview": "Valori di riferimento: {first} → {second}, {third} → {fourth}",
    "linked_axes.preview_invalid": "Valori di riferimento: inserisci prima un moltiplicatore e uno scostamento.",
    "linked_axes.hint.label": "Fino a 160 caratteri. Sono accettati Unicode, µ e $formule$.",
    "linked_axes.hint.log": "Scala logaritmica: è ammesso solo il cambio di unità, quindi lo scostamento resta 0.",
    "linked_axes.hint.intro": (
        "La stessa coordinata mostrata in una seconda unità. Nessuna serie, dato o analisi cambia. "
        "L’asse secondario segue spostamento, zoom, inversione e ricalcolo dell’asse principale."),
    "linked_axes.unavailable": "Non disponibile: {reason}",
    "linked_axes.status.ignored": "Gli assi secondari sono salvati ma non disegnati: {reason}",
    "linked_axes.status.on": "Assi secondari: {items}",
    "linked_axes.note.graph": "Non disponibili per questo grafico: {reason}",
    "linked_axes.btn.ok": "Applica",
    "linked_axes.btn.cancel": "Annulla",
    "linked_axes.error.type": (
        "Gli assi secondari richiedono un record X e/o Y con moltiplicatore, scostamento ed etichetta."),
    "linked_axes.error.multiplier": "Asse {axis} collegato: inserisci un moltiplicatore finito maggiore di 0.",
    "linked_axes.error.offset": "Asse {axis} collegato: inserisci uno scostamento finito.",
    "linked_axes.error.label": (
        "Asse {axis} collegato: l’etichetta ha al massimo 160 caratteri, senza a capo né caratteri di controllo."),
    "linked_axes.error.log_offset": (
        "Asse {axis} collegato: su scala logaritmica è ammesso solo il cambio di unità, "
        "quindi lo scostamento deve essere 0."),
    "linked_axes.error.range": (
        "Asse {axis} collegato: con questo moltiplicatore e scostamento i limiti dell’asse "
        "vanno in overflow o si schiacciano."),
    "linked_axes.error.support": (
        "Gli assi secondari sono disponibili per serie XY, barre d’errore XY, curve di regressione e di "
        "sopravvivenza e per l’asse dei valori dei grafici a colonne e raggruppati."),
    "linked_axes.error.native": "Gli assi secondari richiedono un grafico nativo, non un’immagine importata.",
    "linked_axes.error.categorical": "Gli assi secondari richiedono un asse {axis} numerico.",
    "linked_axes.error.scale": "Gli assi secondari richiedono un asse {axis} lineare o logaritmico.",
    "linked_axes.error.breaks": (
        "Gli assi secondari non si combinano con le interruzioni dell’asse. Rimuovi prima le interruzioni."),
    "linked_axes.error.right": (
        "Un asse Y destro collegato non si combina con un asse Y destro indipendente. "
        "Sposta prima tutte le serie sull’asse sinistro."),
    "linked_axes.error.panels": "Gli assi secondari richiedono un grafico con un solo pannello.",
    "linked_axes.error.p_log_offset": (
        "Su un asse {axis} logaritmico l’asse collegato cambia solo l’unità: lo scostamento deve essere 0."),
    "linked_axes.error.p_range": (
        "L’asse {axis} collegato non può mostrare questo intervallo: i limiti convertiti vanno in "
        "overflow o si schiacciano."),
    "linked_axes.error.failed": "Gli assi secondari non si sono potuti disegnare ({kind}: {message}).",
}
