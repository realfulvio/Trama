# Cartelle Excel su Qt: importare più fogli, esportare dati e risultati

Due comandi nel gruppo **File** della finestra Qt:

- **Importa cartella Excel…** / *Import Excel workbook…*
- **Esporta cartella Excel…** / *Export Excel workbook…*

Il motore è `analisi/xlsx_exchange.py` (nessuna dipendenza da Qt); i dialoghi sono in
`trama_qt/excel_workbook.py`. L'apertura storica di un `.xlsx` (File → Apri / Importa, tutti i fogli con
intestazione in riga 1) e l'import CSV non cambiano.

## Importa cartella Excel…

1. Scegli un `.xlsx`. I formati con macro (`.xlsm`, o un `.xlsx` che contiene `vbaProject.bin`) e quelli
   binari (`.xls`, `.xlsb`) non sono accettati.
2. Il dialogo elenca **tutti** i fogli nell'ordine della cartella, con il nome letterale, lo stato
   (visibile, nascosto, molto nascosto) e le dimensioni indicative (quelle che Excel ha memorizzato, «—» se
   mancano). Sono preselezionati solo i fogli visibili leggibili; nascosti e molto nascosti si possono
   spuntare a mano. Un foglio con sole celle vuote e un foglio grafico non si possono scegliere.
3. Per il foglio selezionato l'anteprima mostra le prime 12 righe e 12 colonne con le coordinate Excel
   (lettere e numeri di riga). Ogni foglio ha la sua **Riga d'intestazione** (da 1, predefinita 1) oppure
   **Senza intestazioni**: in quel caso le colonne si chiamano `Column 1`, `Column 2`… e la prima riga entra
   nei dati. Sotto i comandi c'è l'elenco dei **nomi effettivi in Trama** (duplicati e intestazioni vuote
   normalizzati come nell'apertura storica: `Dose`, `Dose (2)`, `Column 4`). Le righe sopra l'intestazione
   sono in grigio e vengono scartate; la riga d'intestazione è in grassetto.
4. Un'intestazione oltre l'ultima riga con valori è un errore visibile sotto l'anteprima, segnato anche con
   un'icona sul foglio nell'elenco, e disattiva **Importa** finché non si corregge.
5. **Importa** legge tutti i fogli scelti in background (barra di avanzamento e Annulla nella barra di stato)
   e li aggiunge **tutti insieme** solo se ognuno è stato letto e validato. Annulla, un errore su un foglio o
   una selezione vuota non aggiungono nulla. I nomi in collisione con tabelle già presenti diventano
   `Nome (2)`… come in ogni altro import.

### Come vengono letti i valori

| In Excel | In Trama |
| --- | --- |
| Testo | testo letterale, sempre: `0007`, `=etichetta`, `@codice`, `12` scritto come testo |
| Numero | numero (intero o decimale) |
| VERO/FALSO | booleano |
| Cella vuota | mancante (lo zero resta zero) |
| Data, ora, data e ora | testo ISO: `2026-04-06`, `08:15:00`, `2026-04-06T12:30:00` (una colonna con sole date a mezzanotte resta senza ora) |
| Formula | il **risultato memorizzato** nel file; nessuna formula viene calcolata |
| Formula senza risultato memorizzato | mancante, con un avviso che elenca foglio e coordinate |
| Valore di errore (`#DIV/0!`…) | mancante, con un avviso che elenca foglio e coordinate |
| Formula che punta ad altre cartelle | il risultato memorizzato; i collegamenti esterni non vengono mai seguiti |

Una colonna con tipi diversi (numeri e testo) resta mista e letterale. Le righe vuote in mezzo restano, quelle
finali vengono tolte; un'intestazione senza righe di dati è ammessa (tabella vuota con le sue colonne).
Gli avvisi compaiono nell'anteprima e, dopo l'import, in un riquadro informativo.

Limiti (gli stessi dell'apertura storica, controllati anche durante la lettura vera): file fino a 32 MiB,
contenuto decompresso fino a 128 MiB, 512 colonne e 2.000.000 di celle per foglio, 256 tabelle per progetto.

## Esporta cartella Excel…

1. Il dialogo elenca i **fogli dati** e le **singole tabelle risultato** (nome completo «analisi · tabella» e
   tipo). È già spuntato il foglio o la tabella risultato che hai davanti, se si può esportare. I risultati
   non calcolati o non aggiornati restano in elenco, in grigio, con il motivo, e non si possono scegliere.
   L'export legge lo stato com'è: non ricalcola niente.
2. Spunta più voci e mettile in ordine con **Su**/**Giù** (anche Alt+↑/Alt+↓). La colonna **Nome Excel**
   mostra il nome finale di ogni foglio prima di salvare. Per i dati si parte dal titolo del foglio, per i
   risultati da «tabella · analisi» (per esempio `Multiple comparisons · One-way ANOVA of Gruppi`), così la
   parte che distingue le tabelle della stessa analisi resta entro i 31 caratteri.
3. Scegli il file `.xlsx`. Se esiste già, Trama chiede se sostituirlo; con No non cambia nulla.
4. La scrittura gira in background con avanzamento e Annulla.

Cosa finisce nel file:

- **Dati**: lo stesso frame dell'esportazione CSV (formule di Trama già calcolate, valori esclusi lasciati
  vuoti).
- **Risultati**: la tabella con i suoi indici come prime colonne. I nomi dei livelli restano; un indice senza
  nome diventa `Row` (un livello) o `Level 1`, `Level 2`… (più livelli). Se il nome coincide con una colonna
  della tabella, cede il passo all'indice: `Row (2)`. Le intestazioni a più livelli si uniscono con ` · `.
- Testi e intestazioni sono **celle stringa esplicite** qualunque sia il primo carattere (`=`, `+`, `-`,
  `@`, `#N/A`): nessuna formula eseguibile entra nel file.
- Mancanti → celle vuote; numeri finiti e booleani mantengono il tipo; date e orari → testo ISO.

### Nomi dei fogli

Deterministici: i caratteri `[ ] : * ? / \` e quelli di controllo diventano `_`, gli apostrofi ai bordi
spariscono, un nome vuoto diventa `Sheet`, al massimo **31 unità UTF-16** (come le conta Excel: un'emoji
vale due e non viene mai spezzata), unici senza distinzione tra maiuscole e minuscole, `History` è riservato.
Le collisioni prendono ` (2)`, ` (3)`… accorciando il nome per restare nei 31.

### Valori che Excel cambierebbe

L'export si ferma, indica foglio, riga Excel e colonna e chiede di correggere i dati quando trova:

- interi con più di 15 cifre (Excel conserva 15 cifre significative e li arrotonderebbe in silenzio);
- infinito;
- testi oltre 32.767 caratteri;
- caratteri di controllo o non scrivibili;
- più di 1.048.575 righe di dati in un foglio.

Precisione: le celle numeriche XLSX sono double IEEE 754 come in Trama, quindi i decimali tornano identici
quando il file viene riletto; Excel però **mostra e calcola** con 15 cifre significative.

### Scrittura sicura

Trama scrive su un file temporaneo nascosto (`.~trama-*.xlsx`) nella stessa cartella di destinazione, lo
riapre per verificarlo e solo dopo, e dopo l'eventuale conferma di sovrascrittura, lo mette al posto del file
(spostamento atomico). Annulla prima della pubblicazione, un errore, una cartella in cui non si può scrivere o
una destinazione bloccata (per esempio aperta in Excel) lasciano il file precedente intatto e cancellano il
temporaneo. openpyxl usa anche file temporanei suoi nella cartella temporanea di sistema durante la scrittura:
vengono cancellati alla fine o all'annullamento.

## API del motore

```python
from analisi.xlsx_exchange import inspect_workbook, read_workbook, write_workbook

inspect_workbook(path)                  # [SheetInfo(name, state, kind, rows, columns, empty)]
read_workbook(path, {"Controlli": 2, "Campioni α": 1})   # {nome: DataFrame} nell'ordine dato
read_workbook(path, {"Foglio": None})   # senza intestazioni
write_workbook(path, [("Nome", frame), ...], overwrite=False)   # nomi Excel pubblicati
```

Parametri solo per parola chiave: `warnings` (lista che riceve gli avvisi), `progress(fatti, totale)`,
`cancel` (un `threading.Event`). Errori: `ValueError` per file illeggibili, opzioni non valide o dati non
scrivibili (la causa originale resta in `__cause__`), `FileExistsError` con `overwrite=False`,
`ExchangeCancelled` per Annulla. `WorkbookReader` tiene aperta la cartella per anteprime e lettura;
`prepare_workbook` scrive e verifica il temporaneo e restituisce un oggetto con `publish(overwrite=…)` e
`discard()`.

## Prestazioni

Misure nel container Linux di sviluppo (4 CPU logiche Xeon 2,3 GHz, 15 GB) su due fogli da 50.000 × 20
(14 colonne decimali, 3 intere, 3 di testo): vedi `excel-timings.txt` dello smoke. Ordine di grandezza:
apertura + anteprima < 1 s, import di entrambi i fogli ≈ 8 s, export ≈ 13 s (22,9 MB), risposta ad Annulla
< 0,2 s. La scrittura usa openpyxl in modalità streaming; con `lxml` installato sarebbe più veloce, ma non è
una dipendenza di Trama.

Due accorgimenti: l'export scrive l'elemento `<dimension>` di ogni foglio, e la lettura non analizza un intero
foglio solo per scoprire che quell'elemento manca (openpyxl in sola lettura lo farebbe all'apertura di ogni
foglio senza dimensione, cioè di quasi tutti i file scritti in streaming).

## Collaudo

```bash
python -m unittest tests.test_xlsx_exchange tests.test_qt_excel_workbook
# smoke dedicato, preferenze isolate nella cartella, tema da TRAMA_THEME (predefinito chiaro):
python -m trama_qt --smoke CARTELLA --scenario qt-excel-workbook
TRAMA_THEME=dark python -m trama_qt --smoke CARTELLA-scuro --scenario qt-excel-workbook
# giro completo (include lo scenario):
python -m trama_qt --smoke CARTELLA
```

Lo scenario scrive in `CARTELLA`: `<lingua>-excel-*.png`, `excel-<lingua>/excel-report.txt` (byte e hash
prima e dopo, temporanei), `excel-timings.txt` (tempi a freddo e a caldo, memoria di picco), `report.txt`,
`status.txt`.
