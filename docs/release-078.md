# Trama 0.78.0 beta — candidate

This candidate adds grouped false-discovery control (BH, BY and two-stage BKY), custom numeric axis ticks, reference lines and shaded ranges. Existing analysis recipes and reference-line styles remain supported.

Failed FDR recalculations retain the last successful result with a visible stale-result warning and block export or reuse until the input is corrected. Opposite-side ticks outside the current view no longer enlarge tightly cropped exports.

See [false-discovery control](fdr-control.md) and [axis guides](axis-guides.md) for scope, statistical conventions and limits. Native Windows acceptance is required before publication.
