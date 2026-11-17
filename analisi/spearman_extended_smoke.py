"""Native-widget acceptance for the extended exact Spearman policy."""
from math import factorial
import json
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .spearman_exact_budget import FIELD, EXTENDED, STANDARD
from . import spearman_exact_budget as engine


def check_spearman_extended(root, app, directory, tools):
    out = directory / "spearman-extended"
    out.mkdir(exist_ok=True)
    language, geometry, compute = i18n.active_language(), root.geometry(), app.compute
    timings, cpu_timings, ui_waits = [], [], []
    def wait():
        # An exact n=17 law is materially larger than the legacy n<=9 checks.
        # Bound this test independently; record both worker CPU and UI polling.
        start = time.monotonic()
        deadline = start + 120
        ticks = 0
        while app.pending is not None:
            if time.monotonic() > deadline:
                app.cancel_calculation()
                raise TimeoutError("Extended Spearman did not complete within its 120 s acceptance budget")
            root.update()
            ticks += 1
            time.sleep(.02)
        ui_waits.append({"seconds":time.monotonic()-start,"event_loop_polls":ticks})
        assert not tools.errors, tools.errors
    def wrapped(run, frame, *args, **kwargs):
        start, cpu = time.perf_counter(), time.thread_time()
        try:
            return compute(run, frame, *args, **kwargs)
        finally:
            elapsed = time.perf_counter()-start
            timings.append((threading.current_thread().name, elapsed))
            cpu_timings.append({"seconds":elapsed,"worker_cpu_seconds":time.thread_time()-cpu})
            (out / "worker-timings.json").write_text(json.dumps(cpu_timings, indent=2))
    def capture(window, name):
        window.lift(); window.update()
        tools.capture(window, name)
        path = directory / name
        if path.exists():
            path.replace(out / name)
    def row(index):
        return app.runs[index].result.tables["Correlation"]["Value"]
    def configure(dialog):
        tools.pick_method(dialog, "Correlation")
        for key, value in {"X":"X", "Y":"Y", "Method":"Spearman", "Detailed results":True,
                           "Spearman p values":"Exact"}.items():
            dialog.controls[key][1].set(value)
        assert dialog.controls[FIELD][1].get() == EXTENDED
        dialog.fields.select(1); dialog.update()
        assert dialog.field_rows[FIELD][1].winfo_viewable()
        assert dialog.winfo_rooty()+dialog.winfo_height() <= root.winfo_screenheight()
        capture(dialog, f"dialog-spearman-{i18n.active_language()}.png")
    try:
        app.compute = wrapped
        i18n.set_language("en")
        x = np.arange(17.)
        frame = pd.DataFrame({"X":x, "Y":x, "Tied":np.r_[0.,np.arange(16.)]})
        path = out / "input.alab"
        save_project(path, {"Exact 17":Dataset(frame)})
        app.import_file(path)
        app.show("data", "Exact 17")
        tools.drive_dialog(tools.AnalysisDialog, configure)
        app.choose_analysis(only="Correlation"); wait()
        assert not tools.errors, tools.errors
        index = len(app.runs)-1
        assert row(index)["P method"] == "Exact"
        assert abs(float(row(index)["p"])/(2/factorial(17))-1) < 1e-12
        app.show("graph", index); root.update()
        capture(root, "graph-spearman-exact17.png")
        for suffix in ("svg", "png", "pdf"):
            app.runs[index].result.figure.savefig(out / ("exact17."+suffix))
        app.runs[index].result.tables["Ranks"].to_csv(out / "ranks.csv")

        # Same candidate settings, translated display; canonical recipe survives.
        i18n.set_language("it")
        app.show("result", index)
        tools.drive_dialog(tools.AnalysisDialog, configure)
        app.edit_analysis(); wait()
        assert app.runs[index].options[FIELD] == EXTENDED
        saved = out / "roundtrip.alab"
        app.path = saved
        assert app.save()
        i18n.set_language("en")
        app.import_file(saved)
        index = next(i for i, run in enumerate(app.runs) if run.options.get(FIELD) == EXTENDED)
        app.show("graph", index)
        if app.runs[index].result is None:
            app.recalculate(index)
        wait()
        assert row(index)["P method"] == "Exact"

        # Source exclusion drops n only for the current complete pairs.
        app.show("data", "Exact 17")
        app.current_grid.active_cell = (4, 1)
        app.toggle_exclusion(); wait()
        assert row(index)["N"] == 16 and row(index)["P method"] == "Exact"
        app.apply_worksheet_history(); wait()
        assert row(index)["N"] == 17
        app.edit_cell(2, 1, "3.5"); wait()
        assert row(index)["P method"] == "Exact" and float(row(index)["p"]) > 2/factorial(17)

        # Cancellation happens inside the real shared DP; no partial result replaces a completed one.
        kept = app.runs[index].result
        entered = threading.Event()
        counter = engine._count_permutation_distribution
        def slowed(*args, **kwargs):
            entered.set()
            check = kwargs["check"]
            while not app.calculation.cancel.is_set():
                time.sleep(.01)
            check()
            return counter(*args, **kwargs)
        with patch.object(engine, "_count_permutation_distribution", slowed):
            app.show("result", index)
            tools.drive_dialog(tools.AnalysisDialog, lambda dialog: None)
            app.edit_analysis()
            deadline = time.monotonic()+10
            while not entered.is_set():
                assert time.monotonic() < deadline
                root.update(); time.sleep(.01)
            assert app.cancel_button.winfo_manager()
            app.cancel_calculation(); wait()
            assert app.runs[index].result is kept
            assert "cancelled" in app.status.get()
            count = len(app.runs)
            entered.clear()
            app.show("data", "Exact 17")
            tools.drive_dialog(tools.AnalysisDialog, configure)
            app.choose_analysis(only="Correlation")
            deadline = time.monotonic()+10
            while not entered.is_set():
                assert time.monotonic() < deadline
                root.update(); time.sleep(.01)
            app.cancel_calculation(); wait()
            assert len(app.runs) == count

        # Strict memory failure reopens the candidate, preserving settings and focused field.
        family = engine.ExactSpearmanFamily
        with patch("analisi.correlation_details.ExactSpearmanFamily",
                   side_effect=lambda **kwargs: family(max_bytes=1, **kwargs)):
            seen = []
            def recovered(dialog):
                assert dialog.controls[FIELD][1].get() == EXTENDED
                assert dialog.initial_field == FIELD
                assert "storage" in str(dialog.error)
                seen.append(True)
                dialog.controls["Spearman p values"][1].set("Approximate")
            app.show("result", index)
            tools.drive_dialog(tools.AnalysisDialog,
                lambda dialog: root.after(100, lambda: tools.drive_dialog(tools.AnalysisDialog, recovered)))
            app.edit_analysis(); wait()
            assert seen and row(index)["P method"] == "Approximate"
        assert all(name.startswith("Trama") for name, _ in timings), timings
        assert not tools.errors, tools.errors
        (out / "measurements.json").write_text(json.dumps({"timings":timings,"worker_cpu":cpu_timings,"ui_waits":ui_waits,
            "screen":[root.winfo_screenwidth(),root.winfo_screenheight()],
            "dpi":root.winfo_fpixels("1i"), "checks":"exact17, EN/IT, roundtrip, source edits/exclusions, cancellation, recovery"}, indent=2))
    finally:
        app.compute = compute
        i18n.set_language(language)
        root.geometry(geometry); root.update()
