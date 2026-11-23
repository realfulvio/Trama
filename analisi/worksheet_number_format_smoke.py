"""Desktop smoke check of Change → Number format… on the classic Tk window.

Alone: ``TRAMASTAT_SMOKE_ONLY=number-format python tramastat.py --smoke DIR`` (the language comes from the
preferences, as at every start; run it once per language). With ``TRAMASTAT_SMOKE_SCREENSHOTS=1`` and ImageMagick
on X11, pictures of the real dialog at 1024×768 and 1600×1000 go to ``DIR/number-format``, with
``timings-<language>.txt``: open, scroll to the end and format change on 50 000 × 20 cells.
"""
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from unittest.mock import patch

import numpy as np
import pandas as pd

from .i18n import active_language
from .worksheet_number_format import Renderer

SIZES = ((1024, 768), (1600, 1000))
FIXTURE = pd.DataFrame({
    "Categoria": ["Controllo", "Prima", "Seconda", "Terza", "Quarta"],
    "Dose": [0.000125, 1.23456789012345, 12345.6789, 0.5, float("nan")],
    "Risposta": [2.125, -0.0004, -0.0, 1.2345e-14, 950.0],
    "Repliche": [4, 4, 12, 9999, 0],
})


def _grab(root, path, size):
    if sys.platform == "win32" or not os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS") or not shutil.which("import"):
        return False
    root.update_idletasks()
    root.update()
    time.sleep(.2)
    width, height = size
    subprocess.run(["import", "-window", "root", "-crop", f"{width}x{height}+0+0", "+repage", str(path)],
                   check=True, timeout=30)
    return True


def _dialog(root):
    return [widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel)][-1]


def check_number_format(root, app, directory, tools):
    folder = directory / "number-format"
    folder.mkdir(parents=True, exist_ok=True)
    language = active_language()
    errors = tools.errors
    app._add_tables({"celle": FIXTURE.copy()})
    data = app.tables["celle"]
    data.set_background((1, 1, 1, 1), "#ffd966")
    app.show("data", "celle")
    root.update()
    grid = app.current_grid
    seen = []

    for number, size in enumerate(SIZES):
        root.geometry(f"{size[0]}x{size[1]}+0+0")
        root.update()
        grid = app.current_grid
        grid.select_block(1, 0, 4, 2)
        last = number == len(SIZES) - 1

        def drive(size=size, last=last):
            dialog = _dialog(root)
            dialog.update()
            if dialog.winfo_rootx() + dialog.winfo_width() > size[0] or \
                    dialog.winfo_rooty() + dialog.winfo_height() > size[1]:
                errors.append(f"number format dialog leaves the {size[0]}×{size[1]} window")
            dialog.mode.set("fixed")
            dialog.mode_changed()
            dialog.digits.set("3")
            dialog.digits_changed()
            seen.append(dialog.shown.cget("text"))
            _grab(root, folder / f"{language}-tk-number-format-{size[0]}x{size[1]}.png", size)
            dialog.ok() if last else dialog.cancel()

        root.after(400, drive)
        app.change_number_format()
        root.update()
    if seen[-1] != ("1,235" if language == "it" else "1.235"):
        errors.append(f"number format preview shows {seen[-1]!r}")
    expected = {"Dose": {"mode": "fixed", "digits": 3}, "Risposta": {"mode": "fixed", "digits": 3}}
    if data.number_formats != expected:
        errors.append(f"number formats after OK: {data.number_formats}")
    mark = "," if language == "it" else "."
    if [grid.shown_text(row, 1) for row in range(4)] != [f"0{mark}000", f"1{mark}235", f"12345{mark}679",
                                                          f"0{mark}500"]:
        errors.append("the Dose column does not show three decimals")
    if grid.cell_text(1, 1) != "1.23456789" or data.raw.iat[1, 1] != 1.23456789012345:
        errors.append("the stored number changed")
    if data.cell_backgrounds.get((1, "Dose")) != "#ffd966":
        errors.append("the highlight was lost")
    _grab(root, folder / f"{language}-tk-number-format-applied.png", SIZES[-1])
    app.apply_worksheet_history()
    root.update()
    if data.number_formats:
        errors.append("Undo kept the number format")
    app.apply_worksheet_history(redo=True)
    root.update()

    # 50 000 × 20: open, scroll to the end, format every column; only the visible cells are drawn.
    big = pd.DataFrame(np.random.default_rng(7).normal(size=(50_000, 20)) * 1000,
                       columns=[f"C{index + 1}" for index in range(20)])
    started = time.perf_counter()
    app._add_tables({"big": big})
    root.update()
    opened = time.perf_counter() - started
    grid = app.current_grid
    started = time.perf_counter()
    grid.canvas.yview_moveto(1.0)
    grid.draw()
    root.update()
    scrolled = time.perf_counter() - started
    grid.select_block(0, 0, 49_999, 19)
    calls = []
    original = Renderer.text

    def counted(self, position, value):
        calls.append(position)
        return original(self, position, value)

    class Confirm:
        def __init__(self, parent, target):
            self.choice = ("apply", {"mode": "scientific", "digits": 2})

    import analisi.worksheet_number_format_dialog as dialogs
    started = time.perf_counter()
    with patch.object(Renderer, "text", counted), patch.object(dialogs, "NumberFormatDialog", Confirm):
        app.change_number_format()
        grid.draw()
        root.update()
    changed = time.perf_counter() - started
    if len(app.tables["big"].number_formats) != 20:
        errors.append("the 50 000 × 20 sheet did not take the format")
    if not calls or len(calls) > 20 * 200:
        errors.append(f"format change rendered {len(calls)} cells, not only the visible ones")
    lines = [f"Tk {tk.TkVersion} · {language} · window {SIZES[-1][0]}×{SIZES[-1][1]}",
             f"open 50000×20: {opened:.3f} s", f"scroll to the end: {scrolled:.3f} s",
             f"format change on 20 columns: {changed:.3f} s ({len(calls)} cells rendered)"]
    (folder / f"timings-{language}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    app.dirty = False
