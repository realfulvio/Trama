# Disegnare e modificare forme sul grafico Qt · Drawing and editing shapes on the Qt graph

Pacchetto «Canvas Qt» della 0.95. Linee, frecce, rettangoli ed ellissi si disegnano e si modificano direttamente sul
grafico, con lo stesso modello e lo stesso formato `.alab` dell'editor numerico (Grafico → Forme del grafico…).

## Per l'utente

**Dove.** Scheda *Grafico* → **Disegna** (menu con gli strumenti, Taglia/Copia/Incolla e Termina disegno), oppure i cinque
pulsanti a destra della barra del grafico: Seleziona/sposta, Linea, Freccia, Rettangolo, Ellisse.

| Gesto | Effetto |
| --- | --- |
| Trascina nel grafico con uno strumento di disegno | Crea la forma; poi torna a *Seleziona* (con **Maiusc** lo strumento resta) |
| **Ctrl** mentre si disegna un rettangolo o un'ellisse | Quadrato / cerchio |
| Clic su una forma (di un rettangolo senza riempimento: sul contorno) | La seleziona, con le maniglie agli estremi |
| Trascina una forma | La sposta; **Ctrl** blocca in orizzontale, **Maiusc** in verticale |
| Trascina una maniglia | Ridimensiona (l'altro estremo non si muove) |
| Frecce / Ctrl+frecce | Sposta di 1 px / 10 px |
| Canc | Elimina la forma selezionata |
| Doppio clic o Invio | Apre l'editor numerico della forma |
| Tasto destro | Menu: formato, colore, spessore, stile, frecce, motivo, duplica, ordine, appunti |
| Ctrl+C / Ctrl+X / Ctrl+V | Copia, taglia, incolla una forma (l'incolla crea una forma nuova) |
| **Esc** | Annulla il trascinamento; un secondo Esc esce dagli strumenti |
| Ctrl+Z / Ctrl+Y | Annulla / ripeti **le forme di questo grafico** (un trascinamento = un passo) |

Annulla/Ripeti agisce sul grafico finché ha passi di disegno o uno strumento è acceso; sulla griglia e sugli altri
grafici la cronologia resta la loro. Le maniglie sono solo a schermo: non finiscono in PNG, SVG, PDF, layout né nel
file `.alab`. Salvare, esportare, ricalcolare o cambiare foglio durante un trascinamento chiude l'anteprima.

**Quando non è disponibile** (il motivo compare nella nota della pagina e nel suggerimento dello strumento): grafici
importati da formati esterni, layout, grafici con assi interrotti, grafici a più pannelli o con un secondo asse. L'editor
numerico *Forme del grafico…* resta disponibile dove prima. Le forme in unità dati seguono gli assi, compresi
logaritmici e invertiti; un trascinamento fuori dal dominio viene rifiutato e lascia intatto il modello.

**English.** Graph tab → **Draw**, or the five tool buttons beside the graph toolbar. Drag to draw (Ctrl: square or
circle; Shift keeps the tool), click to select, drag to move or resize from a handle, arrows nudge 1 px (Ctrl: 10 px),
Delete removes, double-click or Enter opens the numeric editor, right-click offers the formatting menu, Ctrl+C/X/V
copy, cut and paste (a paste is a new shape), Esc cancels a drag and a second Esc leaves the tools, Ctrl+Z/Ctrl+Y act
on the shapes of the graph. Handles never reach exports or saved files. Imported, layout, broken-axis, multi-panel and
twin-axis graphs show why the tools are off.

## Per chi sviluppa

- **Controller condiviso e senza Tk:** `analisi/shape_interaction.py` (`ShapeController`, `ShapeHistory`,
  `render_shapes`, `event_key`). `analisi/shape_canvas.py` resta l'adattatore Tk (`ShapeCanvas`: tasti, focus-out,
  grab) e riesporta i nomi, quindi `tramastat.py` e i test classici non cambiano. `analisi/shape_context.py` importa
  Tk solo dentro `build_menu`; `edit_records` è usato anche da Qt.
- **Qt:** `trama_qt/shape_canvas.py`: `QtShapeCanvas` (filtro tasti del canvas, `ShortcutOverride` per Esc/Canc/frecce/
  Ctrl+C·X·V quando uno strumento è acceso) e `GraphDrawing` (azioni `draw_*`, `shape_*`, commit, cronologia, appunti,
  menu, editor). Aggancio in `window.py`: `self.drawing`, `_canvas` → `drawing.attach`, `show_sheet`/`show_home` →
  `drawing.detach`, `undo` → cronologia della forma, `settle_graph_draft` e `_start` → `drawing.cancel`.
- **Un solo percorso di commit:** ogni modifica confermata passa da `MainWindow.commit_style` →
  `Project.commit_style(run, style)`, che registra il passo in `Run.shape_history` (per grafico, mai condivisa con la
  griglia). `apply_format` registra anche le modifiche fatte dall'editor numerico; Annulla/Ripeti non registra di nuovo
  (`record_shapes=False`).
- **Identificatori per il verificatore esterno:** `window.actions["draw_select"]`, `["draw_line"]`, `["draw_arrow"]`,
  `["draw_rectangle"]`, `["draw_ellipse"]`.
- **Prove:** `tests/test_shape_interaction.py` (controller: DPI, log, asse invertito, linee sovrapposte, modificatori,
  asse gemello), `tests/test_qt_canvas.py` (finestra Qt con eventi `QTest` reali sulla fixture sintetica
  `tests/data/qt_canvas/grafico.alab`), smoke `trama_qt/canvas_smoke.py` (chiamato da
  `python -m trama_qt --smoke CARTELLA`: apri → disegna → modifica → copia/incolla → annulla/ripeti → salva → riapri →
  esporta PNG/SVG/PDF → asse interrotto, con screenshot chiaro/scuro).
- **Non coperto qui:** il puntatore del sistema operativo (QTest invia gli eventi al widget) e il DPI nativo di
  Windows; la scala 150% è emulata con `QT_SCALE_FACTOR=1.5`.
