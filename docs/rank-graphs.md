# Grafici dei ranghi e delle differenze appaiate

Mann–Whitney e Wilcoxon per ranghi con segno offrono nella scheda **Opzioni** del dialogo di analisi i grafici dedicati ai ranghi e alle differenze appaiate, disattivati in modo predefinito.

## Opzioni disponibili

| Analisi | Opzione (predefinita off) | Contenuto del grafico |
|---|---|---|
| **Mann–Whitney** | `Grafico dei ranghi` (*Plot ranks*) | Rango medio di ogni osservazione completa, raggruppato per campione, con dispersione laterale dei pareggi e linea della mediana dei ranghi. |
| **Wilcoxon per ranghi con segno** | `Grafico dei ranghi` (*Plot ranks*) | Ranghi con segno (`+/− Rango assoluto`) delle coppie complete. Con criterio **Pratt**, gli zeri contribuiscono al ranking e sono disegnati come cerchi vuoti distinti dalle coppie non nulle; con **Scarta**, gli zeri sono omessi dai ranghi con segno. |
| **Wilcoxon per ranghi con segno** | `Grafico delle differenze appaiate` (*Plot paired differences*) | Differenze appaiate nella direzione **Primo − Secondo**, inclusi eventuali zeri validi. |

Quando nel test di Wilcoxon sono attive **entrambe** le opzioni, la figura impagina due sotto-grafici affiancati (`1 × 2`): ranghi con segno a sinistra e differenze appaiate a destra.

## Fedeltà ai dati e ricette storiche

* **Stessa tabella dell'inferenza**: i grafici leggono direttamente la tabella `Ranks` prodotta dal test di inferenza. P-value, statistiche e tabelle esistenti non cambiano attivando o disattivando i grafici.
* **Identità delle righe**: le posizioni di coppia e di punto restano ancorate alle righe sorgente validate nel foglio di lavoro (`table_contexts['Ranks']['positions']`), anche in presenza di celle mancanti o escluse.
* **Ricette storiche**: le analisi create prima delle opzioni *Valore p* conservano **Metodo storico (test originale)** nella finestra parametri. Attivare un grafico lasciando il metodo storico mantiene p-value, statistiche e tabelle originali; passare a *Automatico* / *Esatto* / *Normale* richiede conferma esplicita prima del ricalcolo.
* **Dataset molto grandi**: oltre `5.000` punti, il disegno applica una riduzione deterministica solo visiva e dichiara il conteggio mostrato nella didascalia della figura, mentre inferenza e foglio `Ranks` continuano a usare tutte le righe.
* **Navigatore, Galleria ed export**: i grafici sono navigabili anche prima del calcolo (dopo riapertura di un file `.alab`), visibili in Galleria ed esportabili in **PNG**, **SVG** e **PDF** (anche con etichette letterali contenenti `$`, renderizzate con `parse_math=False`).
