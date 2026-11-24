# Test di Brunner–Munzel

Scegli **Confronto tra gruppi → Test di Brunner–Munzel** (in inglese: *Group Comparison → Brunner–Munzel test*). Il metodo stima quanto spesso una misura del **primo** campione supera una misura del **secondo**: la probabilità di superiorità

`p = P(X > Y) + ½ P(X = Y)`

con errore standard, gradi di libertà di Welch–Satterthwaite, statistica T firmata, p-value e intervallo di confidenza. Non è un confronto delle mediane.

## Dati

| Campo | Predefinito | Significato |
|---|---|---|
| Primo campione / Secondo campione | | Due colonne numeriche distinte. I mancanti e le esclusioni si scartano **dentro** ciascuna colonna. |
| Ipotesi alternativa | Bilaterale | Anche **Maggiore** (p > ½) e **Minore** (p < ½). |
| Livello di confidenza | 95 | Strettamente tra 0 e 100. L’alternativa non sposta l’intervallo. |

Nel dialogo italiano si può scrivere `95,0`. Nella ricetta il numero resta `95.0`.

Servono almeno **2** osservazioni finite per campione. Una booleana ferma l’analisi sulla colonna. Stringhe numeriche locali (virgola decimale) sono accettate. Colonne uguali, selezioni invalide e livello fuori dominio restano segnalati sul campo.

`tests/data/brunner_munzel/columns.csv` è la coppia sintetica dell’oracolo a coppie: Primo `1, 2, 2, 5, 8` e Secondo `0, 2, 3, 3, 6, 9`. Conteggi: 12 vittorie, 2 pareggi, 16 sconfitte; `p = 13/30`.

## Calcolo

Per ogni valore di X si calcola la quota di Y strettamente inferiori più metà della quota di Y uguali; per ogni Y la quota di X strettamente superiori più metà della quota di X uguali. Le medie delle due liste coincidono con p. Vittorie, pareggi e sconfitte intere si ottengono dagli stessi passaggi sui vettori ordinati, in tempo O(N log N) e memoria lineare, senza matrice Nₓ×Nᵧ né permutazioni.

Siano `a = var(punteggi X, ddof=1)/Nₓ` e `b = var(punteggi Y, ddof=1)/Nᵧ`. Errore standard `SE = √(a+b)`, gradi di libertà `(a+b)² / (a²/(Nₓ−1) + b²/(Nᵧ−1))`, statistica `T = (p − ½) / SE` (positiva se X tende a essere maggiore). Il p-value usa la t di Student: `sf(T)` per Maggiore, `cdf(T)` per Minore, `2·sf(|T|)` per Bilaterale. L’IC bilaterale è `p ± tcrit·SE`, tagliato a [0, 1].

La statistica di SciPy `brunnermunzel` ha **segno opposto** per lo stesso orientamento; i p-value restano confrontabili. Con un solo contributo di varianza zero l’inferenza resta valida. Se SE = 0 (tutti i pareggi, separazione completa, …) si conservano probabilità e conteggi; T, gdl, p e limiti restano vuoti.

Con campioni piccoli (meno di 10 osservazioni in uno dei due) il foglio Settings riporta una nota sull’approssimazione.

## Fogli

I nomi restano in inglese, come le altre ricette.

* **Brunner–Munzel**: una riga con `Nx`, `Ny`, `Wins`, `Ties`, `Losses`, `Probability`, `SE`, `T`, `df`, `P`, `Lower`, `Upper`.
* **Settings**: nomi dei campioni, orientamento del segno, alternativa, livello, conteggio di mancanti/esclusioni per campione, nota sull’approssimazione e, se serve, il motivo dell’inferenza assente.

Non c’è un grafico.

## Limiti

* Solo due campioni indipendenti.
* L’inferenza è un’approssimazione di Student; per campioni molto piccoli preferire cautela nell’interpretazione.
* Il collaudo di riferimento include 50.000 × 50.000 valori con circa il 20% di pareggi: il calcolo resta lineare in memoria.
* Scala di sistema 150% su Windows: **NON PROVATO** se assente dal collaudo della macchina.

Riferimento: Brunner e Munzel (2000), *The nonparametric Behrens-Fisher problem: asymptotic and exact solutions*, Biometrical Journal 42, 17–25; `scipy.stats.brunnermunzel`.
