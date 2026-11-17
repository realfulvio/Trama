# Trama 0.72.0 beta

Build beta di sviluppo: funzionalità ancora incomplete e possibili errori.

La 0.72 aggiunge **Confronto tra gruppi → Test di equivalenza (TOST)** per un campione, dati appaiati, Student a varianza comune e Welch a varianze separate. L'utente dichiara i margini inferiore e superiore e il livello alfa. L'analisi restituisce la differenza, i due test unilaterali, l'intervallo, i dati utilizzati e un grafico collegato.

Il dialogo e i suoi errori sono disponibili in italiano e inglese. Ricette, salvataggio `.alab`, ricalcolo, Inspector, Formatta grafico, riutilizzo dei risultati ed export CSV/PNG/SVG/PDF sono supportati. Tabelle e testi della figura mantengono per ora l'inglese.

La revisione corregge perdita di piccole differenze su grandi valori di base, soppressione della variabilità rappresentabile, scale di varianza molto diverse e calcoli con alfa molto piccolo. Le figure con unità estreme usano un moltiplicatore di visualizzazione esplicito.

La base applicativa ha superato **1.870 test su Linux e 1.870 su Windows**, senza salti, oltre agli smoke completi e ai casi TOST a 1024×768 e 1920×1200 Windows reali. La build 0.72 cambia versione e materiali di rilascio rispetto al codice già collaudato; il controllo mirato del nuovo portabile è registrato nei metadati della release.

[Guida al TOST](equivalence-tost-071.md) · [Rapporto di integrazione](validation-tost-086.md) · [Funzionalità](features.md)

