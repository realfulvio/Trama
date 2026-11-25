# Verifica della regressione di Passing–Bablok

Base pubblica `v0.110.0`, commit `6be79ae7068b679a76e5beb30127cdda343d381c`. Macchina del notebook: Linux 7.3.5-2-cachyos x86_64, Python 3.14.10, PySide6 6.12.0. I comandi partono dal worktree `passing-bablok`, con `uv run --no-project python`. Il calcolo verificato è `7d6ae5cf3627e863072d275cbb9de81224ceec2c`. Questo commit nomina quella revisione e non cambia il calcolo.

## Oracle

R 4.5.3 (2026-03-11), mcr 1.3.3.1, installati in un prefisso locale. Comando, per ciascun campione:

```r
mcreg(x, y, method.reg = "PaBa", method.ci = "analytical",
      slope.measure = "tangent", alpha = 0.05)
getCoefficients(fit)
```

`R.version.string` è `R version 4.5.3 (2026-03-11)`. `packageVersion("mcr")` è `1.3.3.1`.

Sui due campioni di `tests/data/passing-bablok/casi.json` le stime coincidono: pendenza 2 e intercetta 1; pendenza 2,25 e intercetta −1,875. Con quattro coppie mcr scrive `LCI = -Inf` e `UCI = Inf`. Trama lascia vuote le celle e la nota dice che i limiti non sono stimabili.

Il campione dispari di 11 coppie, y = 3x + (−1)^x, e il campione pari di 16 coppie intere del test hanno estremi finiti. Le differenze rispetto a `getCoefficients` restano sull’ultima cifra binaria. Lo stesso vale per la correlazione negativa x = 1…10, y = 20, 18, 17, 14, 12, 11, 9, 7, 5, 2: pendenza −2, intervallo −2…−1,8, intercetta 22,5, intervallo 21,5…22,5. I numeri sono fissati in `test_interior_intervals_match_the_recorded_mcr_run`.

Un valore negativo fa fermare mcr con `Passing-Bablok regression for negative values is not available.` Trama adatta la retta e lo scrive nelle note. È una scelta aperta: la formula delle pendenze non richiede valori positivi.

`verifica_casi.py` del pacchetto, eseguito nella cartella estratta, stampa `PASS: two synthetic reference fits`. Quello script scarta le pendenze esattamente −1. mcr le tiene, e il programma fa come mcr. Sui due campioni pubblicati non ce ne sono, quindi i due controlli coincidono.

## Tempi

`fit_values`, seme 7, rumore normale, picco di `tracemalloc` durante la chiamata:

| Coppie | Pendenze | Secondi | Picco MiB |
| --- | ---: | ---: | ---: |
| 500 | 124750 | 0,015 | 8,6 |
| 1000 | 499500 | 0,057 | 34,3 |
| 2000 | 1999000 | 0,172 | 137,3 |

Il limite è 2 000 000 pendenze, controllato prima di `triu_indices`. Duemila coppie passano. 2001 coppie si fermano sul campo X e il test verifica che l’allocazione non parta. Due milioni di float64 sono 16 MB per il solo vettore delle pendenze; il picco misurato a 2000 coppie è più alto perché restano anche gli indici e gli angoli. Il tetto di mcr nel sorgente C è 2·10⁸, troppo grande per un calcolo interattivo.

L’annullamento è un `Event` già impostato, o una funzione che restituisce vero: in entrambi i casi parte `ChainCancelled` prima dell’allocazione e il test non vede le pendenze costruite.

## Display

Smoke nativo, inglese e italiano, temi chiaro e scuro, finestre richieste 1024×768 e 1600×1000: **PASS**. Piattaforma Wayland, schermo eDP-1, area utile 1920×1080, device pixel ratio 1,0, DPI logico 96. `QT_SCALE_FACTOR` non impostato. 32 screenshot.

Le finestre richieste sono state disegnate a quella misura, tranne la prima finestra italiana in tema chiaro: 1024×768 è diventata 1280×820. La stessa richiesta, in tema scuro, è restata 1024×768. Lo screenshot a 1024 della guida è quello scuro.

Lo stesso smoke a scala 1,5 emulata, non nativa: `QT_QPA_PLATFORM=xcb` e `QT_SCALE_FACTOR=1.5`. Inglese e italiano, temi chiaro e scuro, solo 1024×768: **PASS**. Piattaforma xcb, area utile 1280×689, device pixel ratio 1,5, DPI logico 96. L’altezza disegnata è 1024×670, perché 768 non entra in 689. 1600×1000 non è stato chiesto a questa scala: non entra nell’area utile.

Lo smoke apre `tests/data/passing-bablok/passing-bablok.alab`, controlla 2,25 e −1,875, la retta di identità e le due righe lasciate fuori, salva, riapre e, dopo aver messo 8 nella Y di U1, ricalcola 2,75 e −3,375. Il progetto riapribile è [passing-bablok.alab](examples/passing-bablok.alab). Le figure PNG, SVG e PDF dello smoke sono in `docs/media/passing-bablok-en-figure.svg` e `.pdf`.

## Windows

Questi esiti riguardano il collaudo Linux del prototipo. Il collaudo nativo Windows al 100% e al 150% è da completare sul candidato integrato.

## Suite

```
python -m unittest tests.test_passing_bablok tests.test_catalog tests.test_compare_lines tests.test_nb2_regression
```

I test del metodo, il catalogo, il confronto fra rette e la regressione NB2 sono verdi. Il confronto fra rette resta all’indice 1 del gruppo. NB2 resta subito dopo la regressione multipla.

```
python -m unittest discover -s tests
```

5412 test in 2363,614 s. 34 saltati. 0 failure. 79 error, ed esito di processo 1. Tutti e 79 nominano `tkinter` e `libtk8.6.so`: 78 traceback più `test_startup`, il cui processo figlio importa `tkinter` e termina con stato 1. Lo stesso import, su questa macchina, fallisce con `libtk8.6.so`. Nessuna asserzione è fallita. Tk non è stato installato.
