# Linked coefficients · Coefficienti collegati

*Fit custom equation* and *Global fit custom equation* (Classica Qt) can define a coefficient as an affine function of another one: `C = factor × source + offset`, for example `C = 2*A + 1`. The fit estimates only the independent coefficients; the linked one is recomputed from its source at every step and reported with its uncertainty.

## English

**Where.** Analysis dialog → *Parameters*. The table has three more columns: **Linked to**, **Factor**, **Offset**.

- *Fit custom equation*: choose the source in **Linked to** (the cell offers the other coefficients and *(not linked)*). Factor and Offset start at 1 and 0. **Fixed** and **Linked to** exclude each other: ticking Fixed removes the link.
- *Global fit custom equation*: the **Scope** column adds **Linked (per series)** and **Linked (shared)**. Choosing a source switches the scope to Linked by itself. A *shared* linked coefficient has one value for every series, so its source must have one too (Shared, or Fixed to the same value); a *per series* one may follow a shared coefficient or the local coefficient of the same series. On *Series constraints* a linked coefficient accepts only lower and upper limits.

**Before Run.** Under the table the dialog shows the resolved formula of each link (a chain also in terms of its root: `D = -0.5*C + 3 (D = -A + 2.5)`), the dependency order (`A → C → D`), the starting value each linked coefficient takes from its link (shown in italics and read-only in Start) and the limits that the fit will use on the source. A problem is written in the same place and Run keeps the dialog open on the right cell:

| Problem | Message (start) |
| --- | --- |
| cycle | `The links form a cycle: A → C → A.` |
| missing source | `C: the link source Z is not a coefficient of this equation.` |
| Fixed and Linked together | `C: a coefficient cannot be both Fixed and Linked.` |
| limits that leave no value | `C: its limits (10 to 20) and the link C = -2*A + 1 leave no admissible value for A …` |
| fixed or zero-factor value outside the limits | `C: the link C = 2*A + 1 gives C = 5, outside its limits …` |
| start of the source outside the carried range | `A: the starting value 1 lies outside the range allowed by the links of C (-2 to 0).` |
| shared link to a local source | `C: a shared linked coefficient needs a source with the same value in every series …` |
| fixed/start of one series on a linked coefficient | `Series 'Uno', C: a linked coefficient takes its value from its link …` |

**Limits.** The limits of a linked coefficient are carried onto its root (reversed for a negative factor) and intersected with the root's own limits and with every per-series limit. With `C = -2*A + 1` and `1 ≤ C ≤ 5` the fit uses `-2 ≤ A ≤ 0`. A factor of 0 makes the coefficient the constant *offset*, which must lie inside its limits.

**Results.** The Parameters sheet adds a **Relation** column and the status **Linked**; in the global fit the linked rows come after the estimated and fixed ones, with Scope and Group. The summary adds *Linked parameters*, *Dependency order* and *Links*. *Free parameters* and the residual df count only the estimated coefficients. SE and intervals of a linked coefficient are the affine image of its root (`SE(C) = |factor| × SE(A)`); profile limits are mapped and swapped for a negative factor, with their status and reason. The Covariance sheet of the global fit includes the linked coefficients. When the root is at a limit, or the fit is exact, or every coefficient ends up fixed (also through the links), the usual rules apply and the summary says why there is no SE.

**Rename and delete.** Renaming a coefficient updates the links that use it; removing it frees its dependents again, starting from the value they had through the link. Recipes without links are written exactly as before, and older projects open unchanged.

## Italiano

**Dove.** Finestra dell'analisi → *Parametri*. La tabella ha tre colonne in più: **Collegato a**, **Fattore**, **Scostamento**.

- *Adatta un'equazione personalizzata*: scegli la sorgente in **Collegato a**. Fattore e Scostamento partono da 1 e 0. **Fisso** e **Collegato a** si escludono.
- *Adattamento globale*: la colonna **Ambito** aggiunge **Collegato (per serie)** e **Collegato (condiviso)**. Un collegato condiviso richiede una sorgente con lo stesso valore in tutte le serie; uno per serie può seguire un condiviso o il locale della stessa serie. In *Vincoli per serie* un collegato accetta solo i limiti.

**Prima di Esegui** la finestra mostra la formula risolta, l'ordine delle dipendenze, il valore iniziale preso dal legame e i limiti effettivi della sorgente; gli errori (ciclo, sorgente assente, Fisso e Collegato insieme, limiti incompatibili, legame condiviso verso un locale) compaiono nello stesso punto e tengono aperta la finestra sulla cella giusta.

**Risultati.** Colonna **Relation** e stato **Linked**, righe di riepilogo *Linked parameters*, *Dependency order*, *Links*. I gradi di libertà contano solo i parametri stimati. SE e intervalli del collegato sono l'immagine affine di quelli della radice (estremi scambiati con fattore negativo); i profili ne conservano stato e motivo.

## Example and checks

- `docs/examples/Coefficienti-collegati-singolo.alab` and `Coefficienti-collegati-globale.alab` (data `tests/data/coefficient_links/curve.csv`).
- `python tests/coefficient_links_measure.py misurato.json [--reopen]` then `python tests/data/coefficient_links/confronta.py misurato.json --tolleranza 1e-6`.
- `python tests/bench_coefficient_links.py` (10 series × 5,000 rows).
- `python -m trama_qt.coefficient_links_smoke OUT --lang it --theme dark` (real window).
