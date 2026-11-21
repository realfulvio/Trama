"""Measure recovery copies on two tabs of 10,000 × 30: ``python tests/perf_qt_recovery.py [OUTPUT.json]``.

For each tab: one cell changed, then a copy. Reports the time the GUI thread spends capturing the state (the only
part on the GUI thread), the longest pause between two GUI events while the copies are written in the background
(Python threads share one interpreter lock), the background time (serialise, hash, write) and the size; then the data stays still for
two intervals and the number of writes is counted (expected: none). Offscreen, temporary profile, synthetic data.
"""
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from unittest import mock  # noqa: E402


def main(output=None):
    app = QApplication.instance() or QApplication(["perf-recovery"])
    from trama_qt.recovery import RecoveryController
    from trama_qt.window import MainWindow

    now = [0.0]
    folder = tempfile.mkdtemp(prefix="trama-recovery-perf-")
    controller = RecoveryController(Path(folder) / "recovery", interval=30, clock=lambda: now[0],
                                    tick_ms=3_600_000, heartbeat_ms=3_600_000)
    window = MainWindow(recovery=controller)
    window.show()
    rng = np.random.default_rng(7)
    for tab in range(2):
        if tab:
            window.new_project()
        frame = pd.DataFrame({f"C{i}": pd.array(rng.random(10_000), dtype="Float64") for i in range(30)})
        window.project.add_tables({f"Grande {tab + 1}": frame})
    writes = []
    original = controller.store.write_snapshot

    def counting(*args, **options):
        writes.append(args[0])
        return original(*args, **options)

    controller.store.write_snapshot = counting
    for _ in range(5):  # The first paint of the window is not part of the measure.
        app.processEvents()
        time.sleep(0.05)
    rounds, latencies = [], []
    for round_ in range(3):
        for session in window.sessions:
            title = next(iter(session.project.tables))

            def change(dataset, value=round_ + 0.5):
                raw = dataset.raw.copy()
                raw.iat[0, 0] = value
                dataset.raw = raw

            session.project.edit(title, "Edit cell", change)  # One cell, as typing it would.
        start = time.perf_counter()
        controller.tick()
        now[0] += 30
        controller.tick()  # Both tabs (one not active) are captured here, on the GUI thread.
        tick_ms = (time.perf_counter() - start) * 1000
        gaps, last = [], time.perf_counter()
        done = controller.queue.submit(lambda: None)
        while not done.done():  # How long the GUI thread waits between two events while the copies are written.
            app.processEvents()
            time.sleep(0.005)
            now_ = time.perf_counter()
            gaps.append((now_ - last) * 1000)
            last = now_
        app.processEvents()
        rounds.append(tick_ms)
        latencies.append(max(gaps) if gaps else 0.0)
    timings = controller.timings[-6:]
    before = len(writes)
    for _ in range(2):
        now[0] += 30
        controller.tick()
        controller.wait(60)
        app.processEvents()
    result = {
        "tables": "2 tabs × 10,000 rows × 30 columns",
        "gui_tick_ms_two_tabs": [round(value, 1) for value in rounds],
        "gui_max_event_gap_ms_while_writing": [round(value, 1) for value in latencies],
        "gui_capture_ms_per_tab": [round(item[1], 2) for item in timings],
        "background_ms_per_copy": [round(item[2], 1) for item in timings],
        "copy_bytes": timings[-1][3] if timings else None,
        "median_gui_capture_ms": round(statistics.median(item[1] for item in timings), 2) if timings else None,
        "median_background_ms": round(statistics.median(item[2] for item in timings), 1) if timings else None,
        "writes_while_still_for_two_intervals": len(writes) - before,
    }
    for session in window.sessions:
        session.project.dirty = False
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        window.close()
    text = json.dumps(result, indent=2)
    print(text)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
