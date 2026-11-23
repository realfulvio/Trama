# Consegna Qt per Codex

Questo file è il canale fisso tra Claude e Codex per la migrazione a Qt (PR #56, ramo `claude/project-thread-4unaln`).
Claude lo aggiorna a ogni commit; la voce più recente sta in cima. Il piano complessivo è in `docs/qt-migration.md`.

## Procedura per Codex, a ogni avanzamento

1. `git fetch origin claude/project-thread-4unaln && git checkout claude/project-thread-4unaln && git pull --ff-only`
2. Leggi la voce più recente qui sotto (e quelle che non hai ancora visto, confrontando il commit).
3. Test: `python -m unittest tests.test_qt_shell` (offscreen; su Windows imposta `QT_QPA_PLATFORM=offscreen` solo per i test) più la tua suite completa.
4. Prova a mano su Windows quello che la voce indica in "Da provare su Windows", a 100% e 150% di scala, e lancia `python -m trama_qt --smoke CARTELLA` alle due scale.
5. Rispondi con un commento sulla PR #56 (o scrivilo a Luca): commit provato, esito dei test, problemi con passi per riprodurli.

Regole fisse: niente merge e niente cambio di versione da parte di Claude; la grafica nuova si fa solo su Qt (il Vetro su Tk è fermo); `trama_qt` non deve importare `tkinter`; Windows resta NON PROVATO finché Codex non lo conferma.

## Avanzamenti

### Assi secondari sincronizzati, pacchetto 0.99 (ramo `claude/assi-secondari`, base main `ba445f5`, 2026-11-23)

PR draft verso main, in tre gruppi di commit: motore con test, dialogo Qt con Formato grafico e Ispettore, smoke con prestazioni e guida. Windows e scala di sistema: **NON PROVATI** (collaudo solo offscreen su Linux). Guida: `docs/linked-axes.md`.

- Nuovo: Formato grafico → Assi → **Assi secondari…** e Ispettore → Assi → **Assi secondari…** mostrano la stessa coordinata in un’altra unità (`secondario = moltiplicatore × principale + scostamento`) sull’asse X superiore e/o Y destro. Solo presentazione: dati, fogli, calcoli, ricette e tabelle non cambiano. Grafici supportati: serie XY, barre d’errore XY, fit globali XY, regressioni (lineare, Deming, non lineare, robusta, equazione personalizzata e globale, spline/LOWESS, confronto di rette), Kaplan–Meier (anche con la tabella a rischio) e, solo Y, Column e Grouped.
- Motore: `analisi/linked_axes.py` (record `linked_axes` a chiavi esatte `x`/`y` → `multiplier`, `offset`, `label`; moltiplicatore finito > 0, scostamento finito, etichetta ≤ 160 caratteri; `LinkedAxesError` con asse e campo; `AffineMap` picklabile e sempre finita; conflitti e motivi) e `analisi/linked_axes_text.py` (EN/IT, i messaggi del motore sono le stesse stringhe tradotte da `translate_message`). `apply_style` disegna veri assi secondari di Matplotlib (figli dell’Axes del grafico, id SVG `trama-linked-x` e `trama-linked-y`): i limiti si ricalcolano a ogni disegno dall’asse principale, quindi spostamento, zoom, inversione, ripristino e ricalcolo li seguono senza callback. Formattare venti volte non lascia mai più di due assi secondari.
- Conflitti: un asse che il grafico non può mostrare (tipo non supportato, immagine importata, asse categorico o con unità, scala diversa da lineare/logaritmica, **interruzioni dell’asse attive**, **asse Y destro indipendente** per l’Y, più pannelli, intervallo che va in overflow o si schiaccia) resta nello stile ma non viene disegnato; la barra di stato e l’Ispettore dicono perché. In Formato grafico gli stessi casi disattivano i controlli di quell’asse con il motivo accanto e non si può accendere un asse già salvato su un grafico che non lo mostra. Su scala logaritmica lo scostamento è 0 (il dialogo lo blocca e lo spiega); uno stile che sceglie il logaritmo con uno scostamento è un errore.
- Qt: `trama_qt/linked_axes.py` (dialogo: un gruppo per asse, anteprima «Valori di riferimento» sul primo e ultimo valore principale visibile, virgola decimale, errore sul campo con focus), blocchi in `trama_qt/graph_format.py` e `trama_qt/inspector.py` (anteprima sul grafico vivo, Applica/Annulla/Ripristina sezione), `trama_qt/project.py` (`graph_warning` unisce le note delle interruzioni e degli assi secondari). Tk: nessun editor; `graph_dialog.py` conserva il record quando formatta un grafico.
- Kaplan–Meier: cambiando *Curve* o *Display units* il record dell’asse Y destro cade (la grandezza è cambiata), quello dell’X resta. Con la colonna Y di una serie XY cambiata il record resta: è l’unità dichiarata dall’utente.
- Test: `tests/test_linked_axes.py` (33: record, conversioni, disegno su ogni grafico supportato, conflitti, limiti estremi, zoom oltre ogni limite, pickle, esportazioni PNG/SVG/PDF e layout, parità del catalogo IT/EN), `tests/test_qt_linked_axes.py` (16, offscreen). Smoke dedicato: `python -m trama_qt.linked_axes_smoke CARTELLA [--dark] [--size LARGHEZZAxALTEZZA]` (con `--size` emula lo schermo a 100%). Prestazioni: `python tests/perf_linked_axes.py [FILE]`.
- Prestazioni su 10.000 punti (Agg, impaginazione automatica): ridisegno 50 → 121 ms con entrambi gli assi (punti) e 82 → 132 ms (linea e punti); l’aggiunta dipende dai due assi, non dai punti.
- Da provare su Windows, a 100% e 150%: lo smoke dedicato chiaro e scuro; su un XY aprire Formato grafico → Assi → Assi secondari…, accendere X superiore (°C → °F: 1,8 e 32) e Y destro, Applica; zoom e spostamento con la barra del grafico; scala logaritmica sull’X (scostamento bloccato a 0); serie sull’asse destro (Y destro non disponibile, X sì); esportare PNG, SVG e PDF; salvare e riaprire.
- Packaging: aggiungere `linked-axes.md` ai docs di `package_windows.py` (non toccato qui, come `precision-recall.md`).
- Conflitti attesi con le altre PR 0.99: `analisi/workbench.py` (`analyse` diventa un involucro attorno a `_analyse`: stesso corpo e stessa firma), `analisi/presentation.py` (import, chiavi di `validated_style`, `validate_graph_style`, `apply_style`), coda di `analisi/i18n.py`, `trama_qt/graph_format.py`, `trama_qt/inspector.py`, `trama_qt/project.py`, `docs/features.md`, `docs/coverage.md` e questa voce in cima al file.

### Curva precisione–richiamo per punteggi esterni, pacchetto 0.97 (ramo `claude/precisione-richiamo`, base main `df1d591`, 2026-11-20)

PR draft verso main, in tre gruppi di commit: motore con test, dialogo Qt con catalogo IT, smoke con guida ed esempio. Windows: vedi la PR per l'esito del collaudo sul desktop reale. Guida: `docs/precision-recall.md`.

- Nuovo: Analizza → Confronto tra gruppi → **Curva precisione–richiamo** (*Precision–recall curve*). Motore `analisi/precision_recall.py`: esito con etichette Positive/Negative scritte dall'utente (confronto letterale: `01` ≠ `1`), uno o due punteggi con verso a scelta, tutte le soglie distinte con i pari merito contati insieme, TP/FP/TN/FN, Precision, Recall, average precision senza interpolazione. Soglie e AP vengono dalle stesse funzioni della validazione logistica (`curve_points`, `average_precision`, `roc_auc` di `analisi/logistic_validation.py`, non modificato): ricette, tabelle e grafico della logistica sono identici prima e dopo (hash di tutte le tabelle e dell'SVG).
- Righe: con due punteggi si usano solo le righe complete per entrambi; le altre vanno in *Excluded rows* con la riga fisica. Un'etichetta estranea è un errore su Outcome con la prima riga; una sola classe, un punteggio non finito, il budget sono errori sul campo.
- Bootstrap appaiato (opzionale, anche con un punteggio): stratificato per esito, stessi indici per A e B, `Generator(PCG64(seed))` con seme fino a 2^64−1, 199–10.000 repliche, quantili lineari; ordine canonico delle righe per classe, quindi le repliche non dipendono dall'ordine del foglio. Budget repliche × campioni ≤ 20.000.000 posizioni (interpretazione di «valori ricampionati»: le posizioni estratte, gli stessi indici servono i due punteggi), controllato prima di estrarre. Annullabile sul worker Qt tra un blocco e l'altro. Non usa il pool multicore: 10.000 repliche su 2.000 campioni ≈ 1,2 s.
- Qt: `trama_qt/precision_recall.py` e una dozzina di righe in `analysis_dialog.py` (come il binding di Bland–Altman per coppie ripetute): le etichette Positive/Negative stanno nella pagina Variabili accanto a Outcome, riga di conteggio live (campioni comuni, positivi, prevalenza) senza banner d'errore, Second direction solo con il secondo punteggio, livello/repliche/seme solo con Bootstrap CI, controlli del motore al Run prima del worker con focus sul campo, messaggi IT in `analisi/precision_recall_catalog.py` (unito in coda a `interface_catalog.py`).
- Figura: gradini la cui area è l'AP, partenza convenzionale (0,1) non nelle soglie, riga della prevalenza, legenda sotto gli assi con AP e intervalli; nessuna banda. Linee con gid `precision-recall:*`, esportabile in PNG/SVG/PDF come i grafici nativi.
- Test: `tests/test_precision_recall.py` (42, oracolo del pacchetto con frazioni esatte, bootstrap contro la sequenza documentata, permutazione righe, punteggi identici, etichette `01`/`1`, classe unica, infinito, budget, annullamento), `tests/test_qt_precision_recall.py` (13, offscreen), caso nuovo in `tests/test_catalog.py`. Smoke dedicato: `python -m trama_qt.precision_recall_smoke CARTELLA [--dark]`. Dati sintetici in `tests/data/precision_recall/`, esempio `docs/examples/Precisione-Richiamo.alab`.
- Da provare su Windows, a 100% e 150%: lo smoke dedicato chiaro e scuro; aprire `docs/examples/Precisione-Richiamo.alab`, Cambia parametri, scrivere un'etichetta Positive sbagliata (errore con riga, focus su Outcome), Bootstrap CI con 100 repliche (errore sul campo), poi 10.000 repliche e Annulla calcolo; esportare il grafico in SVG e PDF.
- Packaging: aggiungere `precision-recall.md` ai docs di `package_windows.py` (non toccato qui).
- Nota: il nome proposto per l'export CSV dei fogli «Thresholds: NOME» contiene i due punti (e, con colonne come «U/mL», la barra), come già «Parameters: …» di Fit custom equation. Non ho toccato `window.py`.
- Conflitti attesi con le altre PR 0.97: `analisi/workbench.py` (import, `METHODS`, gruppo Confronto tra gruppi, `GRAPH_METHODS`, dispatcher), coda di `analisi/interface_catalog.py`, `trama_qt/analysis_dialog.py` (import, `__init__`, `configure_fields`, `accept`, `_message`), `tests/test_catalog.py`, `docs/features.md` e questa voce in cima al file.
### ANOVA a misure ripetute: correzioni Huynh–Feldt e Limite inferiore (ramo `claude/anova-sfericita-hf`, base main `df1d591`, 2026-11-20)

Pacchetto ANOVA-Sfericita-HF, in tre commit: motore con test, dialogo Qt, smoke con guida. Provato su un PC Windows 10 fisico, con i limiti indicati sotto: 150% di scala e due monitor restano NON PROVATI.

- Nuovo: in Analizza → Confronto tra gruppi → ANOVA a misure ripetute le scelte di *Sphericity correction* diventano None, Geisser–Greenhouse, **Huynh-Feldt** e **Lower bound** (*Limite inferiore* in italiano), per uno o due fattori. I valori di ricetta restano in inglese, con il trattino ASCII in Huynh-Feldt. Guida `docs/rm-anova-sphericity.md`: esempi su due dataset sintetici, limiti, perché stimare ε non è un test di sfericità (nessun test di Mauchly).
- Motore: `analisi/rm_sphericity.py` (`huynh_feldt`, `applied_epsilon`) e `repeated_measures_anova` in `analisi/inference.py`. Lower bound: ε = 1/d (df 1 e n − 1). Huynh–Feldt: (n·d·ε − 2) / (d·(n − 1 − d·ε)) dall'ε di Greenhouse–Geisser dell'effetto, limitato a [1/d, 1] con una nota che conserva il valore non limitato. Con d = 1 ε vale esattamente 1. Se il denominatore si annulla (n = 2, oppure autovalori uguali con n − 1 ≤ d) Huynh–Feldt è indefinito per quel solo effetto: ε, df e p restano vuoti e la nota dice perché, gli altri effetti e il Lower bound conservano i numeri. F, somme dei quadrati e termini d'errore non cambiano. Il foglio ANOVA riceve la colonna `Applied epsilon`; il foglio Sphericity delle due scelte nuove ha `Correction`, `Applied epsilon` e `Note`, anche con un solo fattore. None e Geisser–Greenhouse non cambiano di una cifra.
- Qt: `trama_qt/rm_sphericity_dialog.py` (nota sotto il campo che segue la scelta, etichetta «ricetta salvata» della vecchia scelta a una via, controllo del disegno sul campo prima di avviare il worker, messaggio nella lingua attiva quando un errore del motore riapre il dialogo) e dieci righe in `trama_qt/analysis_dialog.py`, negli stessi punti dei binding di K-means stability e Bland–Altman per coppie ripetute.
- Test: `tests/test_rm_sphericity_hf.py` (27: formule chiuse da basi di Helmert, secondo dataset sintetico contro R 4.3.3 `anova.mlm(test = "Spherical")` in `tests/data/rm_sphericity` con lo script che ha prodotto il file, casi degeneri, invarianti, validazione, testi), `tests/test_qt_rm_sphericity.py` (12, offscreen). Aggiornati i test del dialogo Tk e lo smoke Tk, che fissavano le due scelte di prima. Smoke Qt: `python -m trama_qt.rm_sphericity_smoke CARTELLA [--dark]`. Il verificatore del pacchetto passa sul candidato (8 righe di oracolo e 8 del dispatcher) e fallisce sulla base con «Choose None or Geisser–Greenhouse.».
- Provato su Windows 10 fisico (Python 3.13, PySide6 6.12.0, schermo 1920×1080 a 96 DPI, 100%): smoke Qt sul desktop reale in chiaro e scuro, inglese e italiano, 0 differenze da R; smoke Tk `rm-two-way-sphericity` PASS; i quattro moduli di test del pacchetto (80 test) OK. Suite completa e confronto con la base sulla stessa macchina: nella descrizione della PR.
- Da provare su Windows, a 100% e 150%:
  - Aprire il dialogo ANOVA a misure ripetute, scheda Opzioni, scegliere con la tastiera Huynh-Feldt e Lower bound: la nota sotto il campo resta visibile a 1024×768 e in tema scuro.
  - Su `tests/data/rm_sphericity/second-dataset.csv` (Response = Value, Factors = Time e Dose, Subject = Subject): Time con Huynh-Feldt ha ε 0,9692, df 2,908 e 20,35, p 9,53e−06; Dose è limitato a 1 con la nota; Time:Dose ha p 0,7519. Con Lower bound Time ha p 4,30e−03.
  - Togliere una riga dei dati e rieseguire: il dialogo resta aperto con il messaggio sul campo Soggetto, in italiano e in inglese.
- Conflitti attesi: `analisi/rm_sphericity.py`, `repeated_measures_anova` in `analisi/inference.py`, `analisi/i18n.py`, coda di `analisi/interface_catalog.py`, `tramastat.py` (`show_sphericity_note`), `trama_qt/analysis_dialog.py` (punti dei binding K-means stability e Bland–Altman ripetuti), `docs/coverage.md` e la cima di questo file.

### Ordine ottimale delle foglie nei dendrogrammi, pacchetto Dendrogrammi-Ordine-Foglie (ramo `claude/dendrogrammi-ordine-foglie`, base main `df1d591`, 2026-11-20)

PR draft verso main, in tre commit: motore e regressioni, integrazione Qt, smoke e guida. Guida: `docs/leaf-ordering.md`. Provato su un PC fisico Windows 10 (Python 3.13, PySide6 6.12.0, schermo 1920×1080 a 96 DPI, 100%): suite completa 4139 test OK contro 4111 sulla base, smoke dedicato sul desktop reale in chiaro e scuro, smoke generale nella sessione interattiva con profilo isolato. 150% di scala e due monitor restano NON PROVATI.

- Nuovo campo **Leaf ordering** (*Ordine delle foglie*) del raggruppamento gerarchico, `Default` (anche se la chiave manca: figure e fogli storici invariati) oppure `Optimal`. Il motore è `analisi/leaf_order.py`: programmazione dinamica esatta di Bar-Joseph, Gifford e Jaakkola sul fit già calcolato (nessun secondo clustering), prodotti min-plus a blocchi con GIL rilasciato e annullamento fra un blocco e l'altro. `scipy.cluster.hierarchy.optimal_leaf_ordering` non basta: con scipy 1.18.1 non dà sempre il minimo (caso `FOUR` in `tests/test_leaf_order.py`: 3,727 contro 3,192) e tiene il GIL.
- Fogli con Optimal: `Row leaf order`, `Column leaf order` (Position, Label, Input index, Distance from previous) e `Leaf order costs` (Leaves, Original cost, Final cost). L'identità della foglia è l'indice in ingresso, mai l'etichetta. Le assegnazioni ai gruppi restano quelle del fit.
- Limite 2000 foglie per asse, controllato in `check_leaf_options` prima di qualsiasi matrice e dal dialogo (`trama_qt/analysis_dialog.py`, `accept`): errore sul campo, in inglese e in italiano. Misure in guida (2000 foglie: 2,6 s e 234 MB di picco).
- `hierarchical_result(..., cancel=)` riceve il controllo di annullamento da `workbench.analyse`; un ricalcolo annullato non sostituisce il risultato precedente.
- Corretto un bug **già presente nella base**: un dendrogramma (non la mappa di calore) con più di 55 foglie e etichette «Values» dava `IndexError` in `_draw_tree`, perché `names` veniva sovrascritto con le sole etichette mostrate prima di registrare i metadati. Test: `test_a_long_dendrogram_keeps_every_leaf_caption_in_the_registered_metadata`.
- Nuovo smoke dedicato: `python -m trama_qt.leaf_order_smoke CARTELLA` (con `--dark`). In inglese e in italiano: dialogo, tasto Giù sul campo, limite rifiutato su 2100 righe, esecuzione su righe e colonne, celle della mappa nell'ordine del foglio, grafico collegato girato in orizzontale senza un secondo clustering (`hierarchical` bloccato durante il calcolo), layout a due pannelli Default/Optimal, esportazioni PNG/SVG/PDF, modifica ed esclusione di una cella, salva e riapri, annullamento su 1200 foglie. Scrive screenshot, `report.txt` e `status.txt`.
- Fixture sintetica: `tests/data/leaf_order/profili-sintetici.csv` (7 righe, 5 variabili; costi 559 → 520 righe, 519 → 492 colonne).
- Da provare su Windows (Codex): lo smoke dedicato a 100% e 150%, chiaro e scuro; Analizza → Raggruppamento gerarchico con Ordine delle foglie *Ottimale* sulla fixture; Esporta SVG/PDF; Annulla su una tabella da 1200+ righe.
- Conflitti attesi: coda di `analisi/interface_catalog.py` (quattro righe), `analisi/hierarchical_workbench.py` (opzioni e `hierarchical_result`), import e `accept` di `trama_qt/analysis_dialog.py`, e questa voce in cima al file.

### Cartelle Excel: Importa cartella Excel… / Esporta cartella Excel…, pacchetto Excel-Completo-Qt (2026-11-19)

PR draft verso main (ramo `claude/project-thread-mq7akh`, base main `4c07db6`). Windows NON PROVATO. Guida:
`docs/qt-excel-workbook.md`.

- Motore `analisi/xlsx_exchange.py` (senza Qt): `inspect_workbook`, `read_workbook(path, {foglio: riga o None})`,
  `write_workbook(path, [(nome, frame)], overwrite=False)`, più `WorkbookReader` (anteprime e lettura con un solo
  handle) e `prepare_workbook` → `publish`/`discard`. Il lettore storico `analisi.data.load_tables` non cambia.
- Qt `trama_qt/excel_workbook.py`: due azioni nel gruppo File (`import_excel`, `export_excel`), dialoghi
  `ExcelImportDialog` ed `ExcelExportDialog`, lavoro sul worker della finestra con avanzamento e Annulla. Testi
  EN/IT nel modulo (nessuna voce in `strings.py`).
- Smoke dedicato: `python -m trama_qt --smoke CARTELLA --scenario qt-excel-workbook` (preferenze nella cartella,
  tema da `TRAMA_THEME`, predefinito chiaro). Il giro completo `--smoke` lo esegue anche, prima del canvas; le misure
  50.000×20 solo nella prima lingua.
- Da provare su Windows, a 100% e 150%:
  - Smoke dedicato in chiaro e scuro; guardare `en-/it-excel-*.png` e `excel-timings.txt` (tempi e memoria di picco
    reali).
  - A mano: Importa cartella Excel… su `quaderno-multifoglio.xlsx` (nello smoke, cartella `excel-en`): Appunti non
    spuntato, Vuoto non selezionabile, riga 2 per Controlli, riga 9 → errore e Importa spento. Mouse e tastiera
    (spazio sulle caselle, frecce, Tab fino a Importa).
  - Esporta cartella Excel… con due fogli dati e due tabelle risultato, Su/Giù e Alt+↑/↓, Invio = Esporta;
    aprire il file in Excel (nessuna formula, `0007` e `=letterale` come testo); riesportare sullo stesso file con
    Excel aperto su quel file: errore, file intatto, nessun `.~trama-*.xlsx` rimasto.
  - Apri, salva .alab, riapri: i fogli importati tengono tipi (testo, numeri, booleani).
- Conflitti attesi: `trama_qt/window.py` (2 azioni in `_build`, gruppo File del ribbon, 2 righe in
  `update_actions`, 2 metodi prima di `open_classic`, 1 import), `trama_qt/smoke.py` (attributo `scenario`, 4 righe
  in `run_language`, `SCENARIOS` e `run`), `trama_qt/app.py` (`--scenario`), cima di questo file. Vicine: #57-#69
  sul gruppo File di `window.py`, `smoke.py` e questo file.

### Modelli di analisi riutilizzabili su Qt, pacchetto Modelli-Analisi-Qt (2026-11-19)

PR draft verso main (ramo `claude/project-thread-dvb3yf`, base main 4c07db6). Windows NON PROVATO. Guida per chi usa il programma: `docs/qt-analysis-templates.md`.

- Nuovo: **File → Salva come modello…** e **File → Nuovo progetto da modello…** (anche nel gruppo File della barra). Formato `.tramatpl`, JSON schema 1, solo procedura: fogli e colonne, formule, analisi collegate con opzioni, etichette e stili, layout. Nessuna osservazione, niente Info, forme o annotazioni (contate nell'anteprima). Scrittura atomica; rifiuta il progetto aperto e quelli delle altre schede anche via link.
- Motore senza Qt: `analisi/analysis_templates.py` (`write_template`, `read_template`, `instantiate_template`, più `plan_template`, `mapping_problems`, `default_mapping`). Lettura rigorosa: schema, chiavi doppie, NaN, campi ignoti, formule, cicli. Ogni applicazione dà UUID nuovi alle analisi.
- Interfaccia: `trama_qt/templates.py` (dialogo con anteprima, assistente con sorgenti per tabella, griglia di colonne, CSV/TSV letti su un worker, errori sopra la griglia con focus sul campo). La costruzione gira sul worker del job con Annulla; la scheda vuota iniziale si riusa, altrimenti scheda nuova (max 6). Testi EN/IT nel dizionario locale `_TEXT` di quel modulo, non in `strings.py`.
- Scelte fuori specifica, da rivedere: una sorgente presa da un foglio del progetto copia i valori visibili (le formule della sorgente diventano valori, le esclusioni non passano); una formula che legge Info blocca il salvataggio invece di toglierla.
- Da provare su Windows, a 100% e 150%:
  - Aprire `tests/data/qt_templates/progetto-originale.alab`, aprire il layout, File → Salva come modello…: anteprima leggibile, salvare; il `.tramatpl` non contiene `SOLO_ORIGINALE_Ω`.
  - File → Nuovo progetto da modello…, Aggiungi CSV/TSV… con `nuova-calibrazione.csv` e `nuovo-controllo.csv`, mappatura di `mappatura.json`; prima provare Dose due volte (errore sopra la griglia, focus sul campo). Pendenze 6 e 5 nel layout.
  - Salva con nome `.alab`, chiudere, riaprire dal layout, cambiare una misura del Controllo: il grafico si aggiorna.
  - Tastiera: Tab tra sorgenti e griglia, Invio crea, Esc annulla. Tema scuro.
  - `python -m trama_qt --smoke CARTELLA --only qt-analysis-templates` e lo smoke completo.
- Test attesi: `tests.test_analysis_templates` 19/19, `tests.test_qt_templates` 10/10, contratto esterno del pacchetto OK, verificatore 7/7.
- Conflitti attesi con #57–#69: `trama_qt/window.py` (import in testa, due azioni in `_build` dopo `save_as`, gruppo File della barra, una riga in `update_actions`, due metodi prima di `recalculate`), `trama_qt/smoke.py` (due righe dopo `project_tabs`), `trama_qt/app.py` (ramo `--only` di `--smoke`), cima di questo file.

### Recupero progetti dopo una chiusura anomala, pacchetto Recupero-Progetti-Qt (2026-11-19)

PR draft verso `main` dal ramo `claude/project-thread-urwia4`, base `main` `4c07db6` (0.95.0 beta, la base del pacchetto). Commit: `c0cadac` motore, `8aca18d` interfaccia, poi collaudo e guida. **Windows NON PROVATO.** Guida per chi usa il programma e note per sviluppatori: `docs/qt-recovery.md` (va collegata al menu Aiuto e al portabile: decide il coordinatore).

- Nuovo: copie di recupero dei progetti con modifiche confermate e non salvate. **Impostazioni → Copie di recupero…** (attive, ogni 30 s; 15/30/60/120), **File → Recupera progetti…** (`window.actions["recover"]`), avviso sotto la barra comandi all'avvio se ci sono copie, stato «Ultima copia di recupero hh:mm:ss» nella barra di stato. Testi EN/IT in `trama_qt/recovery.py` (`r()`), non in `strings.py`.
- Motore senza Qt: `trama_qt/recovery_store.py` (verificatore del pacchetto 6/6). Copie in `%APPDATA%\TramaStat\recovery` (Linux `$XDG_CONFIG_HOME/tramastat/recovery`), lease per finestra in `recovery/leases`.
- `MainWindow(recovery=None)` è il default: test e smoke esistenti non scrivono nel profilo. Solo `app.main` crea `RecoveryController.for_profile()`.
- Da provare su Windows (portabile, a 100% e 150% di scala reale):
  - `python -m trama_qt.recovery_drill CARTELLA` (o lo stesso col Python del portabile): avvia un Trama separato con APPDATA temporanea, aspetta le due copie, termina solo quel PID (TerminateProcess), riapre, recupera una copia, rinvia l'altra e la riapre da File, Salva con nome Annulla/OK, originale con byte identici; poi originale cambiato fuori e indice rovinato. Esito in `CARTELLA/status.txt` e `report.json`, schermate EN/IT anche in tema scuro.
  - A mano: aprire `tests/data/qt_recovery/misure-salvate.alab`, cambiare una cella, aprire un secondo progetto nuovo e scriverci un valore, aspettare «Ultima copia di recupero» (30 s), chiudere Trama da Gestione attività. Riaprire `tramastat.exe`: avviso con 2 copie, Recupera, salvataggio con nuovo nome nelle due schede. Controllare `%APPDATA%\TramaStat\recovery` vuota dopo i salvataggi/scarti.
  - Due istanze aperte insieme: la seconda non offre le copie della prima (il dialogo dice «Altre N copie appartengono a un'altra finestra»).
  - Cartella `recovery` in sola lettura (Proprietà → Sicurezza): la barra di stato dice «Copia di recupero non riuscita · ultima …», una sola riga di messaggio, nessuna finestra.
  - Dialogo e avviso leggibili a 150% e nel tema scuro; colonne del dialogo con percorsi lunghi (elisi al centro).
- Test attesi: `tests.test_recovery_store` 21/21, `tests.test_qt_recovery` 24/24, `tests.test_qt_projects` e `tests.test_qt_shell` invariati. Misure (container Linux, due schede 10.000×30): cattura sul thread GUI ~2 ms per scheda, pausa massima della GUI durante la scrittura ~22 ms, scrittura in sottofondo ~0,4 s e 5,8 MB per copia, nessuna riscrittura con dati fermi per due intervalli (`python tests/perf_qt_recovery.py`).
- Conflitti attesi: `window.py` (import, costruttore, azioni `recover`/`recovery_settings` e gruppi File/Impostazioni della barra, `update_actions`, `close_project`, `open_path` → `_put_project`, `save`, `closeEvent`) con le PR Qt aperte #63 (Esporta più figure), #64 (Stili di figura), #65 (Report riproducibili, anche gruppo File) e #66 (Unisci fogli); `app.py` (creazione della finestra); `project.py` (`Project.__init__`, `dirty` diventa proprietà, `save`, `sync_links` → `_persist_links`); `analisi/data.py` (`save_project` diviso in `project_document`/`project_bytes`, stesso output); cima di questo file.

### Unisci fogli per chiave, pacchetto Unione-Fogli-Chiavi 0.96 (2026-11-19)

PR draft verso main (ramo `claude/worksheet-key-join`, base main 4c07db6). Windows NON PROVATO. Guida per chi usa il programma: `docs/worksheet-join.md`.

- Nuovo metodo **Analyze → Data Processing → Join worksheets by key** (IT **Unisci fogli per chiave**). Il motore è in `analisi/worksheet_join.py`, i testi EN/IT in `analisi/worksheet_join_text.py`. Chiavi tipizzate (testo letterale, 1 = 1.0 senza perdita sugli interi grandi, `"1"` ≠ 1, bool solo con bool, vuoto/escluso/non finito = nessuna corrispondenza), da 1 a 4 coppie, Inner/Left/Full, quattro cardinalità, budget di 100.000 righe e 2.000.000 di celle controllato prima di espandere. I risultati sono Joined data, Join provenance e Join diagnostics.
- Qt: editor dedicato `trama_qt/worksheet_join.py` (foglio di destra, coppie affiancate, tipo e cardinalità), agganciato in `analysis_dialog.py`. Gli errori riaprono il dialogo con il cursore sul campo giusto, anche sulla singola coppia.
- Progetto: `Project.join_sources`, `join_problem`, `join_data` e `readers`. Il foglio di destra si legge sul thread della finestra (`frame(mask_excluded=True)`) e viaggia nel `RefreshJob`, quindi una modifica di uno dei due fogli ricalcola l'unione e le analisi collegate. Le unioni restano fuori dal precompute parallelo (`LOCAL_METHODS`).
- Famiglie: Duplica famiglia continua a leggere lo stesso foglio di destra, a meno che non sia copiato anche lui. Salva famiglia come porta con sé il foglio di destra.
- Tk classica: il metodo non compare nel menu; una ricetta esistente resta intatta e mostra `join.classic`.
- Barra di stato: `trama_qt/status_label.py` taglia con i puntini un messaggio lungo invece di allargare la finestra (tooltip con il testo intero, `text()` invariato).
- Da provare su Windows, a 100% e 150%, chiaro e scuro:
  - Aprire `tests/data/worksheet_join/unione-campioni.alab`, foglio `Misure $`, Unisci fogli per chiave: foglio `Anagrafica | visite`, coppie Sample↔ID e Visit↔Time, Completa, Uno a molti → 8 righe come nella guida.
  - Rifare con Uno a uno: errore, il dialogo si riapre su Cardinalità e si corregge lì.
  - Modificare una cella del foglio di destra, poi Annulla: il risultato segue entrambe le volte.
  - Salvare, chiudere, riaprire: il risultato si ricalcola uguale. Export CSV dei tre fogli di risultato.
  - Dialogo in italiano a 150%: coppie, didascalie e note leggibili, senza tagli.
  - `python -m trama_qt --smoke CARTELLA` alle due scale: i passi `join-*` non devono dare problemi.
- Test attesi: `tests.test_worksheet_join` 24/24, `tests.test_qt_worksheet_join` 14/14, `tests.test_catalog`, `tests.test_qt_shell`, `tests.test_family_workflow`. Misure in `tests/perf_worksheet_join.py`.
- Conflitti attesi con #57-#64: `window.py` (`_ask`, `calculate_candidate`, import e costruttore della barra di stato), `analysis_dialog.py` (`__init__`, `configure_fields`, `focus_field`, `options`, `accept`, `_message`), `project.py` (`compute`, `RefreshJob`, `plan_refresh`, `run_refresh`, `table_runs`), `smoke.py` (due righe dopo global_fit), `analisi/i18n.py` (registro dei testi), `analisi/workbench.py` (METHODS e GROUPS), cima di questo file.

### Report di analisi riproducibili su Qt (2026-11-19)

PR draft verso `main` dal ramo `claude/project-thread-svcb2z`, base `4c07db6` (0.95.0 beta). Windows NON PROVATO. Guida per chi usa il programma: `docs/qt-report.md`.

- Nuovo: **File → Esporta report di analisi…** (`window.actions["export_report"]`, gruppo File dopo "Esporta più fogli in PDF"). Crea uno ZIP leggibile offline: `index.html` (senza JS, URL esterni o font remoti), `manifest.json` (`trama-analysis-report`, schema 1), `tables/NNN.csv`, `figures/NNN.svg`, `project.alab` facoltativo (spento di default, con avviso che contiene i dati originali).
- Motore senza Qt: `analisi/report_bundle.py` (`export_bundle`, `verify_bundle`, `ReportCancelled`, `LAYOUT_METHOD = "Layout"`). Scrive in un temporaneo nella stessa cartella, verifica lo ZIP e poi `os.replace`; errori e annullamento lasciano intatto il file precedente e nessun temporaneo. ZIP deterministico (data fissa 1980-01-01, ordine per percorso).
- Qt: `trama_qt/report_catalog.py` (candidati senza Qt: tabelle di risultato, grafici, layout, con il motivo per quelli non esportabili; ricetta pulita da percorsi, cache e metadati del formato di origine; congelamento con il CSV di File → Esporta e l'SVG di `analisi.figure_export`/`layout_svg`), `trama_qt/report_dialog.py` (dialogo, conferma sostituzione, congelamento sul thread GUI con Annulla, scrittura come job annullabile con "Annulla calcolo"). Testi EN/IT locali nel modulo, non in `strings.py`.
- Agganci piccoli: `window.py` (import di `report_text`, azione, voce nel gruppo File, una riga in `update_actions`, metodo `export_report`), `smoke.py` (2 righe dopo `project_tabs`), `package_windows.py` (guida `qt-report.md`).
- Da provare su Windows a 100% e 150% reali:
  - Aprire `tests/data/qt_report/calibrazione-report.alab`, calcolare la regressione, crearne una seconda e un layout. File → Esporta report di analisi…: cambiare ordine e nomi, titolo `Control $ <A> & β`, nota con `<script>`; Esporta, scegliere un file esistente e rispondere No (non cambia nulla), poi Sì.
  - Estrarre lo ZIP e aprire `index.html` con la rete staccata: immagini SVG visibili, CSV completo apribile in Excel (BOM UTF-8), testo con markup letterale.
  - Il dialogo con molte sezioni (60) a 1024×768 e 150%: Esporta e Annulla sempre visibili, motivi delle righe non disponibili leggibili per intero; tema scuro.
  - Con la copia progetto attiva: aprire `project.alab` estratto in Trama, ricalcolare e salvare; il progetto originale resta senza • e il file originale identico.
  - Annulla durante "Preparazione del report…" e durante la scrittura (barra in basso): nessun file nuovo, il report precedente intatto.
  - `python -m trama_qt --smoke CARTELLA` a 100% e 150%: passi `report-*`.
- Test attesi: `tests.test_report_bundle` 14/14, `tests.test_qt_report` 19/19, `tests.test_qt_shell` e `tests.test_qt_projects` invariati. Verificatore del pacchetto: base 2/3 (modulo mancante), testa 7/7.
- Conflitti attesi: cima di questo file con tutte le PR Qt aperte; `smoke.py` (riga dopo `project_tabs`); `window.py` gruppo File e `update_actions` con #63 Esportazione figure (anche lei aggiunge un'azione dopo `export_pdf`); `package_windows.py` (lista guide). Tutti banali: tenere entrambe le righe.
### Correlazione intraclasse, pacchetto ICC-Misure-Continue (2026-11-20)

PR draft verso main (ramo `claude/icc-misure-continue`, base main df1d591 = v0.96.0). Windows 10 fisico (1920×1080, 100 %, DPI 96, 2026-11-20): suite completa 4169 test OK (base 4111 OK), smoke generale PASS, smoke ICC chiaro e scuro PASS, verificatore 9/9; 150 % e secondo monitor NON PROVATI. Evidenze nella PR. Guida: `docs/icc.md`.

- Motore `analisi/icc.py` (Group Comparison → Intraclass correlation, dopo Bland–Altman for repeated pairs): fogli ICC, ANOVA components, Subjects, Settings, Excluded rows; grafico dei profili; quattro coefficienti McGraw–Wong; dati centrati sulla mediana e scalati per una potenza di due esatta (ICC invariante, niente overflow); bootstrap per soggetti sul pool `analisi.parallel` a blocchi con stato PCG64 esatto (1 e N processi identici), budget 20 milioni di celle controllato prima di estrarre.
- Qt: `trama_qt/icc.py` (campi bootstrap solo con Bootstrap CI, riepilogo, valutatori nell'ordine di selezione, controlli prima del worker, messaggi `icc.error.` in italiano) e 8 righe in `analysis_dialog.py`, come il binding di Bland–Altman per coppie ripetute. Una riga in `AnalysisDialog.options()` rimette `Raters` nell'ordine in cui sono stati spuntati. Nessuna modifica a `project.py`/`window.py`.
- Test: `tests/test_icc.py` (motore, oracolo a frazioni esatte e bootstrap con righe copiate), `tests/test_icc_parallel.py` (pool reale a 4 processi), `tests/test_qt_icc.py` (offscreen), fixture in `tests/data/icc/`. Smoke: `python -m trama_qt.icc_smoke CARTELLA [--dark]`.
- Da provare su Windows, a 100% e 150%:
  - Aprire `docs/examples/ICC-valutatori.alab`, aprire il grafico: 11 soggetti completi, 3 valutatori nell'ordine C, A, B.
  - Cambia parametri → Consistency / Mean of raters; Bootstrap CI con 5.000 repliche e Annulla calcolo durante il calcolo (torna l'ultimo risultato).
  - Impostazioni → processi 1 e Auto: stessi numeri nel foglio ICC.
  - Dialogo in italiano a 1024×768 e tema scuro: righe Livello, Repliche e Seme visibili solo con IC bootstrap; spunta i valutatori in ordine diverso e controlla il riepilogo.
- Conflitti attesi con i pacchetti Cochran-Q-Appaiato e Precisione-Richiamo (stessa base): `analisi/workbench.py` (import, METHODS, GROUPS "Group Comparison", GRAPH_METHODS, `analyse`), coda di `analisi/interface_catalog.py`, `trama_qt/analysis_dialog.py` (import, attributo, `configure_fields`, `options`, `accept`, `_message`), `tests/test_catalog.py`, `docs/features.md`, cima di questo file. Tutti banali (righe aggiunte vicine).

### Bland–Altman per coppie ripetute, pacchetto 02 del 0.96 (2026-11-20)

PR draft verso main (ramo `claude/project-thread-y6nc6f`, base main 4c07db6). Windows NON PROVATO. Guida: `docs/bland-altman-repeated.md`.

- Motore `analisi/bland_altman_repeated.py` (Group Comparison → Bland–Altman for repeated pairs): fogli Agreement, Subjects, Pairs, Excluded rows; grafici Pairs e Subject diagnostics; bootstrap per soggetti sul pool `analisi.parallel` a blocchi con stato PCG64 esatto (1 e N processi identici). Il Bland–Altman classico non cambia.
- Qt: `trama_qt/bland_altman_repeated.py` (campi bootstrap solo con Subject bootstrap, controlli prima del worker, messaggi `barep.error.` in italiano) e 10 righe in `analysis_dialog.py`, come il binding di K-means stability. Nessuna modifica a `project.py`/`window.py`: il ricalcolo e l'annullamento usano il percorso generico.
- Test: `tests/test_bland_altman_repeated.py` (motore), `tests/test_bland_altman_repeated_parallel.py` (pool reale a 4 processi), `tests/test_qt_bland_altman_repeated.py` (offscreen). Smoke: `python -m trama_qt.bland_altman_repeated_smoke CARTELLA [--dark]`.
- Da provare su Windows, a 100% e 150%:
  - Aprire `docs/examples/Bland-Altman-ripetute.alab`, aprire il grafico: 14 coppie, 6 soggetti, bias 4,571, limiti −1,192 e 10,33.
  - Cambia parametri → Log ratio e Subject diagnostics; Subject bootstrap con 20.000 repliche e Annulla calcolo durante il calcolo (torna l'ultimo risultato).
  - Impostazioni → processi 1 e Auto: stessi numeri in Agreement.
  - Dialogo in italiano a 1024×768 e tema scuro: righe Livello, Repliche e Seme visibili solo col bootstrap.
- Conflitti attesi: `analisi/workbench.py` (import, METHODS, GROUPS "Group Comparison", GRAPH_METHODS, `analyse`), coda di `analisi/interface_catalog.py`, `trama_qt/analysis_dialog.py` (stessi punti del binding K-means stability, PR #68), `tests/test_catalog.py`, `docs/features.md`, cima di questo file.

### Validazione del modello logistico binario per la 0.96 (ramo `claude/project-thread-4olxvq`, base main `4c07db6`, 2026-11-19)

Pacchetto Trama-Claude-01-Logistica-Validazione-096, in tre commit: motore con test, dialogo Qt con testi EN/IT, smoke con guida ed esempio. Windows NON PROVATO.

- Nuovo: Analizza → Regressione e curve → **Valida il modello logistico binario** (*Validate binary logistic model*). Motore `analisi/logistic_validation.py`; il fit di ogni fold è `analisi.models.binomial_fit`, estratto da `logistic_fit` con risultati identici (`tests.test_logistic_validation.LegacyLogisticTests` confronta tutti i fogli di due ricette Logistic con quelli scritti dalla base). Dialogo generico; `trama_qt/logistic_validation.py` esegue `prepare` quando si preme Esegui (nessun fit prima del worker) e traduce i messaggi. Catalogo IT in una sezione propria: `analisi/logistic_validation_catalog.py`, unito in coda a `analisi/interface_catalog.py`. Guida `docs/logistic-validation.md`, esempio `docs/examples/Validazione-Logistica.alab`.
- Multicore: nessun pool. Su 20.000 righe × 10 fold il pool non dava guadagno e i coefficienti dei fold potevano differire negli ultimi bit fra finestra e worker. Il ciclo dei fold resta sul worker Qt e controlla l'annullamento prima di ogni fold. `analyse(..., cancel=)` basta: `project.py` e `parallel_analyses.py` non sono toccati.
- Smoke dedicato: `python -m trama_qt.logistic_validation_smoke CARTELLA [--dark]`. Importa un CSV sintetico, prova due errori sul campo, esegue, esporta, crea un'analisi collegata su Predictions, annulla una modifica, modifica una cella, salva, riapre, ricalcola, poi 20.000 righe e un annullamento.
- Da provare su Windows:
  - Lo smoke dedicato a 100% e 150%, chiaro e scuro.
  - Aprire `docs/examples/Validazione-Logistica.alab`, Cambia parametri, scegliere *Fold rotto* come colonna dei fold: errore sul campo con la riga 121.
  - 20.000 righe e 20 fold, poi Annulla calcolo: ricetta e risultato precedenti restano.
  - Esportare il grafico (Tutti i pannelli) in SVG e PDF.
- Packaging: aggiungere `logistic-validation.md` alla tupla dei docs di `package_windows.py` (non toccato qui).
- Conflitti attesi con le altre PR 0.96 aperte in parallelo: coda di `analisi/interface_catalog.py` (tre righe), `analisi/workbench.py` (import, `METHODS`, gruppo Regressione e curve, `GRAPH_METHODS`, dispatcher), `trama_qt/analysis_dialog.py` (import, `accept`, `_message`), `tests/test_catalog.py`, `docs/features.md` e questa voce in cima al file.

### Stabilità K-means per la 0.96 (ramo `claude/project-thread-2qvhxr`, base main `4c07db6`, 2026-11-19)

Pacchetto Trama-Claude-Stabilita-KMeans-096, in tre commit: motore, dialogo Qt, smoke con documentazione. Windows NON PROVATO.

- Nuovo: Analizza → Raggruppamento → **Stabilità K-means** (*K-means stability*). Il motore è `analisi/kmeans_stability.py` e usa `analisi.stats.kmeans` per ogni fit. Il dialogo è quello generico. `trama_qt/kmeans_stability.py` mostra il limite di iterazioni solo con Hartigan–Wong, esegue i controlli e i budget del motore quando si preme Esegui (prima di qualsiasi worker) e traduce i messaggi. Il worker passa annullamento e avanzamento (`compute` in `trama_qt/project.py`). Guida: `docs/kmeans-stability.md`. Esempio: `docs/examples/Stabilita-KMeans.alab`.
- Multicore: i fit vanno al pool condiviso di `analisi.parallel` a blocchi di 32, secondo l'impostazione di Calcolo multicore (Impostazioni). Con un processo restano un ciclo sul worker Qt, con un passo di avanzamento per fit. Il metodo è in `LOCAL_METHODS` di `analisi/parallel_analyses.py`: non viene mai mandato intero a un worker, così c'è un solo livello di parallelismo (i fit) e l'avanzamento arriva alla barra di stato. Con 1, 2 e 4 processi le tabelle sono identiche (`tests.test_kmeans_stability.PoolTests` e misure nella PR).
- Nuovo smoke dedicato: `python -m trama_qt.kmeans_stability_smoke CARTELLA` (con `--dark` per il tema scuro). Fa il percorso reale in inglese e in italiano: dialogo con errori corretti sul posto, budget rifiutato, risultato, layout, esportazioni, salvataggio, modifica ed esclusione di una cella, annullamento. Scrive screenshot, `report.txt` e `status.txt`.
- Da provare su Windows:
  - Lo smoke dedicato a 100% e 150%, con tema chiaro e scuro.
  - Aprire `docs/examples/Stabilita-KMeans.alab`, poi Cambia parametri. Con Ricampionamenti 2000 l'errore compare nel dialogo, sul campo. Con Frazione campionata `82,5` il calcolo parte. Con Hartigan–Wong compare il limite di iterazioni.
  - Ricampionamenti 1500, Esegui, poi Annulla durante il calcolo: ricetta e risultato precedenti restano.
  - Esportare il grafico in SVG e PDF e metterlo in un layout.
  - Calcolo multicore… a 1 e a 4 processi (o `TRAMA_PROCESSES`): stesse tabelle, annullamento pronto anche con il pool.
- Conflitti attesi: questa voce con #63 e #64, che scrivono in cima allo stesso file. `analisi/workbench.py` (gruppo Clustering, `METHODS`, `GRAPH_METHODS`) e la coda di `analisi/interface_catalog.py` con #37 Silhouette. `window.py` e `smoke.py` non sono toccati.
- Test attesi: `tests.test_kmeans_stability`, `tests.test_kmeans_stability_example`, `tests.test_qt_kmeans_stability`, `tests.test_catalog` e `tests.test_parallel_analyses` tutti OK. Gli esiti della suite completa sono nella PR.

### Stili di figura riutilizzabili (pacchetto Stili-Figura-Qt-095, ramo `claude/project-thread-wihrrt`, 2026-11-19)

- Grafico → Stili di figura… (accanto a Format Graph): salva colore, caratteri, cornice, griglia e legenda di un grafico come stile con nome, lo mostra in anteprima su un altro grafico senza ricalcolo e lo applica con un solo `commit_style`. Libreria in `graph-style-presets.json` accanto a `preferences.json`, import/export JSON di un solo stile. Guida: `docs/qt-graph-style-presets.md`.
- Codice: `trama_qt/graph_style_presets.py` (senza Qt), `trama_qt/graph_style_preset_dialog.py`, aggancio in `trama_qt/window.py` (azione `graph_style_presets`, metodo `graph_style_presets`, `_figure_canvas`), una voce in `trama_qt/smoke.py`. Nessuna dipendenza nuova, nessuna icona nuova (usa `sparkles`), `strings.py` e i cataloghi non cambiano.
- Da provare su Windows, a 100% e 150%:
  - Formattare il primo grafico, Stili di figura… → nome «Pubblicazione» → Invio: lo stile compare in elenco e il dialogo resta aperto. Il file sta in `%APPDATA%\TramaStat\graph-style-presets.json`.
  - Sul secondo grafico scegliere lo stile (il grafico cambia), Esc (torna com'era), poi di nuovo e Applica. Titolo, scala e forme del secondo grafico non cambiano. Salvare, riaprire, esportare SVG/PDF.
  - Importare un JSON troncato e un omonimo con maiuscole diverse (chiede conferma), file di libreria in sola lettura (errore, file intatto).
  - `python tests/smoke_qt_graph_style_presets.py CARTELLA --lang it --theme dark` e `python -m trama_qt --smoke CARTELLA`.
- Test attesi: `tests.test_qt_graph_style_presets` 16/16, `tests.test_qt_graph_style_preset_dialog` 4/4, `tests.test_qt_shell` 21/21.

### Esporta più figure (ramo `claude/project-thread-x6igj7`, base main 7a7340c, 2026-11-19)

- Nuovo comando File → Esporta più figure… (`export_batch`, accanto a Esporta più fogli in PDF): un file PNG, SVG o PDF per ogni grafico o layout del progetto attivo, in una cartella. Motore senza Qt in `trama_qt/batch_export.py` (`plan_filenames`, `BatchExport`), dialogo in `trama_qt/batch_export_dialog.py`, guida in `docs/qt-batch-export.md`.
- I testi EN/IT stanno nel modulo del dialogo, non in `strings.py`, per non toccare le righe delle altre PR Qt aperte.
- Da provare su Windows:
  - Tre figure (due grafici e il layout di `sessione.alab`) in PNG, SVG e PDF: tre file validi; rifatto nella stessa cartella, tre nomi con ` (2)` e i primi file identici.
  - Un file `xy series of calibrazione b.png` creato a mano nella cartella: l'anteprima propone `… (2)`; se lo crei dopo l'anteprima, la riga risulta Saltata e il file non viene toccato.
  - Cartella in sola lettura (Proprietà → Sicurezza, nega scrittura): l'export si ferma con «la cartella non è scrivibile» e non lascia file.
  - Titoli con `: / ? *`, `CON`, `LPT9.tmp`, accenti: nomi validi in Esplora risorse.
  - Esc durante il lotto: si ferma dopo il file in corso, il riepilogo resta aperto.
  - `python -m trama_qt.batch_export_smoke CARTELLA` e `python -m trama_qt --smoke CARTELLA` a 100% e 150%.
- Test attesi: `tests.test_qt_batch_export` 21 test (uno saltato se si è root o su Windows: permessi della cartella), `tests.test_qt_shell` invariato.

### Più progetti in schede nella finestra Qt, pacchetto Progetti 0.95 (2026-11-19)

PR draft verso main (ramo `claude/project-thread-hz1cm2`, base main 7a7340c). Windows NON PROVATO.

- Una barra `QTabBar` (`projectTabs`) sopra la barra comandi, con **+** per Nuovo e × su ogni scheda. Ogni scheda ha il suo `Project` (dati, risultati, grafici, layout, Info, cronologia, dirty). `trama_qt/sessions.py` tiene le sessioni senza Qt; in `window.py` solo l'area file e lifecycle (`new_project`, `open_path`, `save`, `close_project`, `switch_project`, `closeEvent`), più le proprietà `project`, `selected`, `inspector_*` che puntano alla sessione attiva.
- Comandi: Nuovo (Ctrl+N), Apri (Ctrl+O), Chiudi progetto (`window.actions["close_project"]`, Ctrl+W e Ctrl+F4), scheda successiva/precedente (Ctrl+Tab, Ctrl+Shift+Tab). Salva (Ctrl+S) salva la scheda attiva.
- Stesso percorso (canonico, anche con link): attiva la scheda esistente. La scheda vuota iniziale si riusa. Import e dati CSV lavorano nella scheda attiva. Massimo 6 schede, come la finestra classica.
- Prima di lasciare una scheda: bozza Inspector (annullare resta lì con la bozza), cella in modifica e note Info vengono salvate nel loro progetto. Se la scrittura avvia un ricalcolo, il cambio scheda parte alla fine.
- Con un job attivo: schede, Nuovo, Apri e Chiudi sono disabilitati, Annulla calcolo resta raggiungibile. File arrivati nel frattempo (trascinati, riga di comando) si aprono a job finito. Un job porta con sé la sua scheda e non applica mai risultati a un'altra.
- Chiusura: Salva/Scarta/Annulla solo per il progetto coinvolto. Chiusura della finestra: prima si chiedono tutte le decisioni (Salva/Scarta/Annulla per ogni scheda con modifiche), solo dopo si salva e si chiude; Annulla non salva nulla, un salvataggio fallito lascia la finestra con tutte le schede. L'ultima chiusura lascia una scheda vuota. Salva con nome non sovrascrive un progetto aperto in un'altra scheda (nemmeno Salva famiglia).
- Etichette EN/IT con • per le modifiche non salvate; stesso nome → cartella che distingue; tooltip col percorso completo.
- Test: `tests/test_qt_projects.py` (35: sessioni, isolamento con UUID uguali, percorso invalido, dati con app occupata, cancellazione, salvataggio fallito, bozza Inspector, chiusura con due schede dirty, tasti). Smoke: `python -m trama_qt --smoke` ora esegue anche `trama_qt/projects_smoke.py` (due progetti reali con grafico e layout, mouse e tastiera, salva solo A, chiusura/riapertura, CSV, apertura da riga di comando, errore di apertura, misura 10.000×30 in `projects-switch.txt`).
- Da provare su Windows, a 100% e 150%:
  - Aprire `sessione-a.alab` e `sessione-b.alab` (nel pacchetto, stesso foglio Misure): due schede, dati diversi, Ctrl+Tab e clic.
  - Modificare B, tornare ad A, salvare A: B resta con il •, il file di B non cambia.
  - Chiudere B con Annulla: resta aperta e sporca. Poi chiudere la finestra con due schede sporche e Annulla alla seconda.
  - Lancio `tramastat.exe sessione-a.alab` e trascinare un secondo .alab sulla finestra.
  - Tab con il tema scuro e a 150%: caption e × leggibili.
- Conflitti attesi: `window.py` (area file e lifecycle e il costruttore), `strings.py`, `tests/test_qt_shell.py` (helper `reopen`: aprire un file già aperto ora attiva la sua scheda, quindi i test che salvano e rileggono chiudono prima la scheda), `smoke.py` (due righe dopo `self.editors`), cima di questo file.

### b7c4ee2 · Galleria di grafici e layout su Qt, pacchetto 03 (2026-11-19)

PR draft verso `main` dal ramo `claude/project-thread-i504fp`, base `7a7340c`. **La consegna è il commit `b7c4ee2`.** Il commit dopo aggiunge solo questa nota. Guida per chi usa il programma: `docs/qt-gallery.md`.

- Nuovo: **Visualizza → Galleria** (Ctrl+Maiusc+G). Schede con anteprima, nome, tipo e stato scritto a parole (Pronto, Non calcolato, Obsoleto, Calcolo non riuscito); viste Tutti/Grafici/Layout con conteggio; ricerca per nome (Ctrl+F) letterale, senza accenti, maiuscole e spazi doppi, con `$` come carattere normale. Frecce, Invio e doppio clic aprono il foglio con la navigazione normale (`open_sheet`), quindi il calcolo è quello ordinario con errori e Annulla; Esc o Alt+Sinistra tornano al foglio di partenza. La galleria non calcola mai e non sporca il progetto.
- Anteprime: solo per le schede visibili, una figura per tick sul thread della GUI, in pausa mentre gira un calcolo, cache LRU da 64 schede invalidata da dati, Format Graph e ricalcolo. Sono disegnate con `savefig`, mai con un canvas nuovo, e non rubano il canvas della figura mostrata da un foglio. I layout si compongono pannello per pannello nelle proporzioni della pagina.
- Scelte fuori specifica, da rivedere:
  - La galleria prende il posto della pagina e la pagina di partenza resta nascosta (non distrutta); il foglio dati torna identico, gli altri si ricostruiscono con `show_sheet`.
  - Filtro e testo di ricerca restano per la sessione e si azzerano cambiando progetto.
  - I testi stanno in `trama_qt/gallery.py` (`g()`), non in `strings.py` né in `theme.py`, per non scontrarsi con #57, #58 e #59.
  - Cinque icone nuove Lucide (ISC) in `assets/qt/icons/`.
- Punti di conflitto con #57/#58/#59: `trama_qt/window.py` (azione `gallery`, gruppo Visualizza della barra, `update_actions`, `refresh`, `_replace_page`, `new_project`, `open_path`, `closeEvent`), `assets/qt/icons/` e questo file.
- Da provare su Windows (NON PROVATO):
  - Aprire `tests/data/qt_gallery/galleria.alab` (3 grafici, 2 layout), Visualizza → Galleria: cercare `Calibrazione $` trova una scheda; Invio la apre e la calcola; Esc torna al foglio dati.
  - Anteprime nitide a 100% e 150%, e tema scuro; titolo e stato leggibili anche senza colore.
  - Cambiare un dato e poi Format Graph: la scheda diventa "Obsoleto" o si ridisegna al ritorno in galleria.
  - Un grafico con opzione sbagliata: scheda "Calcolo non riuscito", aprirlo mostra il motivo e non chiede dialoghi.
  - Con molti grafici scorrere con la barra e col rotellino: i clic restano pronti.
  - `python -m trama_qt --smoke CARTELLA` a 100% e 150%: i passi "gallery" non devono dare problemi.
- Test attesi: `tests.test_qt_gallery` 38/38 OK, `tests.test_qt_shell` 21/21 OK. Misure con 120 schede in `/mnt/project-files/qt-galleria-095/`.

### Canvas Qt · Disegno e modifica di forme col mouse sul grafico (2026-11-19, pacchetto 01 della 0.95)

Ramo `claude/project-thread-9kot5b`, base `main` `7a7340c`. Windows NON PROVATO. Riferimento utente e per sviluppatori in `docs/qt-canvas-095.md`.

- Scheda Grafico → **Disegna** e cinque pulsanti nella barra del grafico: Seleziona/sposta, Linea, Freccia, Rettangolo, Ellisse (`window.actions["draw_*"]`). Trascinare disegna, cliccare seleziona, trascinare sposta, le maniglie ridimensionano; frecce, Canc, doppio clic/Invio (editor numerico), tasto destro (menu come nella classica), Ctrl+C/X/V, Esc.
- Controller spostato senza Tk in `analisi/shape_interaction.py`; `analisi/shape_canvas.py` è ora solo l'adattatore Tk, con lo stesso comportamento (63 test delle forme sotto Tk OK). Cambia anche la classica in due punti voluti: i modificatori si leggono anche da `event.modifiers`, e un ridimensionamento lascia l'altro estremo identico a come era salvato.
- Annulla/Ripeti: cronologia per grafico in `Run.shape_history`, mai condivisa con la griglia o con altri grafici. Con un grafico che ha passi di disegno (o con uno strumento acceso) Ctrl+Z/Ctrl+Y agiscono su quello; altrove, sulla griglia come prima. Un trascinamento = un passo. L'editor numerico registra anch'esso un passo.
- Fuori perimetro (strumenti spenti, con il motivo nella nota e nel suggerimento): grafici importati, layout, assi interrotti, più pannelli o asse gemello. Salvare, esportare, ricalcolare o cambiare foglio durante un trascinamento chiude l'anteprima. Le maniglie non finiscono in PNG/SVG/PDF/`.alab`.
- Conflitti attesi: `trama_qt/window.py` (azioni, `_canvas`, `undo`, `update_actions`, 7 punti piccoli), `trama_qt/project.py` (`Run.shape_history`, `commit_style`), `trama_qt/strings.py`, `trama_qt/smoke.py` (una chiamata) e la prima voce di questo file con #57, #58 e #59.
- Nota per il Vetro (#59): le quattro icone nuove (`mouse-pointer-2`, `slash`, `move-up-right`, `circle`) sono Lucide ISC in `assets/qt/icons/`, usate con `theme.icon`. Nel tema scuro attuale di main le icone delle azioni non si ricolorano; lo risolve `SvgIcon` della #59.
- Da provare su Windows, a 100% e 150%, con il mouse vero:
  - Disegnare un rettangolo, una freccia, una linea e un'ellisse; spostarli e ridimensionarli dalle maniglie; Ctrl per quadrato/cerchio, Maiusc per tenere lo strumento.
  - Copia e incolla, taglia e incolla, tasto destro, doppio clic; Ctrl+Z/Ctrl+Y sul grafico e poi sulla griglia.
  - Esc a metà trascinamento, cambio di finestra con Alt+Tab durante il trascinamento (deve annullare l'anteprima), zoom o pan della barra del grafico con uno strumento acceso.
  - Salva, riapri, esporta PNG, SVG e PDF: senza quadratini di selezione. Grafico con asse interrotto: strumenti spenti con il motivo.
  - `python -m trama_qt --smoke CARTELLA` alle due scale.
- Test attesi: `tests.test_shape_interaction` 15/15, `tests.test_qt_canvas` 45/45, `tests.test_qt_shell` 21/21, smoke Qt PASS; verificatore del pacchetto `python verify.py --repo <checkout>` PASS.

### Rifinitura grafica Vetro su Qt · ramo `claude/project-thread-n2ib1i` (2026-11-19)

Ramo nuovo da main `7a7340c`, solo interfaccia: `analisi/` non è toccato. Anteprima con schermate prima/dopo e video in `/mnt/project-files/qt-rifinitura-1119/` (fuori dal repo).

- Tema chiaro (predefinito), scuro o "Come il sistema": Visualizza → Come il sistema / Chiaro / Scuro. La scelta resta salvata (`QSettings` TramaStat/Trama, chiave `qt/theme`), `TRAMA_THEME=light|dark|system` la forza. In "Come il sistema" il tema cambia da solo quando Windows passa da chiaro a scuro (`styleHints().colorSchemeChanged`). I grafici restano su carta bianca.
- File → Apri nell’interfaccia Classica e l’opzione `--tk` aprono la finestra Tk con la grafica originale di Trama.
- Icone: ogni icona Lucide è un `QIconEngine` (`theme.SvgIcon`) che disegna l'SVG alla dimensione e alla scala del monitor in cui compare, quindi resta nitida anche spostando la finestra tra schermi con scala diversa, e prende il colore del tema al momento del disegno. La barra di matplotlib usa le stesse icone (`theme.plot_toolbar`). Nuove icone Lucide: house, arrow-left, arrow-right, move, check, monitor, chart-spline.
- Ombre morbide sotto i due pannelli, disegnate a nove fette dallo sfondo della finestra (`theme.ShadowCanvas`): nessun `QGraphicsEffect` su tabelle e grafici, quindi lo scorrimento della griglia non rallenta.
- Vetro: quando si apre un dialogo modale, la finestra principale dietro viene sfocata e velata (`theme.GlassVeil`), con dissolvenza in 200 ms. Il dialogo resta una finestra nativa.
- Angoli arrotondati e controlli disegnati da noi: caselle di spunta e pulsanti di opzione col colore Trama, frecce dei menu a tendina e dei campi numerici, schede dei dialoghi a pillola, riquadri arrotondati, pulsante principale con leggero gradiente, scrollbar sottili. Su Windows 11 menu e tendine hanno gli angoli arrotondati e l'ombra di sistema (DWM); altrove li arrotonda il foglio di stile.
- Barra del titolo su Windows 11: dark mode nativa nel tema scuro e colore della barra uguale allo sfondo (`theme.native_frame`, DWM attributi 20, 33, 35, 36). Su Windows 10 non succede nulla.
- Animazioni brevi: barra che scorre sotto la scheda attiva, dissolvenza della barra comandi e del foglio aperto, navigatore che si chiude e si apre scorrendo, velo del vetro. Si spengono da sole se Windows ha "Effetti di animazione" disattivato, offscreen (test e smoke) o con `TRAMA_NO_ANIMATIONS=1`.
- Cifre tabulari (Figtree `tnum`) nella griglia e nelle tabelle dei risultati.
- Ispettore largo 330 px invece di 310: a 150% con i campi arrotondati compariva la barra di scorrimento orizzontale.
- Da provare su Windows, a 100% e 150%:
  - Visualizza → Scuro, poi Chiaro, poi Come il sistema; con "Come il sistema" cambiare il tema di Windows (Impostazioni → Personalizzazione → Colori) con Trama aperta: deve seguire senza riavvio. Barra del titolo scura nel tema scuro.
  - Analizza…: la finestra dietro si sfoca e si vela; chiudendo il dialogo torna nitida. Lo stesso con Formato grafico e i dialoghi annidati (il velo resta finché è aperto il primo).
  - Tasto destro sul navigatore e una tendina qualsiasi: angoli arrotondati con ombra, senza bordi neri.
  - Caselle di spunta, frecce delle tendine e dei campi numerici visibili anche nel portabile PyInstaller (servono il modulo QtSvg e il plugin `imageformats/qsvg`).
  - Spostare la finestra tra un monitor al 100% e uno al 150%: icone nitide su entrambi.
  - Con "Effetti di animazione" spento in Windows non deve muoversi nulla.
  - `python -m trama_qt --smoke` alle due scale, anche con `TRAMA_THEME=dark`.
- Test attesi: `tests.test_qt_shell` 26/26 OK (5 nuovi: temi, icone SVG, vetro dei dialoghi modali, ombre e navigatore, cifre tabulari). Smoke Qt nel container: PASS a 1920×1080 100% (chiaro e scuro), 1920×1080 150% (chiaro e scuro), 1366×768 150%.

### cd1faeb · Fit globale: editor Qt di coefficienti e vincoli per serie (2026-11-19, ramo `claude/project-thread-7tdnhf`)

Pacchetto `Trama-Claude-Qt-Fit-Globali-095`, base main `7a7340c`. PR draft separata (non è la #56). Dettagli, sovrapposizioni con il pacchetto ANOVA in `analysis_dialog.py` e istruzioni GUI in `docs/qt-global-fit-095.md`.

- Nuovo `trama_qt/global_fit.py`: editor Coefficienti (Locale/Condiviso/Fisso, Leggi dall'equazione) ed editor Vincoli di serie (campi per serie e coefficiente, vincoli non applicabili e loro rimozione). Il dialogo ha le pagine del classico e chiama `check_options` prima del worker.
- Da provare su Windows: `linear.csv` di `tests/data/qt_global_fit`, A Locale, B Condiviso 0–4, `Control $` A fisso 1 → A 1 e 4, B 2, df 6; errore B Inferiore 3 / Superiore 1 con cursore sulla cella; Group → SD e "Rimuovi vincoli non applicabili"; `python -m trama_qt --smoke` a 100% e 150% (immagini `*-global-*.png`).
- Test attesi: `tests.test_qt_global_fit` 14/14, `tests.test_qt_shell` 20/20, suite globali OK; `verify.py --repo . --qt` del pacchetto tutto PASS.

### Ramo claude/project-thread-k3kr0a · ANOVA multifattoriale completa in Qt, pacchetto Qt-ANOVA-095 (2026-11-19)

PR draft separata verso `main` (base `7a7340c`, la merge della #56). Tre commit: editor, agganci/lingua, verifiche. Guida e passi dalla GUI in `docs/qt-anova-095.md`.

- Nuovo `trama_qt/anova_model.py`: `TermEditor` per *Model terms* (effetti principali, interazioni a 2 e a 3, Aggiungi i termini richiesti, Rimuovi i termini non disponibili, termini orfani riconoscibili) e `FactorOrder` sotto *Sums of squares* (nota del tipo, ordine dei fattori Su/Giù e Ctrl+Su/Giù per il Tipo I, anteprima dell'ordine dei termini). `Factors` della ricetta segue quell'ordine anche se diverso dalle colonne.
- `trama_qt/analysis_dialog.py`: innesti piccoli. Ramo `TERM_LIST` accanto a `EQUATION_TEXT` (sia nella costruzione sia in `options()`), lontano dal ramo `ParameterTable` che tocca il pacchetto Fit globali; `self.hidden` per i campi nascosti (Interaction order con Termini scelti); `attach` a fine `configure_fields`; in `accept()` i controlli economici del motore e i messaggi tradotti. Sovrapposizione attesa col pacchetto Fit globali: solo questo file e questa sezione del file di consegna, conflitti meccanici.
- Ricetta: stesse chiavi e omissioni del dialogo classico (Type III e Full hierarchy non aggiungono chiavi a una ricetta che non le aveva). Annulla lascia ricetta e risultati confermati.
- Lo smoke Qt (`python -m trama_qt --smoke`) ora guida anche l'ANOVA: errore di gerarchia con focus su Aggiungi i termini richiesti, correzione, Tipo I con ordine invertito, Esegui, modifica annullata, salva, riapri e ricalcolo. Screenshot `*-anova-*.png`.
- Da provare su Windows:
  - La tabella sintetica di `docs/qt-anova-095.md`, passi 1–6, in italiano e in inglese, a 100% e 150%.
  - Tab e Spazio sulle caselle dei termini; Ctrl+Su/Giù sulla lista dell'ordine; Invio sul pulsante a fuoco dopo l'errore.
  - `python -m trama_qt --smoke` a 100% e 150%: nessun testo tagliato nei dialoghi `*-anova-*`.
- `package_windows.py` non toccato: se la guida va nel portabile, aggiungi `qt-anova-095.md` all'elenco dei documenti.
- Test attesi: `tests.test_qt_anova` 14/14, `tests.test_qt_shell` 20/20, `tests.test_anova_terms` e `tests.test_anova_ss` OK. Verificatore del pacchetto: base 2 PASS + 1 FAIL (contratto Qt), testa 3 PASS. Windows NON PROVATO.

### 9c10a2f · Formule, cella con Invio e testo SVG: consegna finale per la 0.95 (2026-11-19)

**Consegna finale per la 0.95: il commit `9c10a2f`.** Il commit dopo aggiunge solo questa nota. Integra quella revisione.

- Colonne calcolate su Qt. Home → Formula… aggiunge una colonna calcolata o ne cambia una. Il doppio clic sull'intestazione di una colonna calcolata apre la sua formula, al posto del messaggio che rimandava a Tk. L'espressione viene verificata sulla tabella prima di tenerla e si può annullare. Codice in `trama_qt/formula.py` e `Project.set_formula`. Con questo la parità con la finestra classica è completa. La riproduzione di Codex (doppio clic sulla colonna calcolata) ora apre la formula.
- La cella si chiude con Invio: `closeEditor` usa `QAbstractItemDelegate.EndEditHint`, come nel candidato di Codex. Il test con F2, valore e Invio controlla che il valore sia scritto e che la selezione scenda di una riga.
- Esporta con opzioni ricorda anche Testo SVG (Tracciati) per la sessione.
- OK e Annulla tradotti in Esporta con opzioni, Formula e Proprietà del foglio Info. I testi di Qt (pulsanti dei messaggi, dialoghi file) usano `qtbase_it.qm` di PySide6 se presente (`theme.install_qt_translations`). Per il portabile serve che PyInstaller includa `PySide6/Qt/translations/qtbase_it.qm`.
- Nota per l'integrazione: la barra comandi troppo larga è corretta qui con lo scorrimento laterale di ogni scheda (b78e602). Il tuo candidato usa l'overflow delle azioni. Tieni la soluzione che preferisci: lo smoke Qt controlla solo che la finestra entri nello schermo.
- Da provare su Windows:
  - Formula… con nome "Double" e `=Control *` dà l'errore nel dialogo; con `=Control * 2` la colonna compare. Il doppio clic sulla sua intestazione riapre la formula; cambiarla in `* 3` e poi Annulla.
  - Esportare in SVG con Tracciati, poi riaprire il dialogo: Testo SVG resta su Tracciati.
  - In italiano, i pulsanti Salva/Non salvare/Annulla del messaggio di chiusura con modifiche.
  - `python -m trama_qt --smoke` a 100% e 150%.
- Test attesi: `tests.test_qt_shell` 20/20 OK. Nel container la suite completa dà 63 errori, tutti `No module named 'tkinter'` (il container non ha Tk); nessun altro errore.

### b78e602 · Smoke Qt e schermi piccoli al 150% (2026-11-19)

- Nuovo: `python -m trama_qt --smoke CARTELLA` (`trama_qt/smoke.py`), il collaudo da desktop per Qt descritto in `docs/qt-migration.md`. Gira in inglese e in italiano. Salva gli screenshot della finestra su ogni foglio e di ogni dialogo, poi scrive `report.txt` e `status.txt` (PASS o FAIL). Fallisce se un dialogo non entra nello schermo o se un testo è tagliato.
- Corretto quello che lo smoke ha trovato emulando schermi al 150%:
  - La barra dei comandi a schede imponeva alla finestra una larghezza minima di 2025 px (2231 in italiano). Ora ogni scheda scorre di lato.
  - I pulsanti delle pagine andavano a capo male e venivano tagliati. Ora stanno in un layout che va a capo (`trama_qt/flow.py`).
  - Ogni dialogo, quando si apre, viene ridotto e spostato dentro lo schermo (`theme.keep_on_screen`).
  - Importazione testo, Confronti a coppie e Forme scorrono in verticale sugli schermi bassi; i pulsanti restano sempre visibili.
- Esito nel container (offscreen con schermi emulati): PASS a 1920×1080 al 100%, 1920×1080 al 150% (1280×720 logici) e 1366×768 al 150% (911×512 logici).
- Da provare su Windows: lanciare `python -m trama_qt --smoke C:\temp\qt-smoke-100` a 100% e `...-150` a 150%. Allegare `report.txt`, guardare gli screenshot e segnalare i testi tagliati o i dialoghi fuori schermo che il controllo non vede.
- Test attesi: `tests.test_qt_shell` 19/19 OK (incluso lo smoke in inglese).

### a751bcd · Importazione guidata di file di testo su Qt (2026-11-19)

- Nuovo: File → Importa nel progetto… su un file .csv, .tsv o .txt apre l'importazione guidata. Codice in `trama_qt/text_import.py` e in `open_path` di `trama_qt/window.py`, stesso motore della versione Tk (`analisi.text_import`). Si sceglie separatore, decimali, intestazione, prima e ultima riga e colonna con salto, codice dei mancanti e `*` finale che esclude il valore. L'anteprima filtrata si aggiorna dal vivo e gli errori compaiono nel dialogo. I testi sono in italiano anche dove il dialogo Tk restava in inglese. Aprire un file di testo con Apri resta diretto.
- Con questo commit tutte le funzioni della finestra classica sono anche su Qt. Restano il porting dello smoke test e il collaudo DPI su Windows.
- Da provare su Windows:
  - File .txt con `;` e virgola decimale (ID;Dose;Risposta;Note), colonne 2–3, ultima riga 4, codice mancante -99, `*` finale attivo: in anteprima compaiono Dose e Risposta, il valore con `*` è segnato e dopo l'importazione è escluso.
  - Prima colonna "x" deve dare l'errore nel dialogo senza chiuderlo.
  - Un file non UTF-8 deve dare il messaggio di errore e non aprire il dialogo.
- Test attesi: `tests.test_qt_shell` 18/18 OK.

### ad09d92 · Catene di analisi su Qt (2026-11-19)

- Nuovo: Analizza questo risultato…, Analisi sorgente e Cambia risultato di ingresso… nella pagina dei risultati e dei grafici collegati, nella scheda Analizza e nel menu del tasto destro. Codice in `trama_qt/analysis_source.py` (scelta di sorgente e tabella, stesso comportamento del dialogo Tk) e `trama_qt/window.py` (`analyze_result_table`, `source_analysis`, `change_input_result`; `_ask` accetta la sorgente). Nel navigatore i risultati collegati compaiono sotto la loro sorgente. Il ricalcolo a catena c'era già.
- Da provare su Windows:
  - Tabella X 0..3, Y 1,3,5,7. Transform (valore assoluto), poi Analizza questo risultato → Normalize (sottrai il primo valore), poi Analizza questo risultato → Regressione lineare X/Y: pendenza 2.
  - Analisi sorgente dalla regressione: si apre Normalize sulla scheda "Normalized".
  - Cambia risultato di ingresso del Transform verso la regressione deve dare l'errore di ciclo nel dialogo.
  - Cambiare l'ingresso della regressione verso Transform/"Transformed", salvare e riaprire in Qt e in Tk: i collegamenti restano. Modificare una cella: si ricalcola tutta la catena.
- Test attesi: `tests.test_qt_shell` 17/17 OK.

### 1ab2343 · Esporta con opzioni su Qt (2026-11-19)

- Nuovo: File → Esporta con opzioni… (anche nella scheda Grafico) per grafici, layout e layout salvati. Codice in `trama_qt/export_options.py`; `export_graph` e `Project.export_layout` accettano le impostazioni. Stesse scelte del dialogo Tk: preset Schermo/Stampa/Vettoriale/Personalizzato, formato PNG/TIFF/SVG/PDF, larghezza in mm (vuota = dimensione attuale o pagina del layout), DPI per PNG e TIFF, sfondo trasparente, testo SVG come testo o tracciati, riga con dimensione finale in mm e pixel. Le scelte restano per la sessione. La destinazione passa da `check_destination`.
- Da provare su Windows:
  - Grafico a colonne, PNG a 85 mm e 200 DPI: il file deve essere largo 669 px.
  - Lo stesso in SVG con testo come tracciati: il file non deve contenere `<text>`.
  - Layout di due grafici in PDF a 180 mm: pagina larga 180 mm. In PNG deve comparire la nota sul raster.
  - Larghezza "abc" deve dare l'errore nel dialogo senza chiuderlo. Controllare i testi in italiano a 150%.
- Test attesi: `tests.test_qt_shell` 16/16 OK.

### fc63fa9 · Modifica dei fogli Info su Qt (2026-11-19)

- Nuovo: Home → Nuovo foglio Info…; nella pagina del foglio Proprietà… (nome e ambito), Sposta su/giù, Elimina foglio Info…, costanti modificabili (aggiungi, elimina, ↑↓), note con grassetto, corsivo e sottolineato (pulsanti o Ctrl+B/I/U) e Importa note… Codice in `trama_qt/info_editor.py`, `Project.change_info`/`move_info`/`update_info_sheets`. Le note si salvano dopo una pausa, uscendo dal foglio e prima di salvare. Gli stili sono contati in caratteri Python, quindi le emoji non spostano la formattazione.
- Da provare su Windows:
  - Nuovo foglio Info legato a una tabella, costante "Dose" = 10 e una formula della tabella che la usa: cambiando il valore la tabella si ricalcola.
  - Note con una parte in grassetto e un'emoji prima, salvare e riaprire in Qt e in Tk: formattazione nello stesso punto.
  - Eliminare il foglio.
- Test attesi: `tests.test_qt_shell` 15/15 OK.

### a22d53b · Famiglie di esperimenti su Qt (2026-11-19)

- Nuovo: Home → Duplica famiglia… e Salva famiglia come… (anche col tasto destro nel navigatore). Codice in `trama_qt/family.py` e `trama_qt/window.py`, più `Project.apply_family` e `Project.update_info_sheets`. Stesso motore della versione Tk (`analisi.family_workflow`): anteprima di tabelle, analisi, layout e fogli info; nome della nuova tabella o prefisso per gli altri fogli; layout inclusi. Copia e salvataggio girano in background e si possono annullare: annullando la copia non viene aggiunto niente. I risultati copiati si calcolano quando apri il foglio.
- Da provare su Windows:
  - Duplicare una tabella con grafico e layout: il nome già usato deve dare l'errore nel dialogo; con "Repeat" compaiono la tabella, il grafico e il layout copiati.
  - Salva famiglia come su un file nuovo, poi riaprirlo in Qt e in Tk.
  - Scegliere il file del progetto corrente deve dare l'errore.
- Test attesi: `tests.test_qt_shell` 14/14 OK.

### 597075b · Confronti a coppie e lettere compatte su Qt (2026-11-19)

- Nuovo: scheda Grafico, Confronti a coppie… e Lettere compatte… (`trama_qt/pairwise.py`, comando in `trama_qt/window.py`). Stessa sezione della ricetta della versione Tk: sorgente (ANOVA a una via con post-hoc, Kruskal–Wallis con Dunn, t-test appaiato fra due colonne del grafico), tutte o solo le coppie spuntate, asterischi o valore P, soglia, colore; in modalità lettere alfa, identificatori, posizione, dimensione e anteprima. Applica ricalcola il grafico; Rimuovi toglie i confronti.
- Da provare su Windows: tabella con due colonne, t-test appaiato Control/Treated, grafico a colonne delle due colonne, Confronti a coppie con valore P, Applica: compare la parentesi; poi Lettere compatte: compaiono le lettere e il foglio "Comparison letters". Salvare e riaprire in Qt e in Tk. Una soglia 2 deve dare errore. Controllare anche i testi in italiano.
- Test attesi: `tests.test_qt_shell` 13/13 OK.

### 714713a · Forme del grafico su Qt (2026-11-19)

- Nuovo: Grafico → Forme del grafico… (`trama_qt/shapes.py`): elenco con aggiungi, modifica, duplica, elimina, su/giù, elimina tutto; editor di linea (frecce: estremi, stile, dimensione), rettangolo ed ellisse (riempimento, motivo e suo colore), tratto, spessore, stile linea, opacità, livello sopra/sotto i dati, coordinate in frazioni del grafico o in unità dei dati. Stessi record e validazione di `analisi.graph_shapes`. Il disegno col mouse sul grafico resta in Tk.
- Da provare su Windows: grafico a colonne, rettangolo da (0,2; 0,3) a (0,6; 0,8) giallo con motivo diagonale + una freccia, Applica, salvare, riaprire in Qt e in Tk: forme identiche. Linea di lunghezza zero deve dare errore nel dialogo.
- Test attesi: `tests.test_qt_shell` 12/12 OK.

### 9dae6d2 · Formato della legenda su Qt (2026-11-19)

- Nuovo: in Format Graph, scheda Aspetto, il pulsante Formato legenda… (`trama_qt/legend.py`): titolo, colonne, ordine inverso, cornice (predefinita/visibile/nascosta), colori di sfondo e bordo, spessore, opacità, etichette delle singole voci, ripristino. Con questo Format Graph su Qt copre tutto quello che fa la versione Tk tranne le forme disegnate.
- Da provare su Windows: grafico XY, legenda con titolo "Gruppi", 1 colonna, cornice nascosta, etichetta di una voce cambiata, Applica, salvare, riaprire in Qt e in Tk: legenda identica. Colonne "abc" deve dare errore nel dialogo.
- Test attesi: `tests.test_qt_shell` 11/11 OK.

### 5e14f9d · Interruzioni degli assi su Qt (2026-11-19)

- Nuovo: in Format Graph, scheda Assi, sui grafici XY nativi c'è il riquadro Interruzioni asse (`trama_qt/axis_breaks.py`): asse, 2 o 3 segmenti, spazio, da/a/quota/intervallo per segmento, "Suggerisci dai dati", totale delle quote. Con un asse interrotto scala, minimo, massimo, passo e inizio di quell'asse restano disattivati. Interruzioni nuove che il grafico non può mostrare danno errore nel dialogo; quelle già salvate restano con la nota del motivo.
- Da provare su Windows: grafico XY, asse Y, 2 segmenti (5,5–6 al 50%, 6,2–6,8 al 50%), Applica, salvare, riaprire in Qt e in Tk: interruzione identica. Con quote che non fanno 100 deve comparire l'errore.
- Test attesi: `tests.test_qt_shell` 10/10 OK.

### a869f3b · Guide e bande degli assi su Qt (2026-11-19)

- Nuovo: in Format Graph, scheda Riferimenti, i pulsanti per tacche e griglie aggiuntive (guide) e per gli intervalli ombreggiati (bande) aprono i rispettivi elenchi (`trama_qt/axis_guides.py`): aggiungi, modifica, duplica, rimuovi; stessi record e stessa validazione del motore (`analisi.axis_guides`), limiti 60 guide e 12 bande. Prima restavano invariati e si modificavano solo in Tk.
- Da provare su Windows: su un grafico a colonne aggiungere una guida Y a 2,5 con etichetta e una banda Y da 4 a 6 con tratteggio, Applica, salvare, riaprire in Qt e in Tk (`--tk`): guide e bande identiche. Su un asse logaritmico un valore 0 deve dare l'errore nel dialogo, non un crash.
- Test attesi: `tests.test_qt_shell` 9/9 OK.

### d9cf4f1 · Annotazioni del grafico su Qt (2026-11-19)

- Nuovo: Grafico → Annotazioni grafico… (`trama_qt/annotations.py`): elenco, aggiungi, modifica, rimuovi; testo, unità (assi o dati), allineamento, posizione, freccia con destinazione, dimensione, colore. Validazione del motore (`analisi.graph_annotations`).
- Da provare su Windows: aggiungere un'annotazione con freccia, applicare, salvare, riaprire il `.alab` in Qt e in Tk (`--tk`): l'annotazione deve essere identica. Numeri con la virgola decimale.
- Test attesi: `tests.test_qt_shell` 8/8 OK.

### 56978a5 · Inspector dei grafici su Qt

- Nuovo: pannello laterale (Ctrl+Maiusc+I) con anteprima dal vivo, Applica/Annulla, clic sul grafico per scegliere il gruppo; prima di salvare, esportare o ricalcolare chiede cosa fare della bozza.
- Da provare su Windows: aprire l'Inspector su un box plot, cambiare colore e assi, salvare con la bozza aperta (deve comparire la domanda Applica/Scarta/Annulla).

### c0d3bd5, 05621e8, 6ee67d1 · Esportazioni, layout, Format Graph

- Esportazione grafici PNG/SVG/PDF/TIFF a 300 dpi verificata; layout PDF e SVG vettoriali; File → Esporta più fogli in PDF.
- Layout (Ctrl+L) nuovo e modifica; Format Graph (Ctrl+Maiusc+F).
- Da provare su Windows: esportare un layout in PDF e SVG e aprirli; esportare 3 fogli in un PDF e controllare l'ordine delle pagine.
