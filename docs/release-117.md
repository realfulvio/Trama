# Trama 0.117.0 beta

- **Equazioni personalizzate.** Nel fit singolo o globale puoi legare un coefficiente a un altro con un fattore e uno scostamento. Per esempio, con `C = 2*A + 1` il fit stima A e ricava C. Nei fit globali puoi impostare un valore iniziale diverso per ogni serie. [Guida ai coefficienti collegati](coefficient-links.md)
- **Confronti di sopravvivenza.** In Kaplan–Meier puoi confrontare le curve con Tarone–Ware e Fleming–Harrington e leggere i pesi applicati ai tempi di evento. [Guida ai confronti pesati](weighted-logrank.md)
- **Salvataggio.** Salvando mentre scrivi in una cella viene conservato il valore appena digitato. I collegamenti ai file dati si conservano anche spostando insieme la cartella del progetto e le sue sorgenti.
- **Importazione PZF.** Trama legge altre tabelle con etichette formattate o lettere greche e conserva le osservazioni escluse anche nelle serie numeriche a precisione singola.

## English

- **Custom equations.** In single and global fits you can link one coefficient to another using a multiplier and an offset. With `C = 2*A + 1`, for example, the fit estimates A and derives C. Global fits support a separate starting value for each series. [Linked coefficient guide](coefficient-links.md)
- **Survival comparisons.** Kaplan–Meier supports Tarone–Ware and Fleming–Harrington comparisons and can display the weights at each event time. [Weighted comparison guide](weighted-logrank.md)
- **Saving.** Saving a project while editing a cell retains the value you just typed. Data file links survive moving the project folder together with its sources.
- **PZF import.** More source tables with formatted labels or Greek letters can be read. Excluded observations are also preserved in single-precision numeric series.
