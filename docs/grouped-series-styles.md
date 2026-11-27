# Stili di disegno per serie nei grafici raggruppati

Nei grafici raggruppati (**Grouped graph**) puoi scegliere un tipo di disegno specifico per ciascuna serie direttamente da **Formato grafico** (*Format Graph*), mantenendo l’impostazione globale come valore predefinito ereditato.

## Come funziona in Classica Qt

1. Apri il pannello **Formato grafico** (barra degli strumenti o menu *Cambia → Formato grafico…*) e seleziona la scheda **Serie** (*Series*).
2. Scegli la serie dall’elenco **Elemento** (*Element*) e imposta **Disegno** (*Drawing*):
   - **Come il grafico** (*As graph*): eredita lo stile globale scelto nei parametri del grafico (**Barre** o **Centro e intervallo**).
   - **Barre** (*Bars*): disegna la serie come barre verticali con l’eventuale intervallo di errore.
   - **Centro e intervallo** (*Center and interval*): disegna solo il centro (simbolo) e l’intervallo.
   - **Linea e simboli** (*Line and symbols*): collega i centri della serie nell’esatta posizione orizzontale della serie (compreso lo scostamento in modalità *Affiancati*); le categorie prive di stima creano una lacuna che interrompe la linea senza spostare le altre categorie, mentre eventuali punti isolati restano disegnati con il proprio marcatore e intervallo.
3. Usa **Anteprima** (*Preview*) per aggiornare la vista in tempo reale senza confermare, **Applica** (*Apply*) per confermare o **Annulla** (*Cancel* / `Esc`) per scartare. Ogni conferma è reversibile con **Annulla** (`Ctrl+Z`) e **Ripeti** (`Ctrl+Y`).

## Disposizione mista

Nei grafici raggruppati affiancati e sovrapposti, **Disposizione** imposta la posizione rispetto alla serie precedente nell’elenco. La prima serie apre il gruppo. Scegli **Come il grafico**, **Affianca**, **Sovrapponi**, **Impila** o **Distanzia**. La distanza lascia un margine aggiuntivo tra le barre. Una pila può essere affiancata a una barra indipendente o a un’altra pila.

Le pile accettano barre, con somme positive e negative separate. Una stima mancante lascia vuoto il segmento senza spostare le altre serie. Gli intervalli delle singole serie si spostano con la base del segmento. I punti delle repliche restano visibili fuori dalle pile. Il foglio numerico conserva i valori e gli intervalli di origine. Anteprima, Applica e Annulla valgono anche per la disposizione. I progetti con disposizione personalizzata richiedono ALAB 17.

Nei parametri del grafico, **Direzione dell’intervallo → Solo superiore** mostra la parte dell’intervallo sopra la stima. Il foglio dei risultati conserva entrambi i limiti. Questa impostazione richiede ALAB 18. Nei progetti ZIP e PZF compatibili, Trama recupera dal foglio di origine le pile affiancate con medie e SEM superiore, oltre ai limiti e alle etichette dell’asse supportati. Il grafico usa la formattazione di Trama.

Con **Solo inferiore**, l’intervallo termina alla stima. In **Formato grafico → Serie** puoi ereditare la direzione del grafico o scegliere entrambi i lati, solo quello superiore o solo quello inferiore per la serie selezionata. Le scelte sono disponibili quando hai impostato un intervallo nei parametri. L’anteprima e le esportazioni mantengono le scelte. La direzione per serie e l’opzione globale **Solo inferiore** richiedono ALAB 21.

Con le distanze asimmetriche o i limiti inseriti a mano, puoi lasciare vuota una delle due celle per ciascuna stima. Il grafico mostra il segmento verso l’estremo disponibile. Nel foglio dei risultati l’altro limite resta vuoto.

Nella stessa scheda, **Colore dell’intervallo**, **Spessore dell’intervallo** e **Lunghezza dei cappucci** formattano solo l’intervallo della serie. Lascia un campo vuoto per mantenere l’aspetto predefinito. Imposta i cappucci a zero per mostrare solo il segmento. La formattazione indipendente richiede ALAB 23.

Nei grafici raggruppati verticali, **Formato grafico → Serie → Asse dei valori** può assegnare una serie all’asse destro indipendente. L’asse destro è lineare e condivide le categorie con quello sinistro. Imposta titolo e limiti nella scheda **Assi**, raggiungibile anche con un doppio clic sull’asse destro. Ogni pila usa un solo asse dei valori. Per usare un asse destro collegato con conversione, mantieni tutte le serie a sinistra. Un asse destro indipendente richiede ALAB 25.

**Cambia → Ordine di disegno delle serie…** sposta le serie nel grafico. Le barre affiancate vanno da sinistra a destra, quelle impilate dal basso verso l’alto. La disposizione relativa segue la serie e si applica alla nuova precedente. La prima serie apre sempre il gruppo. La legenda ha un ordine proprio. Puoi invertire l’elenco, ripristinare l’ordine del foglio e usare Annulla o Ripeti. Un ordine personalizzato richiede ALAB 19.

## Spaziatura delle barre

In **Formato grafico → Disposizione barre** attiva **Spaziatura personalizzata** per impostare la distanza tra barre adiacenti, lo spazio aggiuntivo tra gruppi e i margini prima e dopo le barre. Le misure sono percentuali della larghezza di una barra. **Spazio per valori mancanti** può riservare da zero alla larghezza intera di una barra. Una pila o un insieme di serie sovrapposte occupa una sola posizione. Uno zero osservato conta come valore.

L’anteprima mostra la geometria aggiornata. Il foglio numerico resta uguale. Per tornare alla disposizione automatica, disattiva **Spaziatura personalizzata**. L’impostazione segue il grafico nel layout e nell’esportazione. Il salvataggio con spaziatura personalizzata richiede ALAB 20.

Nella stessa scheda, scegli **Direzione delle barre → Orizzontale** per mettere i valori sull’asse X e le categorie sull’asse Y. I limiti, le etichette, le linee di riferimento e gli oggetti ancorati ai dati seguono gli assi. Le pile, la spaziatura e le opzioni degli intervalli restano disponibili. Il salvataggio con barre orizzontali richiede ALAB 22.

Nelle disposizioni senza pile, **Base delle barre** imposta il valore da cui partono le barre. Le stime e gli intervalli si leggono ancora nelle unità del foglio. Il campo vuoto usa zero. Una base personalizzata richiede ALAB 24.

## Formato di una singola barra

Fai clic destro su una barra oppure apri **Cambia → Formato singola barra…**. L’elenco indica la riga del foglio, la categoria e la serie. Puoi cambiare riempimento, bordo, spessore e motivo anche per un segmento impilato. I campi vuoti seguono la serie. **Ripristina barra** rimuove le modifiche della barra selezionata.

**Anteprima** mostra le modifiche prima di salvarle. **Applica** le registra in un solo passaggio che puoi annullare o ripetere. Il formato segue la riga quando la sposti, rimane in attesa se la barra scompare e si vede anche nei layout e nelle esportazioni. Le stime, gli intervalli e la legenda della serie restano uguali. Il salvataggio con formati individuali richiede ALAB 27.

## Regole di compatibilità e persistenza

- Supporta sia **Affiancati** (*Interleaved*) sia **Sovrapposti** (*Superimposed*), sia con **Repliche grezze** (*Raw replicates*) sia con **Riepiloghi precalcolati** (*Precomputed summaries*).
- Con la disposizione globale **Impilati** (*Stacked*) o **Impilati al 100%** (*100% stacked*), oppure quando lo stile globale è **Osservazioni individuali** (*Individual points*) o **Intervalli flottanti** (*Floating range*), il selettore **Disegno** viene disabilitato con una nota esplicativa nella stessa scheda. Se nei parametri dell’analisi sposti il grafico verso una modalità incompatibile mentre esistono override per serie, Trama chiede conferma per ripristinare tutte le serie su **Come il grafico**.
- Ogni serie mantiene una **sola voce di legenda**, i propri colori, visibilità, etichetta (inclusi caratteri letterali come `$`) e formattazione anche riordinando le colonne selezionate, modificando i parametri compatibili e riaprendo il file `.alab`.
- I progetti con disegni specifici dei grafici raggruppati e disposizione globale usano ALAB 16. Le versioni precedenti dell’app che non lo supportano chiedono di aggiornare. L’esempio preparato prima di questa modifica si apre e viene aggiornato al salvataggio.
- I grafici e i layout conservano il disegno misto nell’export. SVG e PDF mantengono le serie vettoriali.

---

## English

In **Grouped graph** plots, you can assign a dedicated drawing mode to individual series from **Format Graph → Series**, while keeping the global **Graph style** as the inherited default.

1. Open **Format Graph → Series**, pick an item in **Element**, and set **Drawing**: **As graph**, **Bars**, **Center and interval**, or **Line and symbols**.
2. Use **Preview** to inspect edits immediately, **Apply** to commit, or **Cancel** (`Esc`) to discard. Every change supports **Undo** (`Ctrl+Z`) and **Redo** (`Ctrl+Y`), preserves one legend entry per series, keeps exact interleaved X positions, breaks lines cleanly at missing category estimates without shifting other categories, renders isolated markers and intervals, and persists across `.alab` save/reopen, Layout composition, and vector **PDF/SVG** export.
3. With **Stacked** / **100% stacked** placements or **Individual points** / **Floating range** global styles, **Drawing** is disabled with an inline explanation, and switching an analysis with overrides to an incompatible placement prompts before resetting series overrides to **As graph**.

Esempio riapribile: [Grafico-raggruppato-stili-serie.alab](examples/Grafico-raggruppato-stili-serie.alab)

With an interleaved or superimposed grouped graph, **Placement** controls the relation to the previous series. You can inherit the graph setting, use a separate slot, add extra spacing, overlay an independent bar, or stack the series. Stacks use bars and separate positive and negative sums. Individual intervals are translated with their bar segments. A missing value leaves its segment empty. Placement edits preserve the numeric table and are saved as ALAB 17.

In the graph parameters, **Interval direction → Upper only** draws the portion above the estimate and keeps both limits in the results. This setting requires ALAB 18. For supported ZIP and PZF projects, Trama restores side-by-side stacks with means and upper SEM from the original worksheet, together with supported axis settings. The graph uses Trama’s formatting.

**Lower only** draws the portion below the estimate. In **Format Graph → Series**, each series can inherit the graph direction or use both sides, the upper side or the lower side. Set an interval type in the graph parameters to enable the selector. The choices appear in the preview and in exports. Per-series overrides and the global **Lower only** option require ALAB 21.

With asymmetric distances or entered limits, leave one endpoint cell empty to draw from the estimate toward the available endpoint. The missing endpoint stays empty in the result table.

Use **Interval color**, **Interval thickness** and **Cap length** to format the selected interval. Leave a field empty to keep its default. Set the cap length to zero to show just the segment. Independent interval formatting requires ALAB 23.

On a vertical grouped graph, use **Format Graph → Series → Value axis** to assign a series to an independent right axis. Both sides share categories. Set the title, scale and limits in **Axes**, or double-click the right axis to reach them. A stack uses one value axis and needs a linear scale. On the right logarithmic axis, estimates, intervals drawn and individual points must be positive. Bars start at 1 by default on this axis, or at the positive starting value set in **Bar arrangement**. The Results sheet retains the original estimates and interval limits. Keep the series on the left when using a linked right axis with unit conversion. Independent right axes require ALAB 25, or ALAB 26 with a logarithmic scale.

Use **Change → Series drawing order…** to arrange the plotted series. Side-by-side bars run left to right and stacks run bottom to top. Each relative placement follows its series and refers to the series that now comes before it. The first series always starts a group. The legend has its own order. You can reverse the list, restore worksheet order, and undo or redo edits. A custom order requires ALAB 19.

Use **Format Graph → Bar arrangement → Custom spacing** to set distances between adjacent bars, extra group spacing and the leading and trailing margins. Measurements are percentages of a bar’s width. **Space for missing values** can reserve between zero and one bar width. A stack or overlay shares one position, and an observed zero counts as data. The preview shows the adjusted graph. Custom spacing leaves the result table unchanged, follows the graph into layouts and export, and requires ALAB 20.

On the same tab, choose **Bar direction → Horizontal** to put the values on X and the categories on Y. Limits, labels, reference lines and data-anchored objects follow the axes. Stacks, spacing and interval options remain available. Horizontal bars require ALAB 22.

For charts without stacks, **Bar baseline** sets where the bars start. The estimates and intervals stay in the worksheet’s units. Leave the field empty to start at zero. A custom baseline requires ALAB 24.

### Format an individual bar

Right-click a bar or choose **Change → Format individual bar…**. Choose a bar by its worksheet row, category and series. Customize the fill, border, border width and fill pattern, including for a single segment in a stack. Empty fields inherit the series appearance. **Reset bar** removes the selected bar’s changes.

**Preview** shows what will change. **Apply** saves the edits as one step you can undo or redo. Formatting follows the worksheet row when you move it, is suspended if the bar disappears, and appears in layouts and exports. The estimates, intervals and series legend keep their original values and appearance. Individual bar formats require ALAB 27.
