# Trama 0.71.0 beta

Questa è una build beta, con funzionalità ancora incomplete e possibili errori. Tutte le release 0.x precedenti sono anch’esse beta; la prima versione definitiva non è ancora disponibile.

La 0.71 riunisce la nuova interfaccia A e gli strumenti statistici completati nel ciclo di integrazione.

- **Interfaccia:** ribbon a gruppi, griglia e navigatore aggiornati, font coerenti e dialoghi adattati allo spazio disponibile.
- **Fit globali personalizzati:** bande puntuali della risposta media o di predizione e previsioni per serie da nuove X, dallo stesso fit congiunto.
- **Test lognormali:** disegni appaiato, Welch, Student e a un campione, con rapporti geometrici e intervalli bilaterali.
- **PCA:** selezione fissa, Kaiser, varianza cumulativa e analisi parallela ripetibile con seed.
- **Regressione lineare:** IC della media Y a X fissata e insieme di confidenza inverso per X a Y fissata; componenti illimitate o disconnesse esplicite.
- **Regressione multipla gaussiana:** pesi osservati, da SD o da colonna, diagnostica WLS e profili con precisione futura esplicita. I pesi dipendenti da Y danno inferenza condizionale ai pesi fissati.
- **ANOVA:** diagnostica dei residui multifattoriali, grafici delle assunzioni, Brown–Forsythe delle varianze e Bartlett a una via. Il test delle varianze resta distinto dal Brown–Forsythe sulle medie.

Le nuove opzioni sono facoltative e conservano i percorsi legacy quando spente. Le chiavi delle ricette restano canoniche passando fra italiano e inglese. Fonte dati, risultati, grafici, layout ed export restano collegati.

## Correzioni d'integrazione

I test di revisione coprono cambi estremi delle unità, rapporti nulli molto grandi o piccoli, pesi di training e futuri di ordini diversi, residui piccoli e varianza nulla. I calcoli combinano scale/esponenti prima dei prodotti rischiosi; le inferenze lognormali non dipendono dall'offset comune delle unità. Le previsioni WLS lavorano sulla deviazione standard futura quando la varianza intermedia supera il range, mantenendo i limiti finiti rappresentabili. La degenerazione dei residui è valutata nello spazio coerente con i pesi.

La validazione dei campi WLS resta nel dialogo; il fit numerico viene eseguito sul worker e gli errori tardivi con campo nominato ripristinano i parametri inseriti. Un errore conserva il risultato confermato.

Il catalogo di analisi, le etichette dei campi, le scelte e i principali messaggi del dialogo sono disponibili in italiano. Le ricette restano indipendenti dalla lingua; alcuni fogli di risultati ed editor specialistici mantengono ancora testi inglesi.

La 0.71 resta un'applicazione scientifica indipendente. Le singole funzioni e i formati importati hanno limiti documentati; non viene dichiarata equivalenza universale con altri prodotti né validazione clinica. La verifica di release, i dati sintetici e le schermate native sono registrati nel repository insieme al relativo artefatto.

[Esiti e metadati del collaudo 0.71](validation-071.md).

