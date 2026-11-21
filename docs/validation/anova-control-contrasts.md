# ANOVA multifattoriale e confronti con un controllo

Tre progetti di esempio coprono 16 termini di tipo III con 36, 48 e 144 osservazioni. Aprendo i progetti e ricalcolando dai dati, 167 confronti numerici con i risultati archiviati rientrano in una tolleranza relativa di 10⁻¹⁰. Il conteggio include somme e medie dei quadrati, gradi di libertà, F, p, dimensioni dell’effetto, residui e, per due confronti di Dunnett, differenze, errori standard e valori assoluti di t.

Nel progetto con 48 osservazioni, le due condizioni sperimentali sono confrontate con lo stesso controllo. I p corretti e gli estremi degli intervalli simultanei al 95% sono verificati separatamente.

| Confronto | p corretto archiviato | p corretto ricalcolato |
|---|---:|---:|
| Controllo e tipo A | 3,84486265 × 10⁻⁹ | 3,84486663 × 10⁻⁹ |
| Controllo e tipo B | < 10⁻¹⁵ | 4,09908502 × 10⁻¹⁶ |

Lo scarto massimo degli estremi degli intervalli rispetto al progetto è 0,000080 nelle unità della risposta. Con due confronti, Trama integra direttamente la probabilità di coda della t bivariata. I test confrontano questo calcolo con un secondo integrale ottenuto condizionando su una componente. Coprono correlazioni positive, negative e nulle, direzioni opposte, probabilità piccole e il valore critico simultaneo.

Il commit di codice `ae0cffa` ha superato le stesse 57 prove mirate su Linux e Windows. Su ciascun sistema sono stati aperti e ricalcolati i tre progetti. Questo confronto riguarda il motore eseguito dai sorgenti.
