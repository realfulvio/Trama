# Multivariate Bubble Plot

The **Bubble plot** encodes up to four visual channels from a single worksheet alongside **(X, Y)** position:

1. **Size (`Size mode`)**
   - **From column**: marker area is proportional to positive values (`area = Maximum area × value / largest drawn size`). The size legend shows both the column name and the maximum area in `pt²`. Zero, missing, or negative size rules are preserved cleanly.
   - **Fixed area**: all drawn points share a uniform area in `pt²`; a single valid `(X, Y)` pair suffices without requiring a `Size` column.

2. **Fill color (`Fill color`)**
   - **By category**: colors levels of `Group` with an optional per-level color editor (`Category colors`), preserving legacy behavior when no overrides are set.
   - **Fixed color**: single uniform color (`Point color`).
   - **Continuous scale**: maps a numeric `Color` column onto sequential (*Viridis*, *Cividis*, *Blues*, *Magma*, *Greys*) or diverging (*Blue–red*, *Cool–warm*, *Purple–green*) palettes.
     - **Reverse palette**: exact `1 − u` coordinate reversal.
     - **Automatic or Manual limits**: automatic ranges are computed **exclusively from drawn points with finite signals**; out-of-range manual values clamp to endpoint colors.
     - **Diverging midpoint**: sets an internal two-slope center (e.g. center `25` between `0` and `100` maps `0, 25, 100 → 0, 0.5, 1`).
     - **Constant & missing signals**: constant signals draw at center color (`0.5`) with a single colorbar tick; missing values render in `Missing color` (if all signals are missing, points stay visible with an explanatory legend).

3. **Symbol shape (`Shape mode`)**
   - **Fixed shape**: single symbol across all points.
   - **By category**: assigns **12 distinct symbols** automatically (raising a repetition warning if levels exceed 12 or duplicates are assigned). Homonymous number and text categories (e.g. integer `1` vs `"1"`) remain separate typed identities, and symbol assignments stay keyed to category identity across row reordering, save, and reopen. Missing cells receive `Missing shape`.

4. **Qt integration & non-recalculation**
   - Live encoding controls are built into **Graph Inspector**, **Change → Symbols & encoding…** (`Ctrl+Shift+B`), the graph page header button, and **Format graph…**.
   - Previews revert cleanly on **Discard / Cancel / Esc** and commit in a single undoable **Apply** step (`Ctrl+Z`), synchronizing `Bubble values` and `Settings` tables without re-running project statistics.
