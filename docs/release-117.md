# Trama 0.117.0 beta

- **Grafici a bolle.** Dimensione, colore e simbolo possono dipendere da colonne diverse. Con una finestra stretta, l’area del grafico scorre e lascia spazio alle legende e alla scala colore.
- **Barre e intervalli.** Nei grafici raggruppati puoi combinare serie affiancate, sovrapposte e impilate. Imposti la spaziatura, l’aspetto di una serie o di una singola barra, la direzione e lo stile degli intervalli, e un asse destro lineare o logaritmico.
- **Excel collegato.** Puoi collegare un foglio di lavoro per nome in un file XLSX. L’anteprima di aggiornamento permette di verificare le modifiche e risolvere i conflitti riga per riga. [Guida al collegamento Excel](source-link-xlsx.md)
- **Layout.** Puoi aggiungere, sostituire, ritagliare, ruotare e raggruppare pannelli. I grafici collegati mantengono il riferimento al progetto d’origine. Righelli, griglia e guide aiutano la disposizione.
- **Fogli e navigazione.** Modifica i titoli e le repliche dei fogli XY. Con F6 passi tra i riquadri e con Ctrl+1–9 scegli una tabella dei risultati. I fogli collegati sono ricercabili dalla barra inferiore.
- **Modelli misti.** La struttura AR(1) è disponibile per visite ordinate con un fattore entro i soggetti. Le visite mancanti conservano la distanza nell’ordine confermato.
- **Equazioni personalizzate.** Nel fit singolo o globale puoi legare un coefficiente a un altro con un fattore e uno scostamento. Per esempio, con `C = 2*A + 1` il fit stima A e ricava C. Nei fit globali puoi impostare un valore iniziale diverso per ogni serie. [Guida ai coefficienti collegati](coefficient-links.md)
- **Confronti di sopravvivenza.** In Kaplan–Meier puoi confrontare le curve con Tarone–Ware e Fleming–Harrington e leggere i pesi applicati ai tempi di evento. [Guida ai confronti pesati](weighted-logrank.md)
- **Salvataggio.** Salvando mentre scrivi in una cella viene conservato il valore appena digitato. I collegamenti ai file dati si conservano anche spostando insieme la cartella del progetto e le sue sorgenti.
- **Importazione PZF.** Trama legge altre tabelle con etichette formattate o lettere greche e conserva le osservazioni escluse anche nelle serie numeriche a precisione singola.

## English

- **Bubble charts.** Size, color and symbol can come from different columns. In a narrow window, the chart scrolls and keeps space for its legends and color scale.
- **Bars and intervals.** Grouped charts can combine adjacent, overlaid and stacked series. Set spacing, the appearance of a series or a single bar, interval direction and appearance, and a linear or logarithmic right axis.
- **Linked Excel data.** Link a worksheet by name in an XLSX workbook. Preview updates and resolve conflicts row by row. [Linked Excel guide](source-link-xlsx.md)
- **Layouts.** Add, replace, crop, rotate and group panels. Linked graphs retain a reference to their source project. Rulers, grids and guides help position panels.
- **Worksheets and navigation.** Edit XY worksheet titles and replicates. Use F6 to move between panes and Ctrl+1–9 to select a result table. Search linked sheets from the status bar.
- **Mixed models.** An AR(1) structure is available for ordered visits with one within-subject factor. Missing visits retain their distance in the confirmed order.
- **Custom equations.** In single and global fits you can link one coefficient to another using a multiplier and an offset. With `C = 2*A + 1`, for example, the fit estimates A and derives C. Global fits support a separate starting value for each series. [Linked coefficient guide](coefficient-links.md)
- **Survival comparisons.** Kaplan–Meier supports Tarone–Ware and Fleming–Harrington comparisons and can display the weights at each event time. [Weighted comparison guide](weighted-logrank.md)
- **Saving.** Saving a project while editing a cell retains the value you just typed. Data file links survive moving the project folder together with its sources.
- **PZF import.** More source tables with formatted labels or Greek letters can be read. Excluded observations are also preserved in single-precision numeric series.
