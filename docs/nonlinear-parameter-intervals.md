# Intervalli dei parametri nei fit non lineari

In **Analyze → Nonlinear regression → Confidence intervals**, scegli il metodo degli intervalli e il livello di confidenza dei parametri. Queste opzioni sono distinte dal livello delle bande intorno alla curva.

- **Symmetric (Wald)** usa la covarianza e i gradi di libertà del fit confermato. Il livello predefinito del 95% conserva i risultati delle ricette precedenti.
- **Profile likelihood** ristima gli altri coefficienti per ogni valore provato del parametro di interesse. Può produrre limiti asimmetrici; non sostituisce le stime puntuali né modifica la curva stimata.

Per il profilo, Trama inverte il test extra-sum-of-squares con un parametro fissato: il limite soddisfa `SS_profile = SS_min × (1 + F(level; 1, df)/df)`, con `df = N − p`. La somma dei quadrati e i gradi di libertà si riferiscono allo stesso fit indipendente. È un intervallo marginale per ciascun coefficiente, non una regione simultanea per tutti i coefficienti.

## Risultati

Il foglio **Parameters** mantiene stima e SE e indica il livello nei nomi delle colonne dei limiti. Per il profilo e per livelli Wald diversi dal 95%, **Parameter CI status** aggiunge metodo, livello, gradi di libertà, stato e motivo di ciascun estremo.

- **Profile root**: un estremo numerico trovato dall'inversione del test.
- **Parameter bound**: l'insieme di confidenza raggiunge un vincolo del modello; quel valore non è una radice del test.
- **Unavailable**: il limite non è stato determinato, con motivo esplicito. Non viene sostituito con Wald né dichiarato infinito soltanto perché la ricerca non ha trovato una radice.

Cambiare i dati o escludere una cella ricalcola stime e intervalli. Metodo e livelli si salvano nel progetto `.alab` con valori canonici, indipendenti dalla lingua dell'interfaccia. Il calcolo del profilo avviene sul worker ed è annullabile: annullare una modifica conserva l'ultimo risultato completato.

## Limiti della beta

Il profilo richiede attualmente **Unweighted**: le opzioni di pesatura restano disponibili con gli intervalli Wald. Richiede gradi di libertà residui positivi, dispersione residua misurabile e incertezza finita e non nulla dei coefficienti.

La ricerca segue la soluzione locale attorno al fit confermato; non enumera tutte le eventuali soluzioni disgiunte di un modello non identificabile. Se durante la ricerca si trova un fit sensibilmente migliore, l'intervallo viene segnalato come non disponibile: occorre prima affinare il fit puntuale.

Per mantenere il lavoro limitato, sono supportate fino a 5.000 osservazioni complete e 8 parametri per fit. Tutti i gruppi e tutte le risposte della stessa richiesta condividono un budget di 20.000 valutazioni residue e 10 milioni di valori, con 32 espansioni per lato. Il raggiungimento di un limite di lavoro è riportato negli stati.

Le prove indipendenti confrontano il caso lineare con gli intervalli t OLS, il tasso di decadimento con un profilo a coefficienti lineari eliminati analiticamente e il punto medio di un 4PL con minimi quadrati separabili. Coprono anche gruppi, risposte multiple, cambi di unità, vincoli, annullamento e mancata convergenza. Questi controlli non rendono esatto un intervallo approssimato in ogni problema scientifico.

[Funzionalità](features.md) · [Compatibilità](compatibility.md)
