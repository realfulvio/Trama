# Intervalli inversi su curve non lineari

Disponibile nella beta 0.73.0. Le regole e i limiti sotto descrivono il percorso supportato.

`Interpolate a standard curve`, direzione `X from Y`, può calcolare un intervallo di Mean response o di Prediction per One-phase decay e per i quattro modelli 4PL a pendenza variabile (stimolazione e inibizione, X in concentrazione o in log10). One-phase association resta solo stima puntuale. `Uncertainty` = `None` e l'inverso lineare non cambiano tabelle, legenda né geometria.

## Calcolo

Si usa lo stesso fit della stima puntuale: stessa covarianza, stesso SSE e stessi gradi di libertà. Non c'è un secondo fit, non si scartano standard e C non viene riscalata. Non è un profilo di verosimiglianza, una banda simultanea, un bootstrap o un'estrapolazione. X in log10 resta in unità log10. A concentrazione 0 vale il limite della curva.

L'insieme è `{x nel dominio osservato : (f(x) − risposta)² ≤ w(x)²}`. Per la media, `w` è il quantile t per la varianza del valore stimato. Per la predizione della media di k nuove risposte si aggiunge `s²/k`. Il risultato è una lista ordinata di intervalli chiusi disgiunti. Un solo pezzo compila X lower e X upper con Complete, Clipped low, Clipped high o Clipped both, con la stessa regola CLIPPED dell'inverso lineare: un singleton sull'estremo basso del dominio è Clipped low. Più pezzi lasciano vuoti i limiti scalari, segnano Disconnected e compilano il foglio Inverse interval components. Il vuoto fra i pezzi non viene riempito.

Fuori dal codominio della curva, o con una risposta non identificabile, la stima puntuale resta quella di prima e l'intervallo resta vuoto, con la Reason esplicita. Un fit non idoneo (gradi di libertà, residuo esatto, covarianza, parametro al bordo) segna Uncertainty unavailable. La ricerca non parte per le righe fuori range o non identificabili.

La ricerca isola e raffina le radici, con la stima puntuale fra i campioni obbligatori. Non inverte la griglia di 200 punti del grafico. Se il budget non certifica ogni componente, il risultato è Uncertainty unavailable e non un intervallo inventato. Budget: 256 query, 50.000 valutazioni per query, 5 milioni per studio. Il controllo di campi e budget avviene prima del worker. La ricerca gira sul worker delle altre analisi, non con un protocollo di annullamento a blocchi come Monte Carlo: il limite è il budget di valutazioni.

## Dialogo

Per i cinque modelli l'interfaccia mostra Uncertainty, Confidence level (%) e, per Prediction, Replicate count column. Association li nasconde. Una chiamata di `calibration_visibility` senza `model` mantiene il comportamento precedente e continua a nascondere Uncertainty sull'inverso non lineare. I valori dei menu restano gli identificatori inglesi, anche con l'interfaccia italiana. Le etichette, la nota nel dialogo e i messaggi di campo usano `calib.inverse_nonlinear.*`. La nota è la stessa frase di Interval note nei Fit diagnostics. Un errore di campo resta sul campo, con il dialogo aperto; un errore scoperto dal worker riapre il dialogo con i valori inseriti e il focus sul campo.

Sul grafico i pezzi sono segmenti orizzontali alla risposta richiesta, colore `#9a3412`, senza una linea che attraversi un vuoto. La legenda è `{livello}% mean response interval` oppure `{livello}% prediction interval`. Un intervallo di larghezza nulla usa il marcatore `|`.

