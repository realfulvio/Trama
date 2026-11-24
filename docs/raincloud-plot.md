# Raincloud plot

Canonical method: `Raincloud plot` (*Grafico raincloud* in Italian), under **Graphing** and **New graph**.

## Options

- `Response`: numeric response column. Non-numeric, blank, or non-finite values are discarded and counted in `Settings`.
- `Group`: optional categorical grouping column. When omitted, all valid observations form one group (`All`). Blank or missing group entries are discarded.
- `Orientation`: `Vertical` (default, value on Y, groups on X) or `Horizontal` (value on X, groups on Y).
- `Show density`, `Show box`, `Show points`: independent component toggles (at least one must stay enabled).
- `Bandwidth multiplier`: positive finite multiplier for Gaussian KDE (Scott's rule), shown and validated only when `Show density` is active.

## Geometry & Rules

- **Half-violin (cloud)**: drawn strictly on the positive side of the category center (`[pos + 0.05, pos + 0.41]`), scaled so each group's peak fills the same lane width regardless of `N`. Singleton and constant groups produce no density.
- **Compact box**: centered on `pos` (`width = 0.08`), using rank `(N + 1) p` interpolated quartiles (saturated at extremes) and inclusive Tukey `1.5 × IQR` fences; groups with `N < 4` show median and min–max range with empty `Q1`/`Q3`.
- **Rain (points)**: drawn strictly on the negative side (`[pos - 0.39, pos - 0.09]`) using deterministic bounded offsets and a single `PathCollection` per group containing all valid observations (no hidden subsampling).
- **Group order & styles**: follows worksheet category order when set, otherwise first appearance; typed identities (`raincloud:<token>`) keep group styles attached across reorders, edits, exclusions, and `.alab` saves.

## Output Sheets

- `Raincloud summary`: `Group`, `N`, `Minimum`, `Q1`, `Median`, `Q3`, `Maximum`, `Whisker low`, `Whisker high`.
- `Raincloud density` (present when `Show density` is enabled): `Group`, `Value`, `Density` (unscaled KDE).
- `Settings`: active options, observation and discard counts, percentile/whisker rules, and KDE parameters.
