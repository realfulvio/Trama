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

- Tema chiaro, scuro o "Come il sistema" (predefinito): Visualizza → Come il sistema / Chiaro / Scuro. La scelta resta salvata (`QSettings` TramaStat/Trama, chiave `qt/theme`), `TRAMA_THEME=light|dark|system` la forza. In "Come il sistema" il tema cambia da solo quando Windows passa da chiaro a scuro (`styleHints().colorSchemeChanged`). I grafici restano su carta bianca.
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
