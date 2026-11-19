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
- Apri/importa (stessi formati della versione Tk), salva `.alab`, esporta tabelle CSV e grafici PNG/SVG/PDF/TIFF a 300 dpi.
- Format Graph (Ctrl+Maiusc+F): titolo ed etichette, font e dimensioni, legenda, cornice, griglie, assi (scala, minimo/massimo, passo, tacche, decimali), serie (colore, linea, simbolo, etichetta), asse destro e stile delle serie XY, linee di riferimento, ripristino dei predefiniti. Interruzioni, guide e bande degli assi, formato della legenda e annotazioni restano come sono e si modificano in Tk.
- Tema "Scientifico compatto"/Vetro: Figtree, icone Lucide, accento #0B7A73.

## Cosa resta su Tk (fasi successive)

1. Inspector dei grafici, forme e annotazioni; editor di interruzioni, guide e bande degli assi e del formato della legenda.
2. Editor dei layout, esportazione PDF multipagina.
3. Famiglie di esperimenti, interfaccia delle catene di analisi, confronti a coppie sul grafico.
4. Modifica dei fogli info, procedura guidata di importazione testo.
5. Porting dello smoke test (`--smoke`) su Qt e collaudo DPI su Windows reale.

Quando tutto è migrato si toglie `--tk` e la dipendenza da Tk.

## Note per l'integrazione

- Dipendenza nuova: `PySide6-Essentials==6.12.0` (LGPLv3, librerie dinamiche non modificate; avvisi in `THIRD_PARTY_NOTICES.md`).
- `build.ps1` aggiunge `matplotlib.backends.backend_qtagg`; PyInstaller raccoglie PySide6 con il suo hook.
- Il tema Vetro su Tk va fermato: il lavoro grafico prosegue solo su Qt.
- Test: `python -m unittest tests.test_qt_shell` (offscreen; saltato se PySide6 non c'è). Windows **non provato**.
