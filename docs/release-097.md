# Trama 0.97.0 beta

## Novità

- **Interfaccia Vetro.** Il tema chiaro è predefinito. Tornano le schede Inserisci, Disponi, Famiglia e Strumenti. Il menu Tutti i comandi resta accessibile a finestra stretta. La finestra iniziale consente di scegliere il tipo di tabella, con anteprima e dati di esempio. Il navigatore cerca i fogli per nome. La barra inferiore permette di selezionarli e ripercorrere la cronologia. Quando si apre un grafico, Vetro mostra la scheda Grafico. La barra sopra il disegno raccoglie gli strumenti di navigazione e disegno. **File → Apri nell’interfaccia Classica** apre l’interfaccia alternativa.
- **Progetti e dati.** Modelli di analisi riutilizzabili con mappatura delle colonne, copie di recupero Qt, unione di fogli per chiave e importazione ed esportazione di cartelle Excel. I report riproducibili includono HTML consultabile offline, tabelle CSV e figure SVG.
- **Serie XY miste.** Gradini e barre affiancate si combinano con punti e linee. Formato grafico gestisce il tipo di disegno, l’asse e la larghezza dei gruppi di barre. L’Ispettore mostra le opzioni applicabili alla serie selezionata.
- **Analisi.** Silhouette dei cluster, proporzioni appaiate, potenza e numerosità da medie e deviazioni standard, intervalli di tolleranza, diagnostica Cox, Weibull AFT, logistica ordinale, sopravvivenza media ristretta (RMST), kappa di Cohen e test di permutazione per la differenza tra medie.
- **Compatibilità dei progetti.** Il ricalcolo delle ricette di selezione supportate legge intervalli di righe, confronti fra colonne e filtri di presenza. Le ricette delle permutazioni appaiate conservano l’ordine riproducibile delle repliche anche con il multicore.

Per Windows x64, estrai `Trama-0.97.0-Windows-x64.zip` e avvia `Trama.exe`. La beta usa Qt e include una guida per le analisi nel percorso `docs`.

## English summary

This beta adds reusable analysis templates, project recovery, worksheet joins, Excel workbooks and reproducible offline reports. Mixed XY series can combine steps and grouped bars with points and lines. The light theme is now the default, and the Qt ribbon restores the Insert, Arrange, Family and Tools tabs. New Qt workflows cover cluster silhouette, paired proportions, study planning, tolerance intervals, Cox diagnostics, Weibull AFT, ordinal logistic regression, RMST, Cohen's kappa and mean permutation tests.
