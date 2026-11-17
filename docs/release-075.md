# Trama 0.75.0 beta

Gli intervalli dei parametri con **Profile likelihood** in Nonlinear regression supportano ora, oltre ai fit non pesati, le SD relative inserite, **1/abs(Y)**, **1/Y²**, **1/abs(Yfit)** e **1/Yfit²**.

- Le scale di ogni osservazione vengono conservate direttamente dal fit confermato, anche quando un residuo è zero.
- Nei profili non vengono ricalcolati i pesi o ripetuta l'IRLS. Con IRLS l'inferenza resta condizionata ai pesi finali congelati; l'incertezza dei pesi non viene propagata.
- Il foglio degli stati identifica Weighting e Inference. Scale mancanti o non valide producono limiti non disponibili con motivo, conservando la stima e senza sostituirli con intervalli non pesati.
- Dati e SD vengono controllati nel dialogo senza avviare fit sul thread dell'interfaccia. Gli errori correggibili restano sul campo; il calcolo dei profili rimane annullabile.

Le ricette Wald al 95% conservano i risultati precedenti. Le nuove ricette con profili pesati richiedono la 0.75 per essere ricalcolate. Il profilo è locale e l'inferenza non lineare approssimata; rimangono i limiti di ricerca documentati. La beta non costituisce validazione clinica o certificazione regolatoria.

[Guida con schermate Windows](nonlinear-parameter-intervals.md) · [Verifiche](validation-075.md) · [Funzionalità](features.md)
