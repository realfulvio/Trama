# Stili di figura (Qt)

**Grafico → Stili di figura…** (EN *Graph → Figure styles…*) salva l'aspetto di un grafico come stile con nome e lo
riusa su altri grafici e progetti. Il comando sta nella scheda Grafico subito dopo Format Graph ed è attivo sui
grafici che si possono formattare (`Project.graph_format_problem` è `None`).

## Cosa passa da un grafico all'altro

Uno stile contiene solo questi campi, con i valori canonici del motore (`analisi.presentation`):

| Campo | Valori | Dove si vede |
| --- | --- | --- |
| `accent` | colore Matplotlib (`"#0B7A73"`, nome, o lista RGB/RGBA `[0.04, 0.48, 0.45]`) | colore della prima serie (Format Graph → *Legacy first-series color*) |
| `font_family` | `sans-serif`, `serif`, `monospace` | titolo, assi, tacche, legenda |
| `title_size`, `label_size`, `tick_size`, `legend_size` | numero da 4 a 72 (punti) | dimensioni dei caratteri |
| `frame` | `open`, `box` | cornice |
| `grid`, `grid_minor` | `true` / `false` | griglia principale e secondaria |
| `legend` | `hidden`, `best`, `upper right`, … (le posizioni di Format Graph) | posizione globale della legenda |

Restano **sempre del grafico di destinazione** e non vengono letti né scritti: titolo, testi degli assi, scale e
limiti, stile per serie e per gruppo, linee di riferimento, guide e bande, interruzioni degli assi, forme,
annotazioni, confronti a coppie e le opzioni della legenda per voce (`legend_options`, conservate per intero).

Uno stile applicato diventa lo stile salvato del grafico (`run.style` e `graph_styles` del foglio): riaprendo il
progetto il grafico resta uguale anche se lo stile è stato eliminato dalla libreria o il progetto è aperto su un
altro computer.

## Formato JSON

```json
{
  "version": 1,
  "name": "Pubblicazione",
  "style": {"accent": "#0B7A73", "font_family": "serif", "title_size": 18, "grid": true, "legend": "upper right"}
}
```

- Nome: testo Unicode letterale di 1–64 caratteri, spazi ai bordi tolti, niente a capo o caratteri di controllo.
  I nomi sono unici ignorando maiuscole e forma Unicode (casefold + NFC): «Pubblicazione» e «PUBBLICAZIONE» sono
  lo stesso stile.
- Almeno un campo. Un file con chiavi in più, versione diversa da `1`, nome vuoto o valori fuori dominio
  (per esempio `title_size: 200`, `NaN`, una famiglia di caratteri sconosciuta) viene respinto **per intero**.
- Booleani, numeri e stringhe mantengono il loro tipo; un colore RGB salvato come tupla diventa una lista.

## Libreria locale

`graph-style-presets.json` nella cartella delle preferenze di Trama, accanto a `preferences.json`
(`%APPDATA%\TramaStat` su Windows, `$XDG_CONFIG_HOME/tramastat` o `~/.config/tramastat` altrove):

```json
{"version": 1, "presets": [ {"version": 1, "name": "Pubblicazione", "style": {…}} ]}
```

- Al massimo 100 stili. Ogni modifica (Salva stile, Importa…, Rinomina…, Elimina) è un'azione a sé che riscrive
  il file con un temporaneo nella stessa cartella e una sostituzione atomica: se la scrittura fallisce il file su
  disco resta com'era e il dialogo lo dice. Sostituire un omonimo ed eliminare chiedono conferma.
- Aprire il dialogo legge la libreria e non la scrive mai. Se il file è danneggiato (JSON troncato, stile non
  valido, nomi doppi, versione sconosciuta) il dialogo mostra il motivo e il percorso e blocca le modifiche;
  **Metti da parte il file danneggiato** lo rinomina in `graph-style-presets.damaged-AAAAMMGG-hhmmss.json` (da
  recuperare a mano) e riparte da una libreria vuota.
- Importa… accetta un file con **un solo** stile, al massimo 64 KiB. Esporta… scrive lo stile scelto nello stesso
  formato.

## Uso

1. Formatta un grafico (Format Graph o Inspector), poi Grafico → Stili di figura…, scrivi un nome e **Salva stile**
   (anche Invio nel campo Nome: salva senza chiudere il dialogo).
2. Su un altro grafico apri Stili di figura… e scegli uno stile: con *Anteprima sul grafico* attiva il grafico
   sullo schermo cambia subito, senza ricalcolare l'analisi.
3. **Applica** (o Invio, o doppio clic sullo stile) conferma; **Annulla** o Esc ripristinano il grafico com'era.

Se l'Inspector ha modifiche non applicate, prima chiede se applicarle, scartarle o tornare al grafico.

## Note tecniche

- Motore senza Qt: `trama_qt/graph_style_presets.py` (`extract_preset`, `apply_preset`, `validate_preset`,
  `read_preset_file`, `write_preset_file`, `PresetLibrary`). Validazione con `analisi.presentation.validated_style`.
- Dialogo: `trama_qt/graph_style_preset_dialog.py` (testi EN/IT locali al modulo). Anteprima con `apply_style`
  sulla figura e sul canvas esistenti; il risultato è lo stile completo che `MainWindow.graph_style_presets`
  rilegge contro il run attivo, valida sulla figura (`validate_graph_style`) e conferma una sola volta con
  `MainWindow.commit_style`. Il motore di calcolo non viene mai chiamato.
- Test: `tests/test_qt_graph_style_presets.py` (schema e libreria, senza Qt) e
  `tests/test_qt_graph_style_preset_dialog.py` (finestra offscreen). Collaudo con screenshot:
  `python tests/smoke_qt_graph_style_presets.py CARTELLA --lang it --theme dark` (usa preferenze temporanee e i dati
  sintetici di `tests/data/graph_style_presets`). Lo smoke generale `python -m trama_qt --smoke` apre anche questo
  dialogo.
