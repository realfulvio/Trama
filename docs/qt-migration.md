# Migrazione a PySide6/Qt

Dalla 0.95 Trama si apre con un'interfaccia Qt nativa (PySide6). Il motore statistico in `analisi/` non cambia: Qt e Tk leggono e scrivono gli stessi progetti `.alab`.

## Avvio

| Comando | Interfaccia |
| --- | --- |
| `python tramastat.py [file]` | Qt (default se PySide6 è installato) |
| `python tramastat.py --tk [file]` | Tk classica |
| `python -m trama_qt [file]` | Qt diretta |

Senza PySide6 l'avvio ricade su Tk. Da Qt, **File → Open in classic interface** salva il progetto e lo riapre in Tk per le funzioni non ancora migrate.

## Cosa c'è (fase 1, essenziale)

- Foglio dati virtuale (`QTableView`): modifica, incolla/taglia/copia, Canc, inserisci/elimina righe e colonne, rinomina, escludi celle, annulla/ripeti, colonne calcolate in sola lettura.
- Dialogo analisi per tutti i 95 metodi del motore, con ricerca, campi tradotti e messaggio di errore sul campo.
- Calcolo in background con avanzamento e annulla; ricalcolo a catena dei risultati collegati quando cambiano i dati.
- Tabelle dei risultati, grafici matplotlib (barra di navigazione), layout salvati, fogli info in sola lettura.
- Apri/importa (stessi formati della versione Tk), salva `.alab`, esporta tabelle CSV e grafici PNG/SVG/PDF/TIFF a 300 dpi con verifica del file; layout in PDF e SVG vettoriali; File → Esporta più fogli in PDF con ordine, larghezza e sfondo trasparente.
- Format Graph (Ctrl+Maiusc+F): titolo ed etichette, font e dimensioni, legenda, cornice, griglie, assi (scala, minimo/massimo, passo, tacche, decimali), serie (colore, linea, simbolo, etichetta), asse destro e stile delle serie XY, linee di riferimento, tacche e griglie aggiuntive (guide) e intervalli ombreggiati (bande) degli assi, interruzioni degli assi sui grafici XY (2 o 3 segmenti, suggerite dai dati), formato della legenda (titolo, colonne, ordine, cornice, sfondo, etichette delle voci), ripristino dei predefiniti.
- Inspector dei grafici (Ctrl+Maiusc+I): pannello laterale con anteprima dal vivo, Applica/Annulla, clic sul grafico per scegliere box e violini; chiede cosa fare di una bozza prima di salvare, esportare o ricalcolare.
- Annotazioni di testo e frecce sul grafico (Grafico → Annotazioni grafico…).
- Layout (Ctrl+L): nuovo e modifica, con nome, carta, colonne, sfondo e fino a 12 pannelli ordinabili.
- Tema "Scientifico compatto"/Vetro: Figtree, icone Lucide, accento #0B7A73.

## Cosa resta su Tk (fasi successive)

1. Forme disegnate sul grafico.
2. Esporta con opzioni (dimensione in mm, DPI, testo SVG) come nella finestra classica.
3. Famiglie di esperimenti, interfaccia delle catene di analisi, confronti a coppie sul grafico.
4. Modifica dei fogli info, procedura guidata di importazione testo.
5. Porting dello smoke test (`--smoke`) su Qt e collaudo DPI su Windows reale.

Quando tutto è migrato si toglie `--tk` e la dipendenza da Tk.

## Note per l'integrazione

- Dipendenza nuova: `PySide6-Essentials==6.12.0` (LGPLv3, librerie dinamiche non modificate; avvisi in `THIRD_PARTY_NOTICES.md`).
- `build.ps1` aggiunge `matplotlib.backends.backend_qtagg`; PyInstaller raccoglie PySide6 con il suo hook.
- Il tema Vetro su Tk va fermato: il lavoro grafico prosegue solo su Qt.
- Test: `python -m unittest tests.test_qt_shell` (offscreen; saltato se PySide6 non c'è). Windows **non provato**.
