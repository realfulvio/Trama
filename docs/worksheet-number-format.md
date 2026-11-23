# Number format of worksheets and result tables

Choose **Change → Number format…** (Italian: *Cambia → Formato numerico…*) to decide how the selected numeric columns of a data table or of a result tab are **shown**. The stored numbers never change: formulas, analyses, editing and *Use Result as Data* use every digit, and Copy and CSV/XLSX export write the same text as without a format. The command is also in the context menu of the Qt worksheet. It is one step of Undo/Redo, in both interfaces.

## Modes

| Mode | Digits | Example (1234.5678) |
|---|---|---|
| Automatic | — | the usual display (up to ten significant digits) |
| Fixed decimals | 0–12 decimals | 2 → `1234.57` |
| Significant digits | 1–15 digits | 3 → `1.23e+03` |
| Scientific notation | 0–12 decimals | 3 → `1.235e+03` |

Ties round half to even (`2.125` with two decimals shows `2.12`). A rounded negative zero shows as `0`. The exponent always has a sign and at least two digits. The decimal separator follows the display language (comma in Italian); the separator used for typing and for exports keeps its own preference.

## What changes and what does not

- The selection may cover several contiguous columns. The dialog lists the columns that change and those that keep their style, with the reason: text, row titles, codes (whole-number columns of a survival table), counts (contingency tables) or a format chosen by the analysis (ROC thresholds, p-value texts).
- Booleans, missing values and infinities keep their usual text.
- Calculated (`ƒx`) numeric columns can be formatted even though they are read-only.
- The preview uses a real value of the selection: the active cell when it holds a number, otherwise the first number found. A sample value is used only when the selection has none.
- **Cancel** and **Esc** leave the sheet untouched. **OK** applies the format. **Reset** (enabled when a selected column has a format) returns the columns to Automatic. Choosing Automatic also removes the format.
- In a data table, the cell editor starts from the stored, unrounded number.

## Saving

Formats are saved in the project (`.alab`) and shared by the Qt and the classic Tk interfaces:

- data tables: by column name (`number_formats`), so a format follows its column when the order changes or the column is renamed, and disappears when the column is deleted;
- result tables: by analysis, sheet and column position (`result_number_formats`), so two tabs of the same fit keep separate formats and recalculation keeps them.

Older projects open unchanged. Older versions of Trama ignore the two new keys. Family duplication and recovery copies keep the formats.

`docs/examples/Formato-numerico.alab` holds the fixture of the request with formats on two columns, a highlighted cell, and a Deming fit whose *Data* and *Pairs* tabs have different formats.
