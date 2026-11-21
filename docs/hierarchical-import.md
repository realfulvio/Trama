# Editable clustering imports

Supported hierarchical analyses in `.prism` and `.prismt` ZIP projects can reopen as native **Hierarchical clustering** analyses. They remain connected to their imported source worksheet.

The converter restores row, column or combined clustering, supported column and row transforms, cluster counts or an uncut tree, and observation labels using the saved column identifiers. Supported saved transforms are None, Center and Standardize; complete and group-average linkage with Euclidean distance are recognized. Standardization uses the sample standard deviation; columns are transformed before rows.

Selected scaled-data, distance-matrix, merge map and cophenetic reports are restored, including full or lower-triangle matrix display. When a saved heat map is the only supported graph selection, the native result contains the heat map with its row and column trees. When a saved dendrogram is also selected, it remains the primary native figure. Compatible saved heat maps, individual dendrograms and elbow plots can reopen as separate graphs linked to that same calculation.

The editable dendrogram and heat map can restore an opaque single branch color, stroke width and style, tree visibility and supported linear distance-axis limits, direction and spacing. An opaque per-cluster line palette can also be mapped to native group order when the saved count cut covers every observation without duplicates. The heat map can restore the Viridis palette and the visibility of the color bar. Each figure has its own formatting. Open **Format Graph** or the **Inspector** to edit the settings.

Enable **Output → Merge map** to see one table per clustering direction with the one-based merge order, two child labels and the cophenetic distance at which they join. A child displayed as **Cluster 3** refers to the third merge in that report. Children are ordered by the last source observation in each child. The numeric **Merges** sheet and the dendrogram retain their existing ordering. The optional report recalculates with the analysis, so equal distances can produce a different merge sequence in a recomputed tree.

Enable **Output → Elbow data** to report within-cluster sums of squares (WCSS) for each cut from one cluster to one fewer than the number of observations. WCSS uses squared deviations from cluster centers on the same scaled data and merge sequence as the fitted tree. Select **Graph output → Elbow plot** to show those values, with separate panels for row and column clustering. The importer links a saved elbow graph when both its graph identifier and its source dataset match the saved result.

## Working with an imported analysis

1. Open the imported analysis or graph in the project navigator.
2. Use **Change parameters** to edit clustering direction, transforms, cuts or output options.
3. Edit or exclude a source cell. The native result recalculates from the current complete observations.
4. Save the project as `.alab` to retain the editable recipe, native graph style and exclusions.

Saved result snapshots remain independent of the native calculation and keep their original values. They can be useful for reviewing the imported project after source edits.

To add another view, select **Merges** (or **Row Merges** or **Column Merges** when clustering both directions) and choose **Analyze this result… → Hierarchy graph**. Choose the figure and, for a dendrogram or elbow plot, the axis. The graph uses the fitted tree, then updates when the worksheet or clustering parameters change. If a change removes its input result sheet, use **Change input result…** to choose the current Merges sheet.

## Limits

The native figure uses Trama's graph presentation. Complex palette settings, exact label positions and drawing objects are outside the supported settings above. The importer reports unavailable saved views. Additional saved cut methods, linkages or distances that the converter does not recognize stay as saved content where available.

These additions concern supported hierarchical analysis metadata in ZIP project files. They do not add general binary-project recipe restoration or external-format save support.

## Native Windows preview

![Editable imported heat map and both clustering trees in Trama, using a synthetic project.](media/hierarchical-import/modern-windows.png)

Unedited capture of the Windows 0.80 beta portable, optional Modern theme, 96 DPI. Source data are synthetic. The native graph uses Trama styling; the saved result snapshot is retained separately. Accepted application source: `74a5d75dff56bde4f2088afa6064033678db8e9e`.

### Verifica su Windows delle scale dei dendrogrammi

Nel progetto GeneExpression la scala delle righe ha sei tacche, da 0 a 10 a passi di 2. Quella delle colonne ne ha cinque, da 0 a 20 a passi di 5. Nel progetto Cities le sei tacche delle righe vanno da 0 a 2,5 a passi di 0,5. Le posizioni e i numeri esportati in SVG sono stati confrontati con i valori salvati in entrambi i progetti, sia all'importazione sia dopo la riapertura del file Trama.

Nel dendrogramma autonomo di Cities il titolo della distanza è nascosto. L'editor permette di mostrarlo in anteprima, annullare o applicare la modifica conservando tutte e sei le tacche. Nella mappa dello stesso progetto i numeri della scala laterale ruotano quando lo spazio si riduce. Su Windows lo spazio minimo misurato tra due numeri vicini è di 1,06 pixel nella finestra da 1000 × 700 e di 14,42 pixel in quella da 1500 × 900.

Le etichette delle categorie mantengono il carattere, la dimensione, il colore, il grassetto, la rotazione e la cadenza riconosciuti nel progetto. GeneExpression mantiene le otto intestazioni verticali a 11 punti; Cities mantiene le due intestazioni di colonna in grassetto anche se il clustering riguarda solo le righe. Nella finestra compatta l’anteprima di Cities mostra nove nomi distanziati, con tutte le 43 posizioni di riga. Allargando la finestra a 1500 × 900 compaiono quindici nomi. Lo zoom permette di leggere un tratto più piccolo. Con un intervallo fisso, l’esportazione conserva le etichette selezionate: scegliere un’altezza sufficiente per leggerle tutte.

[Vista Qt a 1000 × 700](media/hierarchical-distance/windows-1000.png) · [Vista Qt a 1500 × 900](media/hierarchical-distance/windows-1500.png)

Le barre dei colori riportano «Table values» e «Log₂(Fold Change)» sopra la scala, con i valori in Arial 12. I titoli, il pedice e i valori si conservano dopo la riapertura in Trama e nell’SVG. I limiti automatici seguono i dati ricalcolati. Nel dendrogramma delle colonne di GeneExpression, le cinque tacche rimangono alle distanze 0, 5, 10, 15 e 20. La finestra da 1000 × 700 mostra i due estremi per lasciare spazio alle scritte. A 1500 × 900 si leggono tutti e cinque i numeri. [GeneExpression in Vetro su Windows a 1000 × 700](media/hierarchical-distance/windows-gene-1000.png)

Nel dendrogramma autonomo di Cities ogni nome rimane associato alla propria foglia. Tutti e 43 i nomi si esportano in Arial 11, neri e ruotati di 90°. La legenda riprende i cinque gruppi nell’ordine salvato. Ogni simbolo usa il colore dei rami assegnati al suo gruppo. Modificando la palette dall’editor gerarchico, la legenda si aggiorna con i rami. **Formato legenda** permette di cambiare titolo, voci e ordine.

Su Windows a 1000 × 700 l’anteprima mostra 22 nomi distanziati. A 1500 × 900 mostra tutti e 43. Il collaudo ha confrontato i 42 rami, le cinque voci della legenda e i 43 nomi nell’originale e dopo salvataggio e riapertura in Trama.

[Albero di Cities a 1000 × 700](media/hierarchical-distance/windows-cities-tree-1000.png) · [Albero di Cities a 1500 × 900](media/hierarchical-distance/windows-cities-tree-1500.png)
