# Trama 0.94 beta

La 0.94 aggiunge confronti tra curve ROC di coorti indipendenti, medie aggiustate con ANCOVA e distribuzioni raggruppate. Le analisi e i grafici nativi restano collegati ai fogli sorgente.

- [ROC di coorti indipendenti](independent-roc-curves.md) con AUC totale o parziale, DeLong per l’area totale e bootstrap stratificato per l’area parziale.
- [ANCOVA](ancova-090.md) per un fattore e una covariata, con medie aggiustate, controllo delle pendenze e contrasti opzionali.
- [Distribuzioni raggruppate](grouped-distributions.md) con box plot o violini per categoria e serie. Ogni serie ha una posizione riservata anche quando una categoria è priva di osservazioni.

L’[importazione dei progetti compatibili](compatibility.md) recupera estremi inferiori e superiori indipendenti nelle barre d’errore XY, ricette per ANOVA ordinaria con dati raggruppati e opzioni di confronto per curve di Kaplan–Meier. [I grafici del clustering gerarchico](hierarchical-import.md) possono riaprire le viste collegate e usare i colori salvati nei casi supportati.
