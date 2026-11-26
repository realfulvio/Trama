# Trama 0.113.0 beta

- **Ordine delle righe.** Inverti l’intero foglio da **Modifica**. Dal menu delle intestazioni di riga puoi spostare la selezione in cima o in fondo. Formati ed esclusioni seguono le righe. Puoi annullare il cambio di ordine.
- **Ricalcoli collegati.** I lavori brevi iniziano subito. Se una richiesta dura più a lungo, Trama avvia in sottofondo i processi di calcolo. I processi già pronti ricevono il lavoro successivo.
- **Correlazioni e grafici.** Le matrici Pearson e Spearman riutilizzano i calcoli per colonna. I fogli grafico e layout disegnano alla dimensione effettiva della pagina.
- **Avvio.** La schermata con il logo appare mentre vengono caricate le librerie scientifiche. Il calcolo numerico usa un thread BLAS per processo. Le ultime cifre di alcuni risultati su tabelle grandi possono cambiare per effetto dell’arrotondamento.

Estrai lo ZIP e avvia **Trama.exe** su Windows a 64 bit.

## English

- **Row order.** Reverse the whole worksheet from **Edit**. Use the row header menu to move selected rows to the top or bottom. Formatting and exclusions follow their rows. Undo restores the previous order.
- **Linked recalculations.** Short calculations start immediately. Longer requests start worker processes in the background. Subsequent requests use the workers that are ready.
- **Correlations and graphs.** Pearson and Spearman matrices reuse calculations for each column. Graph and layout sheets render at their actual page size.
- **Startup.** The splash screen appears while the scientific libraries load. Numerical computations use one BLAS thread per process. Some results on large worksheets can differ in their last digits because of rounding.

Extract the ZIP and open **Trama.exe** on 64-bit Windows.
