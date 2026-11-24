# Applicare uno stile a più grafici (Qt)

**Cambia → Applica stile a più grafici…** (EN *Change → Apply style to multiple graphs…*) applica in un'unica operazione uno stile di figura già salvato nella libreria locale a più grafici scelti nel progetto attivo.

Il comando è disponibile nel menu **Cambia** subito dopo **Stili di figura…** ed è attivo appena il progetto contiene almeno un grafico (anche quando il foglio corrente è una tabella dati, un risultato, un layout o la Galleria) purché non ci sia un calcolo in corso.

## Come funziona

1. Se l'Inspector ha modifiche in bozza non confermate, Trama chiede prima di applicarle, scartarle o annullare, usando lo stesso flusso degli altri comandi di modifica.
2. Il dialogo mostra:
   - **Stili salvati** (a sinistra): la libreria locale di sola lettura (`graph-style-presets.json`) con i campi dello stile scelto. Per salvare, importare, rinominare o eliminare stili si continua a usare **Cambia → Stili di figura…**.
   - **Grafici del progetto** (a destra): elenco di tutti i grafici del progetto con **Grafico**, **Foglio sorgente** e **Stato**, identificati dal loro ID stabile (`Run.uid`) anche se due grafici hanno lo stesso titolo.
   - **Seleziona tutti** / **Deseleziona tutti** e il **conteggio della selezione** (incluso il numero di grafici da aggiornare e quelli già aggiornati).
   - **Mini anteprima**: mostra una copia indipendente del grafico candidato selezionato con lo stile applicato. **Esc** e **Annulla** rimuovono la mini anteprima e lasciano intatti tutti i grafici, il progetto e la libreria.
3. Il grafico attualmente aperto nella finestra viene preselezionato automaticamente se è idoneo.

## Quali grafici sono idonei

- **Idonei**: grafici già calcolati e modificabili secondo il criterio di **Formato grafico** (`Project.graph_format_problem` è `None` e nessun errore di calcolo attivo), inclusi i grafici prodotti da analisi statistiche.
- **Non applicabili (disabilitati con motivo)**:
  - grafici in attesa di calcolo: il motivo spiega di aprire il grafico o eseguire **Ricalcola (F9)**;
  - grafici con errore di calcolo: occorre correggere o ricalcolare prima;
  - anteprime importate statiche non formattabili: riportano lo stesso motivo di Formato grafico.
- **Esclusi dall'elenco**: layout e risultati senza figura. I layout che referenziano grafici aggiornati ricevono automaticamente il nuovo aspetto al ridisegno e all'esportazione.

## Regole di applicazione, atomicità e Annulla/Ripeti

- L'operazione riusa `apply_preset` e l'elenco `TRANSFERABLE` di `trama_qt/graph_style_presets.py` (`accent`, `font_family`, `title_size`, `label_size`, `tick_size`, `legend_size`, `frame`, `grid`, `grid_minor`, `legend`).
- Ogni grafico conserva titolo, etichette, scale e limiti degli assi, colori specifici delle serie e dei gruppi, forme, linee di riferimento, interruzioni, assi collegati, annotazioni e opzioni di legenda per voce.
- **Nessun ricalcolo**: il motore di calcolo non viene mai chiamato durante anteprima, conferma, Annulla o Ripeti.
- **Zero modifiche effettive**: se tutti i grafici selezionati hanno già esattamente quei valori, non avviene alcuna mutazione, il progetto non diventa modificato (`dirty`) e non viene aggiunta nessuna voce alla cronologia Annulla/Ripeti.
- **Validazione preventiva e rollback**: tutte le destinazioni vengono verificate prima della conferma (identità del progetto/run, assenza di modifiche concorrenti e `validate_graph_style`). Se una figura fallisce durante Applica, tutte le figure già ridisegnate vengono ripristinate agli stili confermati, senza alcuna modifica parziale a progetto o libreria.
- **Unica azione Annulla/Ripeti**: la conferma registra un solo passo `StyleBatchChange` nella cronologia di progetto, catturando esclusivamente gli stili prima/dopo dei run effettivamente modificati. Annulla e Ripeti aggiornano in un solo passaggio grafici, Inspector, Galleria, layout e anteprima del foglio dati.
- **Persistenza**: salvando e riaprendo il file `.alab`, tutti i grafici conservano lo stile applicato.

## Note tecniche e pacchetto portabile

- **Contratto motore senza Qt** (`trama_qt/graph_style_presets.py`):
  `plan_preset_batch(styles_by_id, selected_ids, preset)` restituisce un dizionario ordinato secondo `selected_ids` con i soli stili completi cambiati, come copie indipendenti dagli originali. Solleva `ValueError` prima di ogni scrittura se un ID manca o è duplicato.
- **Transazione e cronologia** (`trama_qt/project.py`): `ProjectHistory`, `StyleBatchChange`, `BatchStyleOutcome`, `Project.commit_style_batch` e gestione in `Project.undo`.
- **Dialogo e traduzioni IT/EN** (`trama_qt/batch_figure_styles_dialog.py`): modulo dedicato, nessuna modifica ai cataloghi condivisi e nessuna dipendenza aggiunta.
- **Portabile Windows**: per includere questa guida nell'archivio portabile, aggiungere `"qt-batch-figure-styles.md"` all'elenco dei documenti in `package_windows.py` (accanto a `"qt-graph-style-presets.md"`). Il modulo Python `trama_qt/batch_figure_styles_dialog.py` è importato direttamente da `trama_qt/window.py` e viene raccolto da PyInstaller senza nuove dipendenze.

## Prove

- Verificatore di contratto: `python tests/verify.py --repo /percorso/Trama`
- Test unitari motore: `python -m unittest tests.test_qt_graph_style_presets`
- Test Qt mirati (offscreen): `python -m unittest tests.test_qt_batch_figure_styles`
- Smoke dedicato (1024×768 e 1600×1000, IT/EN, chiaro/scuro, 30 grafici × 1.000 punti):
  `python -m trama_qt.batch_figure_styles_smoke CARTELLA`
- Smoke completo Qt: `python -m trama_qt --smoke CARTELLA`
