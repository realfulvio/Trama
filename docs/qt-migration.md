# Migrazione a PySide6/Qt

Trama include un'interfaccia Qt nativa (PySide6) e l’interfaccia Classica (Tk). Entrambe usano il motore statistico in `analisi/` e leggono e scrivono progetti `.alab`.

## Avvio

| Comando | Interfaccia |
| --- | --- |
| `python tramastat.py [file]` | Tk classica (predefinita) |
| `python tramastat.py --tk [file]` | Tk classica |
| `python tramastat.py --qt [file]` | Qt |
| `python -m trama_qt [file]` | Qt diretta |

Il portabile include **Trama - Tk.cmd** e **Trama - Qt.cmd**. Da Qt, **File → Apri nell’interfaccia Classica** può salvare e riaprire il progetto in Tk.

## Cosa c'è (fase 1, essenziale)

- Foglio dati virtuale (`QTableView`): modifica, incolla/taglia/copia, Canc, inserisci/elimina righe e colonne, rinomina, escludi celle, annulla/ripeti. Colonne calcolate con Home → Formula…: si aggiungono o si cambiano, anche con doppio clic sull'intestazione, e l'espressione viene verificata prima di tenerla.
- Dialogo analisi per tutti i 95 metodi del motore, con ricerca, campi tradotti e messaggio di errore sul campo.
- Calcolo in background con avanzamento e annulla; ricalcolo a catena dei risultati collegati quando cambiano i dati.
- Tabelle dei risultati, grafici matplotlib (barra di navigazione), layout salvati.
- Fogli Info (Home → Nuovo foglio Info…): nome e ambito, costanti modificabili (aggiungi, elimina, sposta), note con grassetto/corsivo/sottolineato (Ctrl+B/I/U) e importazione da testo, sposta ed elimina foglio. Le costanti lette dalle formule ricalcolano le loro tabelle.
- Apri/importa (stessi formati della versione Tk), salva `.alab`, esporta tabelle CSV e grafici PNG/SVG/PDF/TIFF a 300 dpi con verifica del file; layout in PDF e SVG vettoriali; File → Esporta più fogli in PDF con ordine, larghezza e sfondo trasparente.
- Format Graph (Ctrl+Maiusc+F): titolo ed etichette, font e dimensioni, legenda, cornice, griglie, assi (scala, minimo/massimo, passo, tacche, decimali), serie (colore, linea, simbolo, etichetta), asse destro e stile delle serie XY, linee di riferimento, tacche e griglie aggiuntive (guide) e intervalli ombreggiati (bande) degli assi, interruzioni degli assi sui grafici XY (2 o 3 segmenti, suggerite dai dati), formato della legenda (titolo, colonne, ordine, cornice, sfondo, etichette delle voci), ripristino dei predefiniti.
- Inspector dei grafici (Ctrl+Maiusc+I): pannello laterale con anteprima dal vivo, Applica/Annulla, clic sul grafico per scegliere box e violini; chiede cosa fare di una bozza prima di salvare, esportare o ricalcolare.
- Annotazioni di testo e frecce sul grafico (Grafico → Annotazioni grafico…).
- Confronti a coppie e lettere compatte su box, violini e grafici a colonne (Grafico → Confronti a coppie… / Lettere compatte…): sorgente, coppie, asterischi o valori P, soglia, colore; lettere con alfa, identificatori, posizione e dimensione.
- Famiglie di esperimenti (Home → Duplica famiglia… / Salva famiglia come…, anche dal menu del navigatore): anteprima del contenuto, nome o prefisso, layout inclusi; copia e salvataggio in background, annullabili.
- Forme sul grafico (Grafico → Forme del grafico…): linee con o senza frecce, rettangoli ed ellissi, con tratto, riempimento, motivo, opacità, livello e coordinate in frazioni o dati; ordinabili.
- File → Esporta con opzioni… per grafici e layout: preset Schermo/Stampa/Vettoriale, PNG/TIFF/SVG/PDF, larghezza in mm, DPI, sfondo trasparente e testo SVG come testo o tracciati, con dimensione finale in anteprima; le scelte restano per la sessione, compreso il testo SVG.
- Catene di analisi: Analizza questo risultato… (nuova analisi sulla tabella dei risultati aperta), Analisi sorgente, Cambia risultato di ingresso… (sorgente e tabella, con controllo dei cicli e revisione dei parametri); nel navigatore i risultati collegati stanno sotto la loro sorgente. Anche nella scheda Analizza e col tasto destro.
- File → Importa nel progetto… su un file .csv/.tsv/.txt apre l'importazione guidata: separatore, decimali, intestazione, prima/ultima riga e colonna con salto, codice dei mancanti, `*` finale che esclude il valore, anteprima filtrata dal vivo. Aprire un file di testo senza importare resta diretto, come in Tk.
- Layout (Ctrl+L): nuovo e modifica, con nome, carta, colonne, sfondo e fino a 12 pannelli ordinabili.
- Tema "Scientifico compatto"/Vetro: Figtree, icone Lucide, accento #0B7A73.

## Cosa resta su Tk (fasi successive)

Le funzioni della finestra classica sono tutte su Qt. Resta il collaudo su Windows reale (Codex), da fare con lo smoke Qt qui sotto.

## Smoke Qt (collaudo da desktop)

`python -m trama_qt --smoke CARTELLA` gira sullo schermo vero, in inglese e in italiano. Apre un piccolo progetto, calcola un risultato, grafici e un layout, apre ogni comando che mostra un dialogo e scrive in CARTELLA:

- `<lingua>-<nome>.png` con la finestra su ogni foglio e ogni dialogo, alla scala corrente;
- `report.txt` con schermo, scala, versione di Qt e i problemi trovati;
- `status.txt` con `PASS` o `FAIL`; il codice di uscita è 0 o 1.

Un dialogo fallisce se non entra nell'area disponibile dello schermo o se un pulsante, una casella o un'etichetta è più stretta del suo testo. Va lanciato a 100% e a 150%. In Linux si emula uno schermo con `QT_QPA_PLATFORM="offscreen:configfile=schermo.json"`: per esempio 1366×768 al 150% è `{"screens": [{"name": "s", "x": 0, "y": 0, "width": 1366, "height": 768, "logicalDpi": 144, "logicalBaseDpi": 96, "dpr": 1.0}]}`. Lo smoke Tk (`python tramastat.py --smoke`) resta per la versione classica.

## Note per l'integrazione

- Dipendenza nuova: `PySide6-Essentials==6.12.0` (LGPLv3, librerie dinamiche non modificate; avvisi in `THIRD_PARTY_NOTICES.md`).
- `build.ps1` aggiunge `matplotlib.backends.backend_qtagg`; PyInstaller raccoglie PySide6 con il suo hook.
- Il tema Vetro su Tk va fermato: il lavoro grafico prosegue solo su Qt.
- Test: `python -m unittest tests.test_qt_shell` (offscreen; saltato se PySide6 non c'è). Windows **non provato**.
