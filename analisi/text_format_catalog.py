"""Text group (font, size, color, bold, italic, underline, alignment, subscript, superscript): captions.

``analisi.i18n`` merges these tables beside the other worksheet appearance captions. Engine messages stay
English keys (``ValueError`` text of ``analisi.worksheet_text`` and ``analisi.text_markup``), shown through
``translate_message`` with the ``text.error.`` prefix.
"""

MESSAGES = {
    "ribbon.text_group": ("Text", "Testo"),
    "command.text_font": ("Text font…", "Carattere del testo…"),
    "command.text_size": ("Text size", "Dimensione del testo"),
    "command.text_size_other": ("Other size…", "Altra dimensione…"),
    "command.text_bold": ("Bold", "Grassetto"),
    "command.text_italic": ("Italic", "Corsivo"),
    "command.text_underline": ("Underline", "Sottolineato"),
    "command.text_color": ("Text color…", "Colore del testo…"),
    "command.text_align_left": ("Align text left", "Testo a sinistra"),
    "command.text_align_center": ("Center text", "Testo al centro"),
    "command.text_align_right": ("Align text right", "Testo a destra"),
    "command.text_subscript": ("Subscript", "Pedice"),
    "command.text_superscript": ("Superscript", "Apice"),
    "command.text_restore": ("Restore text", "Ripristina testo"),
    "command.text_graph": ("Graph text…", "Testo del grafico…"),
    "command.text_menu": ("Text", "Testo"),
    "text.state.inherited": ("table default", "predefinito della tabella"),
    "text.state.mixed": ("mixed", "misto"),
    "text.state.on": ("on", "attivo"),
    "text.state.off": ("off", "disattivo"),
    "text.tip.font": ("Font: {state}", "Carattere: {state}"),
    "text.tip.size": ("Size: {state}", "Dimensione: {state}"),
    "text.tip.color": ("Color: {state}", "Colore: {state}"),
    "text.tip.align": ("Alignment: {state}", "Allineamento: {state}"),
    "text.tip.graph": ("Opens Format graph for titles, axes and tick labels.",
                       "Apre Formato grafico per titoli, assi e etichette dei valori."),
    "text.align.left": ("left", "sinistra"),
    "text.align.center": ("center", "centro"),
    "text.align.right": ("right", "destra"),
    "text.dialog.title": ("Text font", "Carattere del testo"),
    "text.dialog.keep": ("Keep as it is", "Lascia invariato"),
    "text.dialog.reset": ("Table font", "Carattere della tabella"),
    "text.dialog.reset_size": ("Table size", "Dimensione della tabella"),
    "text.dialog.size_keep": ("Keep as it is", "Lascia invariata"),
    "text.dialog.note": ("Only how the text looks changes: values, formulas, analyses, copy and export keep "
                         "every stored digit.",
                         "Cambia solo l’aspetto del testo: valori, formule, analisi, copia ed export "
                         "conservano tutte le cifre memorizzate."),
    "text.status.applied": ("Text format applied to {cells} cells.", "Formato del testo applicato a {cells} celle."),
    "text.status.restored": ("Text restored on {cells} cells.", "Testo ripristinato su {cells} celle."),
    "text.status.unchanged": ("The text already looks like this.", "Il testo ha già questo aspetto."),
    "text.status.annotation": ("Annotation text formatted.", "Testo dell’annotazione formattato."),
    "text.error.script_selection": ("Select some of the text first.", "Seleziona prima una parte del testo."),
    "text.error.size": ("Choose a text size between {low} and {high} points.",
                        "Scegli una dimensione del testo fra {low} e {high} punti."),
    "text.annotation.group": ("Format", "Formato"),
    "text.annotation.default_font": ("Graph default", "Predefinito del grafico"),
    "text.error.invalid": ("Invalid text formatting.", "La formattazione del testo non è valida."),
    "text.error.script": ("Choose subscript or superscript.", "Scegli pedice o apice."),
}
