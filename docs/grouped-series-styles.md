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

## Regole di compatibilità e persistenza

- Supporta sia **Affiancati** (*Interleaved*) sia **Sovrapposti** (*Superimposed*), sia con **Repliche grezze** (*Raw replicates*) sia con **Riepiloghi precalcolati** (*Precomputed summaries*).
- Con **Impilati** (*Stacked*) e **Impilati al 100%** (*100% stacked*), oppure quando lo stile globale è **Osservazioni individuali** (*Individual points*) o **Intervalli flottanti** (*Floating range*), il selettore **Disegno** viene disabilitato con una nota esplicativa nella stessa scheda. Se nei parametri dell’analisi sposti il grafico verso una modalità incompatibile mentre esistono override per serie, Trama chiede conferma per ripristinare tutte le serie su **Come il grafico**.
- Ogni serie mantiene una **sola voce di legenda**, i propri colori, visibilità, etichetta (inclusi caratteri letterali come `$`) e formattazione anche riordinando le colonne selezionate, modificando i parametri compatibili e riaprendo il file `.alab`.
- I progetti con disegni o formati specifici dei grafici raggruppati usano il formato ALAB 16. Le versioni precedenti dell’app che non lo supportano chiedono di aggiornare. L’esempio preparato prima di questa modifica si apre e viene aggiornato al salvataggio.
- I grafici e i layout conservano il disegno misto nell’export. SVG e PDF mantengono le serie vettoriali.

---

## English

In **Grouped graph** plots, you can assign a dedicated drawing mode to individual series from **Format Graph → Series**, while keeping the global **Graph style** as the inherited default.

1. Open **Format Graph → Series**, pick an item in **Element**, and set **Drawing**: **As graph**, **Bars**, **Center and interval**, or **Line and symbols**.
2. Use **Preview** to inspect edits immediately, **Apply** to commit, or **Cancel** (`Esc`) to discard. Every change supports **Undo** (`Ctrl+Z`) and **Redo** (`Ctrl+Y`), preserves one legend entry per series, keeps exact interleaved X positions, breaks lines cleanly at missing category estimates without shifting other categories, renders isolated markers and intervals, and persists across `.alab` save/reopen, Layout composition, and vector **PDF/SVG** export.
3. With **Stacked** / **100% stacked** placements or **Individual points** / **Floating range** global styles, **Drawing** is disabled with an inline explanation, and switching an analysis with overrides to an incompatible placement prompts before resetting series overrides to **As graph**.

Esempio riapribile: [Grafico-raggruppato-stili-serie.alab](examples/Grafico-raggruppato-stili-serie.alab)
