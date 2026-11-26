# Test di mancato adattamento con repliche

In **Regressione multipla**, scegli **Lineare** e apri **Diagnostica e previsioni**.
Attiva **Test di mancato adattamento sulle repliche**. La scheda dei risultati
separa la somma dei quadrati residua in errore puro e mancato adattamento.

Una replica ha gli stessi valori per tutti i predittori numerici e categorici.
Il test usa le righe complete del fit lineare senza pesi. Con N righe complete,
U combinazioni distinte e rango r, i gradi di libertà sono N − U per l’errore
puro e U − r per il mancato adattamento. La statistica F è il rapporto tra
il quadrato medio del mancato adattamento e quello dell’errore puro.
Il test presuppone errori indipendenti, normali e con varianza costante.
[NIST/SEMATECH Engineering Statistics Handbook](https://itl.nist.gov/div898/handbook/pmd/section4/pmd446.htm)

Se mancano repliche, gradi di libertà o variabilità entro le repliche,
il foglio indica il motivo per cui F e p restano vuoti. Le regressioni
pesate mantengono le proprie stime e diagnostiche. L’opzione è disattivata
per impostazione iniziale.

Il progetto di esempio **repliche.alab** è incluso nel portabile. Sul suo
modello additivo, N = 8, U = 4 e r = 3. Le somme dei quadrati sono 40
(residua), 8 (errore puro) e 32 (mancato adattamento), con F = 16 e p ≈ 0,01613009.

## English

In **Multiple regression**, choose **Linear**, then enable **Replicate lack-of-fit
test** under **Diagnostics and predictions**. The report splits the residual
sum of squares into pure error and lack of fit. Replicate observations share all
numeric and categorical predictors. The example **repliche.alab** is included in
the portable download and gives F = 16 and p ≈ 0.01613009.
