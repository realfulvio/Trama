# Modelli di analisi riutilizzabili (Qt)

Un modello di analisi salva la **procedura** di un progetto (fogli dati con le loro colonne, formule, analisi collegate, opzioni, stili dei grafici e layout) **senza le osservazioni**. Si riapplica poi a dati nuovi: Trama ricostruisce le stesse analisi e gli stessi layout su un progetto nuovo.

Il file ha estensione `.tramatpl` ed è JSON leggibile (schema 1).

## Salvare un modello

**File → Salva come modello…** (inglese: File → Save as analysis template…), anche dal gruppo File della barra comandi.

1. Il dialogo mostra un'anteprima di cosa entra nel modello (fogli, colonne, formule, analisi con il foglio che leggono, layout) e di cosa resta fuori:
   - le righe di dati e le celle escluse (contate, non copiate);
   - i fogli Info e il loro testo;
   - forme e annotazioni disegnate sui grafici.
2. Scegli il file. Il nome proposto è quello del progetto con `.tramatpl`, nella stessa cartella. Non si può scrivere sopra il progetto aperto né sopra un progetto aperto in un'altra scheda, anche passando da un collegamento.
3. **Salva** scrive il file in modo atomico: o il file nuovo completo, o nessun cambiamento. Chiudere il dialogo non scrive nulla. Il progetto non risulta modificato.

Il salvataggio è bloccato, con il motivo scritto nel dialogo, quando il progetto contiene qualcosa che il modello non sa ricostruire:

- tabelle, analisi o layout importati da progetti esterni (restano disponibili solo come viste);
- una formula che legge un foglio Info;
- un'analisi con metodo sconosciuto, opzioni non valide o una colonna che non esiste più;
- collegamenti tra analisi rotti o circolari.

Il tempo di salvataggio non dipende da quante righe hanno i fogli: il modello contiene solo intestazioni e procedura.

## Creare un progetto da un modello

**File → Nuovo progetto da modello…** (File → New project from template…).

1. Scegli il `.tramatpl`. Un file danneggiato (schema sconosciuto, chiavi doppie, campi mancanti, formule non valide, collegamenti circolari) viene rifiutato con il motivo e non apre nulla.
2. Si apre l'assistente. Per ogni foglio del modello:
   - scegli la **sorgente**: un foglio del progetto attivo oppure un file CSV/TSV aggiunto con **Aggiungi CSV/TSV…** (la lettura avviene in background, l'assistente resta usabile). Un foglio viene proposto da solo solo se ha esattamente lo stesso nome;
   - nella griglia assegna a ogni colonna del modello una colonna della sorgente. Le proposte automatiche valgono solo per nomi identici e univoci.
3. Il riepilogo dice quanti campi sono assegnati e quali colonne della sorgente restano ignorate. Le colonne calcolate da formule non si assegnano: vengono dal modello.
4. **Crea progetto** controlla la mappatura. Se c'è un errore (colonna assegnata due volte, campo richiesto vuoto, colonna non numerica dove serve un numero) il messaggio compare sopra la griglia e il focus va sul campo da correggere.
5. Il progetto nasce in una **scheda nuova** (o nella scheda vuota iniziale, se c'è), senza nome e con il • delle modifiche non salvate. Si salva con **Salva con nome** come `.alab`. Il progetto di partenza e le sue schede non cambiano.

Durante la costruzione **Annulla calcolo** ferma tutto: nessuna scheda viene creata. Se le schede sono già 6 il comando è disabilitato (a meno che la scheda attiva sia vuota).

Ogni applicazione dà alle analisi identificativi nuovi: applicare due volte lo stesso modello produce progetti indipendenti, con identificativi che non si incrociano.

Se un'analisi non riesce a calcolare con i dati nuovi, Trama lo dice indicando anche il foglio che legge (per esempio "Normalize, che legge Transformed"). Corretti i dati, il ricalcolo è quello normale.

## Cosa copia e cosa no

| Nel modello | Fuori dal modello |
| --- | --- |
| Nomi e formati dei fogli, nomi e tipi delle colonne, ruoli | Righe di dati, celle escluse |
| Formule delle colonne | Fogli Info, testo e variabili |
| Analisi, opzioni, etichette, foglio sorgente | Forme e annotazioni sui grafici |
| Stili dei grafici (Format Graph) | Risultati calcolati |
| Layout: pannelli, colonne, carta, sfondo | Percorso e nome del progetto originale |

Quando la sorgente è un foglio del progetto attivo, Trama copia i valori come li vede il foglio: le formule della sorgente diventano valori e le esclusioni non passano nel progetto nuovo.

## Per chi sviluppa

- Motore: `analisi/analysis_templates.py` (`write_template`, `read_template`, `instantiate_template`, più `plan_template` e `mapping_problems`). Nessuna dipendenza da Qt.
- Interfaccia: `trama_qt/templates.py` (dialogo di salvataggio, assistente, testi EN/IT nel dizionario locale `_TEXT`).
- Test: `tests/test_analysis_templates.py` (motore) e `tests/test_qt_templates.py` (flusso Qt offscreen).
- Smoke dedicato: `python -m trama_qt --smoke CARTELLA --only qt-analysis-templates` (EN/IT, tema chiaro e scuro). Lo smoke completo `python -m trama_qt --smoke CARTELLA` lo include una volta.
