# Formati e compatibilità

[Presentazione](../README.md) · [Guida rapida](getting-started.md)

## Formati nativi e tabellari

| Formato | Uso |
| --- | --- |
| `.alab` | Progetto Trama: dati, formule, esclusioni, ricette, stili, layout e fogli Info. |
| CSV / TSV | Importazione di tabelle e scambio di dati; export dei risultati in CSV. |
| XLSX | Importazione di fogli Excel. Le formule e tutte le funzionalità di una cartella Excel non vengono convertite in ricette Trama. |
| SVG / PDF | Export di figure e layout. I layout nativi preservano i componenti vettoriali supportati; le immagini raster restano raster. |
| PNG / TIFF | Export di figure raster, con opzioni di dimensione e risoluzione. |

## Progetti legacy PZFX, PZF e PZT

Trama legge strutture supportate di **PZFX**, progetti XML/ZIP compatibili e dei formati binari **PZF / PZT** verificati. L'estensione da sola non garantisce il recupero di ogni contenuto.

- **Dati:** recupero delle tabelle e dei metadati riconosciuti.
- **Analisi:** ripristino delle ricette supportate e conservazione di risultati archiviati dove riconosciuti. Un risultato archiviato non è una nuova analisi ricalcolabile. Nei progetti ZIP, le [ricette gerarchiche riconosciute](hierarchical-import.md) possono ripristinare clustering di righe e colonne, trasformazioni e report come analisi native modificabili. Le ricette PCA standardizzate compatibili recuperano analisi parallela, seme, rapporti e grafico dei punteggi con gruppi, anche da un risultato multivariabile archiviato. Il ricalcolo usa la presentazione e il generatore di Trama. Un'ANOVA multifattoriale ordinaria supportata riattiva le dimensioni dell'effetto e la soglia α quando il riepilogo salvato contiene i risultati completi per tutti i termini.
- **Grafici:** alcuni grafici verificati diventano modificabili; altri restano viste originali PDF/EMF. Colori, assi, annotazioni e geometria si conservano entro le capacità del singolo importatore. Nei grafici a dispersione multivariabili compatibili, Trama riapre le coordinate salvate con categorie, colori con opacità, dimensioni dei simboli e assi lineari. Il grafico si aggiorna quando modifichi le coordinate. Le viste con livelli aggiuntivi possono richiedere un importatore diverso.
- **Layout:** recupero di viste e pannelli nei sottotipi supportati. Non ogni pannello, oggetto o collegamento originale può essere convertito in elemento nativo.
- **Dati importati modificabili:** nei sottotipi previsti è possibile modificare i dati delle viste recuperate conservandone la presentazione supportata. Questo non estende automaticamente l'editabilità a tutti i documenti.

Il supporto dei formati legacy è limitato ai contenuti verificati. Non è previsto un export universale verso questi formati. Mantieni l'originale e confronta dati, impostazioni e figure prima di usare una conversione in un lavoro importante.

I dettagli per famiglia e i casi verificati sono nella [documentazione tecnica](coverage.md). L'importazione di file di terzi richiede che tu abbia il diritto di accedere e usare quei file; la licenza MIT di Trama non concede diritti su contenuti o programmi di terzi.

Trama è un progetto indipendente in fase beta. Le funzionalità di importazione sono in evoluzione: vedi le [note legali](legal.md).

