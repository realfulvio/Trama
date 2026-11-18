# ANCOVA con medie aggiustate

In **Analyze → Group Comparison → ANCOVA** (in italiano **Analizza → Confronto tra gruppi → ANCOVA**) si confrontano i livelli di un fattore tenendo conto di una covariata numerica. Il modello è la regressione lineare della risposta sulla covariata con un'intercetta per gruppo. Il risultato principale sono le **medie aggiustate**: il valore atteso della risposta di ciascun gruppo a uno stesso valore della covariata, la **X di riferimento**.

Le chiavi della ricetta sono canoniche inglesi in entrambe le lingue; la lingua cambia solo etichette e messaggi.

## Opzioni

Il dialogo ha tre schede: **Variables**, **Model**, **Comparisons** (*Variabili*, *Modello*, *Confronti*).

| Chiave canonica | Italiano | Valore iniziale |
| --- | --- | --- |
| `Response` | Risposta | vuoto |
| `Covariate` | Covariata | vuoto |
| `Group` | Gruppo | vuoto |
| `Slope model` | Modello delle pendenze | `Common` |
| `Reference X` | X di riferimento | vuoto (media della covariata) |
| `Reference domain` | Dominio del riferimento | `Common range` |
| `Comparisons` | Confronti | `All pairs` |
| `Control group` | Gruppo di controllo | vuoto |
| `Adjustment` | Correzione | `Holm` |
| `Confidence level (%)` | Livello di confidenza (%) | `95` |
| `Graph` | Grafico | `Fitted lines` |

Valori ammessi:

- `Slope model`: `Common` (*Comune*) o `By group` (*Per gruppo*).
- `Reference domain`: `Common range` (*Intervallo comune*) o `Allow extrapolation` (*Consenti estrapolazione*).
- `Comparisons`: `All pairs` (*Tutte le coppie*), `Against control` (*Contro il controllo*) o `None` (*Nessuno*).
- `Adjustment`: `Holm`, `Bonferroni` o `None` (*Nessuna*).
- `Graph`: `Fitted lines` (*Rette adattate*), `Adjusted means` (*Medie aggiustate*) o `Residuals` (*Residui*).

Il valore nella ricetta resta sempre quello inglese, anche con l'interfaccia in italiano: lo stesso `.alab` produce lo stesso risultato nelle due lingue. `Reference X` vuoto vale `null` nella ricetta; la virgola decimale è accettata in input. **Gruppo di controllo** compare solo con *Contro il controllo* e **Correzione** non si applica con *Nessuno*: i campi nascosti non entrano nella ricetta. Cambiando la colonna del gruppo, un controllo che non esiste più viene svuotato.

## Modello

Con *z* = *X* − *X*ᵣ (la covariata centrata sul riferimento) e *D* la matrice degli indicatori di gruppo:

- **Common**: matrice di progetto `[D, z]`. Una pendenza comune a tutti i gruppi; le medie aggiustate sono i coefficienti di *D* e la differenza fra due gruppi è la stessa a ogni *X*.
- **By group**: matrice `[D, D·z]`. Ogni gruppo ha la sua pendenza; le medie aggiustate sono ancora i coefficienti di *D*, cioè i valori adattati **in** *X*ᵣ. La differenza fra gruppi dipende da *X*, quindi ha senso solo al riferimento scelto.

La stima è OLS su una QR con colonne equilibrate; la covarianza è s²(AᵀA)⁻¹ calcolata dal fattore triangolare, quindi le varianze non escono negative per arrotondamento. La scelta fra i due modelli è dell'utente: il test sulle pendenze uguali è una diagnostica, non un passaggio automatico.

**X di riferimento.** Vuoto = media di tutti i valori completi della covariata. Con **Common range** il riferimento deve cadere nell'intervallo di covariata condiviso da tutti i gruppi (dal massimo dei minimi al minimo dei massimi); con **Allow extrapolation** può uscirne, e le righe delle medie aggiustate lo segnalano in `Extrapolated`. Un riferimento troppo lontano dai dati per un calcolo stabile è comunque rifiutato.

**Test.** Due test F annidati sulle righe complete:

- `Equal slopes`: Common contro By group (*q* = *k* − 1 gradi di libertà al numeratore).
- `Groups at reference`: i gruppi hanno la stessa media aggiustata a *X*ᵣ, nel modello scelto.

**Confronti.** Differenze **Primo − Secondo** fra medie aggiustate, con la covarianza completa dei coefficienti, intervalli *t* **puntuali** al livello scelto (non bande simultanee) e p grezzo. `All pairs` produce tutte le coppie nell'ordine dei gruppi; `Against control` confronta ogni altro gruppo con il controllo. La correzione per confronti multipli (**Holm** o **Bonferroni**) agisce solo sui p finiti; con `None` il p corretto coincide con il grezzo. Con `Comparisons = None` il foglio `ANCOVA contrasts` non viene prodotto.

Si assume: osservazioni indipendenti, una sola varianza d'errore per tutti i gruppi, relazione lineare fra covariata e risposta dentro ogni gruppo. Il grafico dei residui aiuta a giudicarlo, ma non è un test.

**Adattamento esatto.** Se la somma dei quadrati residua è al più 1·10⁻¹² volte la somma dei quadrati totale, i residui sono trattati come zero: `RSS`, `MSE` ed errori standard valgono 0, mentre intervalli, *t*, *F* e *p* restano vuoti e `Status` è `Exact fit`, senza numeri fuorvianti.

## Fogli

I fogli sono in inglese, come gli altri report.

| Foglio | Contenuto |
| --- | --- |
| `ANCOVA model` | Una riga: `N, Groups, Residual df, RSS, MSE, Reference X, Common lower, Common upper, Slope model, Status, Note`. |
| `ANCOVA tests` | `Test, F, Numerator df, Denominator df, p, Status`: `Equal slopes` e `Groups at reference`. |
| `Adjusted means` | `Group, N, Reference X, Mean, SE, Lower, Upper, Extrapolated, Slope, Status`, una riga per gruppo. |
| `ANCOVA contrasts` | `First, Second, Difference, SE, df, Lower, Upper, t, p, Adjusted p, Status`; assente con `Comparisons = None`. |
| `ANCOVA fitted` | `Source row, Observed, Fitted, Residual, Group, Covariate`, una riga per osservazione usata. |

`Source row` conserva l'indice della tabella anche se è testuale, ripetuto o non consecutivo. L'identità del gruppo è tipizzata: `1`, `1.0` e `"1"` restano gruppi distinti quando i dati li distinguono.

## Grafici

- **Fitted lines**: punti per gruppo, retta adattata di ciascuno sul suo intervallo di covariata, rombo bianco sulla media aggiustata e linea verticale tratteggiata alla X di riferimento. Per un gruppo che non osserva il riferimento la retta continua con un tratto puntinato fino al riferimento (*Extrapolated to the reference*).
- **Adjusted means**: la media aggiustata di ogni gruppo con il suo intervallo di confidenza puntuale; i marcatori vuoti indicano i gruppi estrapolati.
- **Residuals**: residui contro valori adattati, uno stile per gruppo, con il riferimento a zero.

I grafici si aprono nelle viste normali di Trama e supportano Inspector, esportazione vettoriale e raster, salvataggio nel progetto e ricalcolo.

## Limiti

- da **2 a 12 gruppi** con valori completi;
- almeno **3 osservazioni complete per gruppo**, con almeno due valori di covariata distinguibili in ciascuno;
- al massimo **50.000 osservazioni** complete;
- celle vuote o righe escluse restano fuori dal calcolo; testo, infiniti o dati complessi in risposta o covariata sono un errore sul campo.

## Errori

Gli errori che il dialogo può già conoscere restano nel dialogo, con il messaggio che nomina il campo e il focus su di esso (traduzione in italiano inclusa).

| Condizione | Campo |
| --- | --- |
| Colonna vuota, assente o ripetuta (nomi di colonna non univoci: Risposta) | Risposta, Covariata o Gruppo |
| Dati con testo, infiniti, complessi o interi oltre la precisione | il campo della colonna |
| Meno di 2 o più di 12 gruppi; gruppo con meno di 3 righe | Gruppo |
| Covariata costante in un gruppo, o modello non identificabile | Covariata |
| Gruppi senza intervallo comune | Dominio del riferimento |
| Riferimento fuori dall'intervallo comune | X di riferimento |
| Riferimento troppo lontano per un calcolo stabile; valori non rappresentabili | X di riferimento |
| Confidenza non numerica o fuori da 0–100 (estremi esclusi) | Livello di confidenza (%) |
| Controllo mancante, sconosciuto o ambiguo | Gruppo di controllo |

## Ricalcolo e ricette

La ricetta salva le chiavi canoniche e i valori inglesi (`Reference X` come numero o `null`). Alla riapertura il dialogo riproduce le scelte nella lingua corrente. Se una ricalcolazione non riesce (per esempio perché i dati sono cambiati e un gruppo ha perso righe), il risultato precedente resta visibile con l'indicazione che non è aggiornato e l'esportazione è bloccata finché il dialogo di ricalcolo non produce un risultato valido.

## Verifica

- 54 test unitari sul motore (`tests/test_ancova.py`), con un oracolo statsmodels congelato in `tests/data/ancova/`.
- 6 test Tk sul dialogo (`tests/test_ancova_dialog.py`).
- Smoke mirato: `TRAMASTAT_SMOKE_ONLY=ancova python tramastat.py --smoke DIR`; fa parte anche dello smoke completo.
- Windows e DPI reali: **non provati** in questa consegna.
