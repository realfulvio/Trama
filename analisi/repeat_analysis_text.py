"""Texts of Analysis → Repeat analysis on other sheets…, shared by the classic Tk window and the Qt window.

They live here (``t()``); the shared string table only registers the menu command, so that both menus translate
it like any other entry. Sheet names, column names and analysis labels are literal text of the project: they are
shown as they are, never translated. This module imports ``i18n`` only when called, so ``i18n`` can import it.
"""

_TEXT = {
    "command": ("Repeat analysis on other sheets…", "Ripeti analisi su altri fogli…"),
    "short": ("Repeat on sheets", "Ripeti su fogli"),
    "tip": ("Runs the selected analysis again on other data sheets of this project, with their own columns.",
            "Esegue di nuovo l'analisi selezionata su altri fogli dati di questo progetto, con le loro colonne."),
    "title": ("Repeat analysis on other sheets", "Ripeti analisi su altri fogli"),
    "step": ("Step {number} of 3", "Passo {number} di 3"),
    "page.recipe": ("Recipe", "Ricetta"),
    "page.sheets": ("Sheets and columns", "Fogli e colonne"),
    "page.preview": ("Preview", "Anteprima"),
    "source": ("Source: {sheet} · {name}", "Origine: {sheet} · {name}"),
    "method": ("Method: {method}", "Metodo: {method}"),
    "only": ("Only the selected analysis", "Solo l'analisi selezionata"),
    "follow": ("Also the compatible steps that read its results", "Anche i passaggi a valle compatibili"),
    "follow_none": ("No other analysis reads its results.", "Nessun'altra analisi legge i suoi risultati."),
    "summary": ("What will be repeated", "Cosa verrà ripetuto"),
    "feeds": ("{child} reads {table} of {parent}", "{child} legge {table} di {parent}"),
    "first": ("{name} reads the columns of the sheet", "{name} legge le colonne del foglio"),
    "skipped": ("Not repeated", "Non ripetuto"),
    "skipped_line": ("{name}: {reason}", "{name}: {reason}"),
    "required": ("Columns the recipe reads: {columns}", "Colonne lette dalla ricetta: {columns}"),
    "sheets_hint": ("Choose one or more data sheets, then the column of each sheet for every column of the recipe. "
                    "Only identical names are proposed: choose any other column yourself.",
                    "Scegli uno o più fogli dati, poi per ogni colonna della ricetta la colonna di ciascun foglio. "
                    "Vengono proposti solo i nomi identici: le altre colonne scegliele tu."),
    "sheet_list": ("Data sheets", "Fogli dati"),
    "column_recipe": ("Recipe column", "Colonna della ricetta"),
    "column_target": ("Column of {sheet}", "Colonna di {sheet}"),
    "used_by": ("Used by", "Usata da"),
    "choose": ("Choose a column…", "Scegli una colonna…"),
    "numbers": ("numbers", "numeri"),
    "any": ("any values", "qualsiasi valore"),
    "no_sheet": ("Select a data sheet on the left to choose its columns.",
                 "Seleziona a sinistra un foglio dati per sceglierne le colonne."),
    "ready": ("Ready", "Pronto"),
    "not_chosen": ("Not chosen", "Non scelto"),
    "preview_counts": ("{analyses} analysis(es) will be added to {sheets} sheet(s). Nothing changes until the "
                       "calculation of every copy succeeds.",
                       "Verranno aggiunte {analyses} analisi a {sheets} fogli. Niente cambia finché il calcolo di "
                       "tutte le copie non riesce."),
    "preview_sheet": ("{sheet} — columns: {columns}", "{sheet} — colonne: {columns}"),
    "preview_new": ("new: {name}", "nuova: {name}"),
    "preview_reads": ("new: {name} (reads {table} of {parent})", "nuova: {name} (legge {table} di {parent})"),
    "preview_keeps": ("Existing data, formulas, exclusions, Info, results and graphs stay as they are. Layouts and "
                      "result cell colors stay with the original sheet.",
                      "Dati, formule, esclusioni, Info, risultati e grafici esistenti restano invariati. Layout e "
                      "colori delle celle dei risultati restano del foglio originario."),
    "back": ("< Back", "< Indietro"),
    "next": ("Next >", "Avanti >"),
    "apply": ("Repeat", "Ripeti"),
    "cancel": ("Cancel", "Annulla"),
    "running": ("Repeating the analysis on {sheets} sheet(s)…", "Ripetizione dell'analisi su {sheets} fogli…"),
    "cancelled": ("Repetition cancelled: the project is unchanged.",
                  "Ripetizione annullata: il progetto è invariato."),
    "done": ("Added {analyses} analysis(es) to {sheets} sheet(s).", "Aggiunte {analyses} analisi a {sheets} fogli."),
    "style_dropped": ("The graph format of {count} copy(ies) did not fit the new series and was not reused.",
                      "Il formato grafico di {count} copie non era compatibile con le nuove serie e non è stato "
                      "riutilizzato."),
    "changed": ("The project changed during the calculation: nothing was added. Try again.",
                "Il progetto è cambiato durante il calcolo: non è stato aggiunto nulla. Riprova."),
    "failed": ("Nothing was added. {sheet}: {method} cannot be calculated. {reason}",
               "Non è stato aggiunto nulla. {sheet}: {method} non si può calcolare. {reason}"),
    "select": ("Select an analysis result or graph to repeat.",
               "Seleziona il risultato o il grafico dell'analisi da ripetere."),
    "wait": ("Wait for the current calculation to finish.", "Attendi la fine del calcolo in corso."),
    "no_sheets": ("The project has no other data sheet that can receive the analysis.",
                  "Il progetto non ha altri fogli dati che possano ricevere l'analisi."),
    # Reasons (RepeatError.code)
    "error.origin": ("Select an analysis result or graph to repeat.",
                     "Seleziona il risultato o il grafico dell'analisi da ripetere."),
    "error.reads-result": ("This analysis reads the results of another analysis: repeat the analysis it comes from "
                           "and include the following steps.",
                           "Questa analisi legge i risultati di un'altra analisi: ripeti l'analisi da cui parte "
                           "e includi i passaggi a valle."),
    "error.unsupported": ("{method} cannot be repeated yet. Supported: Transform, Normalize, Descriptive "
                          "statistics, Linear regression and Nonlinear regression.",
                          "{method} non si può ancora ripetere. Sono supportate: Trasforma, Normalizza, Statistica "
                          "descrittiva, Regressione lineare e Regressione non lineare."),
    "error.imported": ("This analysis shows an imported view; analyse the data again first.",
                       "Questa analisi mostra una vista importata: analizza di nuovo i dati prima."),
    "error.external": ("This analysis keeps data of an imported file; analyse the data again first.",
                       "Questa analisi conserva dati di un file importato: analizza di nuovo i dati prima."),
    "error.other-sheet": ("This analysis reads another worksheet.", "Questa analisi legge un altro foglio."),
    "error.other-analysis": ("This graph draws comparisons of another analysis.",
                             "Questo grafico disegna i confronti di un'altra analisi."),
    "error.invalid-options": ("The saved options of this analysis are not valid.",
                              "Le opzioni salvate di questa analisi non sono valide."),
    "error.missing-column": ("The column chosen for {column} is not in {sheet}.",
                             "La colonna scelta per {column} non è in {sheet}."),
    "error.missing-origin": ("The analysis reads columns that are no longer in its sheet.",
                             "L'analisi legge colonne che non sono più nel suo foglio."),
    "error.output": ("It reads a result or a column that the repeated analysis does not provide in every copy.",
                     "Legge un risultato o una colonna che l'analisi ripetuta non fornisce in ogni copia."),
    "error.parent-skipped": ("It reads an analysis that is not repeated.",
                             "Legge un'analisi che non viene ripetuta."),
    "error.unknown-sheet": ("The project has no data sheet named {sheet}.",
                            "Il progetto non ha un foglio dati chiamato {sheet}."),
    "error.source-sheet": ("The recipe already runs on this sheet.", "La ricetta lavora già su questo foglio."),
    "error.read-only": ("This sheet keeps an archived read-only view.",
                        "Questo foglio conserva una vista archiviata di sola lettura."),
    "error.budget": ("The sheet or the project would exceed the analysis limit ({limit}).",
                     "Il foglio o il progetto supererebbe il limite di analisi ({limit})."),
    "error.mapping": ("Choose a column for every column of the recipe.",
                      "Scegli una colonna per ogni colonna della ricetta."),
    "error.unknown-column": ("The recipe does not read a column named {column}.",
                             "La ricetta non legge una colonna chiamata {column}."),
    "error.unmapped": ("Choose the column of {sheet} for {column}.", "Scegli la colonna di {sheet} per {column}."),
    "error.duplicate": ("The column {chosen} of {sheet} is chosen twice.",
                        "La colonna {chosen} di {sheet} è scelta due volte."),
    "error.not-numeric": ("{column} needs numbers; {chosen} of {sheet} contains text.",
                          "{column} richiede numeri; {chosen} di {sheet} contiene testo."),
    "error.formula": ("The formulas of {sheet} cannot be calculated.",
                      "Le formule di {sheet} non si possono calcolare."),
    "error.no-targets": ("Choose at least one data sheet.", "Scegli almeno un foglio dati."),
    "error.changed": ("The project changed while the repetition was prepared: start again.",
                      "Il progetto è cambiato durante la preparazione: ricomincia."),
}


def t(key, **values):
    from .i18n import active_language
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


def method_name(method):
    """The method as the menus show it in the active language."""
    from .i18n import ui
    return ui(method)


def error_text(error):
    """The message of a RepeatError in the active language; unknown codes keep the English text."""
    code = getattr(error, "code", None)
    if code == "missing-column" and "chosen" not in getattr(error, "detail", {}):
        code = "missing-origin"
    key = f"error.{code}"
    if key not in _TEXT:
        return str(error)
    from .i18n import active_language
    values = {"sheet": getattr(error, "sheet", None) or "", "column": getattr(error, "column", None) or "",
              "method": method_name(getattr(error, "method", None) or ""), **getattr(error, "detail", {})}
    if "limit" in values:
        values["limit"] = f"{values['limit']:,}".replace(",", "." if active_language() == "it" else ",")
    try:
        return t(key, **values)
    except (KeyError, IndexError, ValueError):
        return str(error)


def skipped_text(item):
    return t("skipped_line", name=method_name(item.method), reason=error_text(item))
