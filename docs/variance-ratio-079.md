# Confronta due varianze

Il metodo sta in Group Comparison, subito dopo `Lognormal t-test`. Il nome nel menu è `Compare two variances`. Non sostituisce il test t e non sceglie Student o Welch.

## Cosa calcola

Due campioni indipendenti. L’ordine First / Second resta l’ordine del rapporto: `r = s1² / s2²`, e il rapporto delle DS è la radice di `r`. I gradi di libertà sono `n − 1` per ciascun campione.

La statistica F riportata a parte è la varianza più grande divisa per la più piccola. I gradi di libertà del numeratore e del denominatore sono quelli del gruppo che sta davvero al numeratore e al denominatore. Se le due varianze sono uguali, il numeratore è il primo campione.

Il p a due code è `min(1, 2·min(F.cdf(r), F.sf(r)))` con i gradi di libertà orientati, non con quelli della F ripiegata. L’intervallo è quello esatto della F per `r`, non un intervallo di Wald. L’intervallo del rapporto delle DS è la radice dei due estremi.

Servono almeno due valori finiti per gruppo e varianze campionarie positive. I mancanti si tolgono dentro ciascun campione, non a coppie. Testo non numerico, booleani e infiniti sono rifiutati. `Lognormal` usa i logaritmi naturali dei valori strettamente positivi. `Normal` è il default.

Un campione costante è un errore sul campo, senza p o intervallo inventati. Una varianza non rappresentabile come float finito resta mancante nel foglio; il rapporto si riporta lo stesso se è rappresentabile. Se il rapporto o l’intervallo non sono rappresentabili, il calcolo dice perché e non scrive 0 o infinito.

## Fogli e figura

`Variance comparison` ha una colonna `Value` e le quattordici quantità numeriche. `Summary` e `Settings` registrano n, mancanti, l’orientamento con le etichette scritte dall’utente e la scala usata. I nomi dei fogli restano inglesi.

La figura è facoltativa: `None`, `Variance ratio` o `SD ratio`. È un punto con l’intervallo disegnato fra gli estremi veri, il riferimento a 1 e l’asse x logaritmico. Il metodo non entra in `GRAPH_METHODS`: senza figura il navigatore non elenca un grafico; con la figura richiesta la voce c’è anche prima del ricalcolo.

## Accanto al test delle medie

`Show variance comparison` è disattivato di default. Compare solo per Welch e Student del `t-test` e del `Lognormal t-test`. È assente nei disegni appaiati e a un campione, e in quel caso non entra nella ricetta. Non cambia le medie né la scelta di Student o Welch. Se il controllo non si può calcolare, il foglio nuovo contiene solo la ragione e il test delle medie resta.

Il livello del controllo sul t-test è 95. Sul test lognormale è il livello scelto per quel test. I dati sono gli stessi del test delle medie: per il lognormale si ripassano i valori positivi già accettati, e il confronto applica di nuovo il logaritmo.

## Dialogo

Il primo controllo resta nel dialogo. Un input non valido torna sul campo, si corregge senza chiudere, e Annulla non aggiunge un’analisi. Una modifica successiva dei dati che rende il confronto non valido riapre il dialogo e conserva l’ultimo risultato riuscito. Il worker non usa Tk.

Le etichette e gli errori sono tradotti. I valori salvati restano i nomi inglesi. Standard e Modern si applicano all’avvio successivo, non a metà sessione.
