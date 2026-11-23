# Kaplan–Meier simultaneous bands · Bande simultanee di Kaplan–Meier

English first, Italiano più sotto (*[vai alla versione italiana](#italiano)*).

## English

In **Survival Analysis → Kaplan–Meier survival**, the **Uncertainty** field of the graph options (the *Options* page of the Qt dialog, the *Graph* tab of the classic Tk one) has a fifth choice, **Hall–Wellner simultaneous band** (Italian: *Banda simultanea Hall–Wellner (conservativa)*). It draws, for each curve, one band that is meant to hold the true survival function **at all the times of that curve together**, at the level of **Confidence level (%)**, and it adds the sheet *Simultaneous confidence bands* with the numbers behind the drawing.

The pointwise intervals are not removed: they stay in the *Curve: …* sheets, in the median limits and in every other sheet, exactly as without the choice. The new choice replaces only the *drawing* of the pointwise band, bars or error bars. The default stays **None**, and recipes saved before this version open and recalculate with identical output. *Interval method* (log-log or symmetric Greenwood) changes the pointwise limits only, so it has no effect on this band.

### What the level means, and what it does not

- The nominal level refers to the times of **one** curve. A figure with several groups shows **one band per curve**; the guide makes **no claim of joint coverage across the groups** (the legend uses the plural, *bands*, for the same reason).
- The band is **conservative**: its quantile is the one for the supremum of the Brownian bridge over the **whole** interval [0, 1]. A band built for a narrower range of times would use a smaller constant and be narrower, but it would be a different procedure with a different statement. Expect wide bands, most of all with few subjects and early in follow-up, where the log-log transform is steep.
- It is an asymptotic result. With very small groups the real coverage is only approximate (the bands of the example below, with 8 subjects, are shown to explain the numbers, not as a recommended sample size).

### How it is computed

For each curve, *N* is the number of subjects at the start, after the filters, missing values and exclusions that the analysis already applies. At each distinct time with *d* events among *Y* at risk, using the same rows and the same convention for tied times as the Kaplan–Meier (events first, censored subjects at that time still at risk):

```text
S  ← S · (1 − d / Y)                  survival step
G  ← G + d / [Y (Y − d)]              Greenwood factor
c  = scipy.stats.kstwobign.isf(α),    α = 1 − level / 100
```

For 0 < *S* < 1:

```text
z = log(−log S)
w = c · (1 + N·G) / ( √N · |log S| )
g(x) = exp(−exp(x))
lower = g(z + w)        upper = g(z − w)
```

`g` is evaluated without overflow, so a huge `z + w` gives 0 and a very negative `z − w` gives 1. A time with only censored subjects has the state and the limits of the current step.

**Where there are no limits.** If *S* = 1 (no event yet), if *S* = 0 (every subject at risk had the event, so *G* is not finite) or if *G* is not finite, the limits are empty, the **Status** is *Unavailable* and the **Reason** column says why. The survival values and the terminal times are kept. In the figure the band **stops** in those regions: it does not start before the first event and it ends at the last time with limits. A group whose subjects are all censored, or whose only times end with every subject having the event, is drawn without a band and its rows say *Unavailable*.

### The sheet *Simultaneous confidence bands*

One row per group and distinct time. Quantities are **fractions**, even when the graph shows percentages.

| Column | Content |
|---|---|
| Group | The group (*All* for one curve; with several grouping variables the usual combined name). |
| Time | Each distinct time of the group. |
| At risk | Subjects at risk just before the time. |
| Events | Events at the time. |
| Survival | The Kaplan–Meier estimate after the time. |
| Greenwood factor | *G* after the time. Empty when it is not finite. |
| Simultaneous CI lower, Simultaneous CI upper | The limits, empty when the status is *Unavailable*. |
| Status | *Available* or *Unavailable*. |
| Reason | Empty when available; otherwise the sentence that explains it. |

With several response columns the sheet has a leading **Response variable** column and groups are numbered as in the other sheets of that run. The window's CSV export writes the table index as an unnamed first column, as it does for every result table.

### In the figure

- The band is a **step band** in the **color of its curve**. On *Cumulative events* it shows [1 − upper, 1 − lower]; with *Percent* both limits are multiplied by 100.
- The legend names the band and the level, for example *95% simultaneous band*; with several curves it is *95% simultaneous bands*, because each band has the color of its curve (the entry is drawn in neutral gray then). The label is kept as short as a curve label on purpose: a longer one squeezes the panels of a compact multi-response figure. The method name is in the dialog, in the sheet and here. Several bands over one another are hard to read: for many groups, draw them in separate graphs or keep only the curves you need.
- The risk table, the censor marks, the median and its limits, the log-rank test, the p value and every pointwise table are unchanged.
- The SVG export is fully vector (every band is a path); PDF too.

### A worked example

`tests/data/survival_bands/fixture.csv` (synthetic) has four groups that exercise the special cases: *Control* (8 subjects, an event and a censor at the same time, last event with *S* = 0), *Treatment* (7 subjects, a censor before any event), *Censored* (all censored) and *Terminal tie* (two events at the same time). At 95% (*c* = 1.3581) the *Control* rows are:

| Time | At risk | Events | S | G | lower | upper | Status |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 2 | 0.7500 | 0.0417 | 0.0697 | 0.9694 | Available |
| 2 | 5 | 0 | 0.7500 | 0.0417 | 0.0697 | 0.9694 | Available |
| 3 | 4 | 1 | 0.5625 | 0.1250 | 0.0472 | 0.8973 | Available |
| 6 | 2 | 1 | 0.2812 | 0.6250 | 0.0000 | 0.8773 | Available |
| 8 | 1 | 1 | 0 | empty | empty | empty | Unavailable |

At time 1: *z* = log(−log 0.75) = −1.2459, *w* = 1.3581 · (1 + 8 · 0.0417) / (√8 · 0.2877) = 2.2252, so the limits are g(0.9793) = 0.0697 and g(−3.4711) = 0.9694. The pointwise 95% interval at the same time is 0.3148 to 0.9309.

### How it was checked

An independent oracle (`tests/data/survival_bands/verify.py`) computes the Kolmogorov quantile by the series and bisection, and the risk sets by a plain loop, without SciPy or the program. `python tests/data/survival_bands/verify.py` checks the oracle alone and `--repo PATH` compares the real dispatcher at 90, 95 and 99% on both curves; `tests/test_survival_bands.py` and `tests/test_qt_survival_bands.py` repeat the comparison and cover the figure, the dialog in both languages, several responses, exclusions and a project round trip. The Windows native behavior is **not tested**.

References: SAS/STAT *PROC LIFETEST* (Hall–Wellner bands and the log-log transformation, [documentation](https://support.sas.com/documentation/onlinedoc/stat/151/lifetest.pdf)); SciPy [`kstwobign`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kstwobign.html) (asymptotic distribution of the supremum of the Brownian bridge). Using the quantile over the whole interval is the choice of this package.

## Italiano

In **Analisi di sopravvivenza → Sopravvivenza di Kaplan–Meier** il campo **Incertezza** delle opzioni del grafico (pagina *Opzioni* del dialogo Qt, scheda *Grafico* di quello Tk classico) ha una quinta scelta, **Banda simultanea Hall–Wellner (conservativa)** (in inglese *Hall–Wellner simultaneous band*). Per ogni curva disegna una banda pensata per contenere la vera funzione di sopravvivenza **in tutti i tempi di quella curva insieme**, al livello di **Livello di confidenza (%)**, e aggiunge il foglio *Simultaneous confidence bands* con i numeri del disegno.

Gli intervalli puntuali non vengono tolti: restano nei fogli *Curve: …*, nei limiti della mediana e in ogni altro foglio, identici a quelli ottenuti senza la scelta. La nuova scelta sostituisce solo il *disegno* della banda, delle barre o degli errori standard puntuali. Il predefinito resta **Nessuno** e le ricette salvate prima di questa versione si aprono e si ricalcolano con risultati identici. *Metodo dell’intervallo* (log-log o Greenwood simmetrico) cambia solo i limiti puntuali e quindi non influisce su questa banda.

### Che cosa significa il livello e che cosa no

- Il livello nominale si riferisce ai tempi di **una** curva. Un grafico con più gruppi mostra **una banda per curva**: **non si afferma alcuna copertura congiunta fra i gruppi** (la legenda usa il plurale, *bands*, per lo stesso motivo).
- La banda è **conservativa**: il quantile è quello del massimo del ponte browniano sull’**intero** intervallo [0, 1]. Una banda costruita su un intervallo ristretto di tempi userebbe una costante più piccola e sarebbe più stretta, ma sarebbe un’altra procedura con un’altra affermazione. Aspettati bande larghe, soprattutto con pochi soggetti e nei tempi iniziali, dove la trasformazione log-log è ripida.
- Il risultato è asintotico. Con gruppi molto piccoli la copertura reale è solo approssimata (l’esempio sotto, con 8 soggetti, serve a spiegare i numeri, non è una dimensione campionaria consigliata).

### Come si calcola

Per ogni curva, *N* è il numero di soggetti all’inizio, dopo i filtri, i valori mancanti e le esclusioni che l’analisi già applica. A ogni tempo distinto con *d* eventi su *Y* a rischio, con le stesse righe e la stessa convenzione sui pari tempo del Kaplan–Meier esistente (prima gli eventi; i censurati a quel tempo restano a rischio):

```text
S  ← S · (1 − d / Y)                  passo della sopravvivenza
G  ← G + d / [Y (Y − d)]              fattore di Greenwood
c  = scipy.stats.kstwobign.isf(α),    α = 1 − livello / 100
```

Per 0 < *S* < 1:

```text
z = log(−log S)
w = c · (1 + N·G) / ( √N · |log S| )
g(x) = exp(−exp(x))
inferiore = g(z + w)    superiore = g(z − w)
```

`g` si valuta senza overflow: un `z + w` enorme dà 0 e un `z − w` molto negativo dà 1. Un tempo con soli censurati eredita stato e limiti del gradino corrente.

**Dove non ci sono limiti.** Se *S* = 1 (nessun evento ancora), se *S* = 0 (tutti i soggetti a rischio hanno avuto l’evento, quindi *G* non è finito) o se *G* non è finito, i limiti sono vuoti, lo **Status** è *Unavailable* e la colonna **Reason** ne dice il motivo. I valori di sopravvivenza e i tempi terminali si conservano. Nel grafico la banda **si interrompe** in quelle regioni: non parte prima del primo evento e termina all’ultimo tempo con limiti. Un gruppo tutto censurato, o i cui tempi finiscono tutti con l’evento di ogni soggetto, è disegnato senza banda e le sue righe riportano *Unavailable*.

### Il foglio *Simultaneous confidence bands*

Una riga per gruppo e tempo distinto, con le colonne descritte sopra nella versione inglese (*Group, Time, At risk, Events, Survival, Greenwood factor, Simultaneous CI lower, Simultaneous CI upper, Status, Reason*). Le quantità sono **frazioni**, anche quando il grafico mostra le percentuali; il fattore di Greenwood è vuoto quando non è finito. Con più colonne di risposta il foglio ha una colonna iniziale **Response variable** e i gruppi sono numerati come negli altri fogli di quell’analisi. L’esportazione CSV della finestra scrive l’indice della tabella come prima colonna senza nome, come per ogni tabella dei risultati.

### Nel grafico

- La banda è a **gradini** e ha il **colore della sua curva**. Su *Eventi cumulativi* mostra [1 − superiore, 1 − inferiore]; con *Percentuale* entrambi i limiti sono moltiplicati per 100.
- La legenda nomina la banda e il livello, per esempio *95% simultaneous band*; con più curve diventa *95% simultaneous bands*, perché ogni banda ha il colore della propria curva (la voce è in grigio neutro). L’etichetta è corta di proposito, come quelle delle curve: una più lunga schiaccia i pannelli di un grafico compatto a più risposte. Il nome del metodo è nella finestra, nel foglio e in questa guida. Molte bande sovrapposte si leggono male: con tanti gruppi conviene usare grafici separati o tenere solo le curve che servono. I testi dei grafici restano in inglese come nelle altre analisi.
- Tabella a rischio, simboli delle censure, mediana e suoi limiti, test log-rank, p e tutte le tabelle puntuali non cambiano.
- L’esportazione SVG è completamente vettoriale (ogni banda è un tracciato); anche il PDF.

### Esempio svolto

`tests/data/survival_bands/fixture.csv` (sintetico) ha quattro gruppi che esercitano i casi limite: *Control* (8 soggetti, un evento e una censura nello stesso tempo, ultimo evento con *S* = 0), *Treatment* (7 soggetti, una censura prima di ogni evento), *Censored* (tutti censurati) e *Terminal tie* (due eventi nello stesso tempo). Al 95% (*c* = 1,3581) le righe di *Control* sono quelle della tabella inglese. Al tempo 1: *z* = log(−log 0,75) = −1,2459, *w* = 1,3581 · (1 + 8 · 0,0417) / (√8 · 0,2877) = 2,2252 e i limiti sono g(0,9793) = 0,0697 e g(−3,4711) = 0,9694. L’intervallo puntuale al 95% allo stesso tempo è da 0,3148 a 0,9309.

### Come è stato verificato

Un oracolo indipendente (`tests/data/survival_bands/verify.py`) calcola il quantile di Kolmogorov con la serie e la bisezione e i gruppi a rischio con un ciclo semplice, senza SciPy né il programma. `python tests/data/survival_bands/verify.py` controlla l’oracolo da solo e `--repo PERCORSO` confronta il vero dispatcher al 90, 95 e 99% su entrambe le curve; `tests/test_survival_bands.py` e `tests/test_qt_survival_bands.py` ripetono il confronto e coprono la figura, il dialogo nelle due lingue, più risposte, esclusioni e il salvataggio con riapertura. Il comportamento di Windows nativo **non è provato**.

Riferimenti: SAS/STAT *PROC LIFETEST* (bande Hall–Wellner e trasformazione log-log, [documentazione](https://support.sas.com/documentation/onlinedoc/stat/151/lifetest.pdf)); SciPy [`kstwobign`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kstwobign.html) (distribuzione asintotica del massimo del ponte browniano). Usare il quantile sull’intero intervallo è una scelta conservativa di questo pacchetto.
