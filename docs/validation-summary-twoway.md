# Two-way ANOVA from summaries: checks

Base `v0.106.0`, commit `e634fa251080d5e732b5836efe9b057f5aa7bcb2`. The candidate is the tip of `anova-due-fattori-riassunti`. Version, packaging and the site were not changed. The numbers below were measured on that base plus this command, with `uv run --no-project python` from the worktree (Python 3.14.10, pandas 3.1.1, PySide6 6.12.0).

## Engine

`tests/test_summary_twoway.py` and `tests/test_catalog.py`:

```text
uv run --no-project python -m unittest tests.test_summary_twoway tests.test_catalog
Ran 16 tests in 3.241s
OK
```

The balanced and unbalanced grids match `tests/data/summary-twoway/oracolo.json` from SD and from SEM, including a reordered table and the literal level `Dose $`. Changing the A1/B1 mean from 12 to 14 gives F 75, 147 and 27, with residual sum of squares 8. Save, reopen, Undo, Redo and a locked sheet are covered. A 10×10 grid with N = 1,000,000,000 per cell finished in 0.016 s, returned 100 summary rows, and used residual df 99,999,999,900. No length-N replicate vector is allocated.

## Suite

```text
uv run --no-project python -m unittest discover -s tests -p 'test_*.py'
Ran 5129 tests in 1831.288s
FAILED (errors=79, skipped=34)
```

There were no assertion failures. All 79 errors are the missing classic Tk library `libtk8.6.so` on this Python 3.14, including the startup check that imports `tkinter`. None names the new command. `sudo` could not install Tk here.

## Desktop

Linux native, Wayland, screen eDP-1, available 1920×1080, device pixel ratio 1.0, logical DPI 96. English and Italian, light and dark:

```text
uv run --no-project python -m trama_qt.summary_twoway_smoke docs/media/summary-twoway/linux --languages en,it --themes light,dark
```

PASS in 12.36 s, 28 screenshots. Each language and theme finished its own step in about 1.95 s. The grouped sheet opens on summary subcolumns. Clearing N shows the field error and does not run. Restoring N produces F 48, 108 and 12. The project `docs/media/summary-twoway/linux/summary-twoway-en.alab` reopens that recipe. The exported CSV is the later edit, A1/B1 mean 14, with F 75, 147 and 27. Undo, Redo and the frozen sheet were checked. The long CSV is mapped in the dialog, and `Dose $` is kept.

Emulated scale on the same screen, platform xcb, light theme, English and Italian:

```text
QT_SCALE_FACTOR=1.25 QT_QPA_PLATFORM=xcb uv run --no-project python -m trama_qt.summary_twoway_smoke docs/media/summary-twoway/dpi-125 --languages en,it --themes light
QT_SCALE_FACTOR=1.5 QT_QPA_PLATFORM=xcb uv run --no-project python -m trama_qt.summary_twoway_smoke docs/media/summary-twoway/dpi-150 --languages en,it --themes light
```

Both PASS, in 6.59 s and 6.51 s. The reports record device pixel ratio 1.25 (available 1536×864) and 1.5 (available 1280×720). The field-error dialog grab is 940×640 at ratio 1, 1175×800 at 1.25, and 1410×960 at 1.5.

Windows native was not run. `ssh santabianca-hcok` timed out, `ssh win-test` closed the connection, and `ssh dev` timed out, all on 2026-11-25.
