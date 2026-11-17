# Equazioni condizionali (modelli a tratti) — 0.81

In **Regression and Curves → Fit custom equation** e **Global fit custom equation**
la pagina **Equation** (in italiano **Equazione**) ha la scelta **Equation syntax**
(**Sintassi dell'equazione**):

- **Arithmetic** (**Aritmetica**) è la grammatica di sempre ed è il valore
  predefinito. Una ricetta salvata senza questo campo si legge come Arithmetic e dà
  le stesse tabelle e le stesse linee di prima; una ricetta aritmetica nuova viene
  salvata senza il campo.
- **Conditional** (**Condizionale**) aggiunge `if(condizione, valore se vera, valore se falsa)`,
  anche annidato, per scrivere modelli a tratti.

Cambiare sintassi non riscrive l'equazione e non toglie righe dei coefficienti:
un'equazione che non vale nella sintassi scelta resta com'è, con l'errore sotto il
campo, finché non la correggi.

## Grammatica

Nella sintassi Conditional:

- confronti `<  <=  >  >=  ==  !=` fra numeri, esatti (senza tolleranza);
- condizioni combinate con `not`, `and`, `or`, in quest'ordine di precedenza, e
  raggruppate con le parentesi: `(X>=L) and (X<=U)`;
- i confronti concatenati non sono ammessi: scrivi `(0<X) and (X<1)`, non `0<X<1`;
- un confronto non è un numero: si usa solo come condizione di `if(...)`;
- `if`, `and`, `or`, `not` sono parole della sintassi e non possono essere nomi di
  coefficienti (in Arithmetic restano nomi validi, come prima).

Ogni ramo è calcolato solo dove vale la sua condizione, e anche il lato destro di
`and`/`or` solo dove serve: `if(X>0, log(X), 0)` è definita anche per X ≤ 0. Se una
condizione non è un numero finito su un punto usato (per esempio `log(X)` con X ≤ 0
dentro la condizione), l'analisi si ferma e il messaggio indica X e la riga di
origine. Su una riga di previsione la stessa situazione dà lo stato
`Undefined model` solo per quella riga.

Esempi (la guida della pagina Equation li offre con il pulsante **Insert** /
**Inserisci**):

```
if(X<T, A+B*X, A+C*X)
if(X<T1, A, if(X<T2, B, C))
if((X>=L) and (X<=U), A*X, 0)
```

Il parser resta quello ristretto delle equazioni personalizzate: è scritto a mano e
non usa `eval`, `exec`, `compile` né l'AST di Python.

## Soglie note, non punti di cambio stimati

Ogni coefficiente letto in una condizione deve essere **Fixed**: il fit usa soglie
note e **non stima punti di cambio**. Un coefficiente di soglia libero è rifiutato
prima di qualsiasi calcolo, con il campo **Parameters** in evidenza.

Nel fit globale una soglia può essere **Fixed** per tutte le serie oppure **Local**
con un valore fisso per *ogni* serie in **Series constraints** (**Vincoli di serie**).
Una soglia **Shared** libera, o locale non fissata per qualche serie, è rifiutata.

Stime, errori standard e intervalli sono quindi condizionati alle soglie scelte. Il
foglio **Fit** (o **Global fit**) dei risultati condizionali riporta
`Equation syntax = Conditional` e la riga `Conditions` con le soglie tenute fisse.

## Risultati e grafico

- I fogli **Curve** (e **Curve bands** nel fit globale) hanno una colonna **Branch**
  che identifica il ramo di ogni punto: una cifra per ogni `if` (1 vero, 2 falso,
  0 non raggiunto). La colonna c'è solo con la sintassi Conditional.
- La linea disegnata e le bande si interrompono dove cambia il ramo: nessun tratto
  collega due rami attraverso la soglia.
- CSV, **Use Result as Data**, esportazioni PNG/SVG/PDF e layout seguono le tabelle
  e la figura come per gli altri fit.

## Collaudo

Test: `python -m unittest tests.test_conditional_equations tests.test_conditional_fit tests.test_conditional_i18n`.

Smoke desktop mirato (finestra grande quanto lo schermo, tema dalle preferenze,
inglese e italiano):

```sh
TRAMASTAT_SMOKE_ONLY=piecewise-equations xvfb-run -a -s '-screen 0 1024x768x24' python tramastat.py --smoke DIR
TRAMASTAT_SMOKE_ONLY=piecewise-equations xvfb-run -a -s '-screen 0 1600x1000x24' python tramastat.py --smoke DIR
```

Lo smoke fa parte anche di quello completo. Windows nativo e DPI 125/150%: NON PROVATO.
