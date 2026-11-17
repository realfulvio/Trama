# Intervalli dei parametri nelle equazioni personalizzate

In **Regression and Curves → Fit custom equation**, la scheda **Output**
permette di scegliere **Parameter intervals**:

- **Symmetric (Wald)** mantiene gli intervalli simmetrici precedenti, al livello
  scelto in **Confidence level (%)**. È il valore predefinito anche quando una
  ricetta salvata non contiene questa nuova opzione.
- **Profile likelihood** calcola limiti extra-SS, generalmente asimmetrici,
  intorno al fit confermato. Il calcolo avviene sul worker e può essere annullato
  dalla barra inferiore. Annullare conserva l'ultimo risultato completato.

Il parser delle equazioni resta ristretto: non esegue codice Python. Nella
ricetta vengono salvati soltanto testo, numeri, flag e la scelta canonica del
metodo, indipendentemente dalla lingua dell'interfaccia.

## Significato del profilo

Per ciascun coefficiente libero, Trama fissa un valore di prova e ristima gli
altri coefficienti liberi, rispettando i loro vincoli. I coefficienti dichiarati
**Fixed** restano ai valori inseriti e non contano nei gradi di libertà del fit.
Con `df = N − p`, i limiti invertono la soglia
`SS_profile = SS_min × (1 + F(level; 1, df)/df)`.

Si usano le osservazioni complete dello stesso fit e le loro SD relative, quando
inserite. Le SD restano fisse in ogni ristima. Un cambio comune della loro unità
non cambia gli intervalli. Le SD specificano scale relative degli errori, non
varianze assolute note; una varianza residua comune viene stimata dai dati.
Questo metodo non propaga l'incertezza delle SD e non aggiunge nuove pesature
all'analisi personalizzata.

I fogli **Parameters**, **Fit**, **Residuals** e **Curve** conservano le stime,
gli errori standard, le osservazioni e la geometria del fit confermato. Con il
profilo attivo, cambiano i limiti in **Parameters** e compare un foglio
**Parameter CI status** per gruppo, con metodo, livello, df, pesatura e stato
di ciascun estremo:

| Stato | Significato |
| --- | --- |
| Profile root | La ricerca ha trovato la soglia di confidenza |
| Parameter bound | L'insieme connesso raggiunge il limite imposto al coefficiente |
| Fixed | Il coefficiente non è stimato; non ha un intervallo |
| Unavailable | Estremo non determinato; il foglio ne riporta il motivo |

Un coefficiente su un vincolo può avere un profilo unilaterale anche quando il
suo SE Wald non è disponibile. Il vincolo rimane distinguibile da una radice di
confidenza; non viene presentato come un limite stimato senza vincoli.

## Limiti e compatibilità

- Al massimo 8 coefficienti liberi e 5.000 osservazioni complete per fit con
  ricerca di profilo. Le equazioni interamente fisse non richiedono questa ricerca.
- Un budget comune di 20.000 valutazioni e 10 milioni di valori residui copre
  tutte le ricerche dei gruppi della stessa richiesta.
- Un estremo fuori budget, non identificabile o non finito rimane non
  disponibile con motivo. Non viene sostituito da un intervallo Wald.
- La ricerca segue una soluzione locale e l'insieme connesso intorno alla stima:
  non enumera tutti i rami disgiunti. L'inferenza non lineare è approssimata,
  soprattutto con pochi dati o vincoli attivi.
- I progetti precedenti mantengono i quattro fogli e i risultati Wald. Per
  ricalcolare una ricetta con il nuovo profilo serve Trama 0.76 o successiva.

[Intervalli delle equazioni a catalogo](nonlinear-parameter-intervals.md) ·
[Funzionalità](features.md)
