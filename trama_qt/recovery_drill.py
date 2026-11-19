"""Controlled crash of a real Trama process and recovery in a new one: ``python -m trama_qt.recovery_drill FOLDER``.

For each language (English and Italian) and each case the drill:

1. prepares an isolated profile (``APPDATA`` on Windows, ``XDG_CONFIG_HOME`` elsewhere) and a working folder with a
   copy of ``tests/data/qt_recovery/misure-salvate.alab``;
2. starts a separate Trama process (``--child``) on that profile with a 1-second interval. It opens the copy,
   changes a cell, excludes a value, changes an Info note, draws the graph and puts it in a layout, then opens a
   second, never-saved project and types a value. When both recovery copies are on disk and verified it prints
   ``READY`` with its PID, keys, generations and hashes;
3. kills only that PID (``Popen.kill``: SIGKILL, TerminateProcess on Windows);
4. starts the main window again on the same profile (in this process), checks the start-up notice and the
   dialog, recovers one copy, leaves the other, reopens it from File → Recover projects…, checks that Save as
   cancelled keeps the copy and Save as removes it, and that the original file has the same bytes;
5. the second case changes the original outside Trama and damages one reference before reopening: the dialog shows
   the changed original and the damaged copy, and the other copy still opens.

Everything goes into FOLDER: ``<lang>-*.png`` screenshots (checked for clipped text like the Qt smoke),
``report.json`` (hashes, PIDs, timings, each step PASS/FAIL), ``drill.log`` and ``status.txt``. Exit code 0 on PASS.
Synthetic data only.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "data" / "qt_recovery" / "misure-salvate.alab"
TABLE = "Calibrazione $ <β>"


def digest(data):
    return sha256(data).hexdigest()


def profile_env(profile, language):
    env = dict(os.environ)
    env["APPDATA"] = str(profile)
    env["XDG_CONFIG_HOME"] = str(profile)
    folder = profile / ("TramaStat" if sys.platform.startswith("win") else "tramastat")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "preferences.json").write_text(json.dumps({"language": language}), encoding="utf-8")
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def wait_until(app, condition, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    app.processEvents()
    return condition()


# == the process that is killed ===========================================================================
def child(workdir):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["trama-recovery-child"])
    from analisi.i18n import config_path, load_language, set_language
    set_language(load_language(config_path()))
    from analisi.presentation import Layout
    from . import theme
    from .recovery import RecoveryController
    from .window import MainWindow

    theme.load_fonts()
    theme.apply(app)
    controller = RecoveryController(config_path().parent / "recovery", settings_path=config_path(), interval=1,
                                    tick_ms=200)
    window = MainWindow(recovery=controller)
    window.error = lambda error: print(f"ERROR {error}", flush=True)
    window.show()
    QTimer.singleShot(180_000, lambda: os._exit(3))  # Never outlive a drill that went wrong.

    def idle():
        return wait_until(app, lambda: window.job is None, 60)

    window.open_path(Path(workdir) / "misure-salvate.alab")
    idle()
    project = window.project
    window.edit_cell(TABLE, 4, 1, "15")
    idle()
    project.toggle_exclusion(TABLE, {(1, 1)})
    sheet = next(iter(project.info_sheets.values()))
    from dataclasses import replace
    project.change_info(replace(sheet, notes="Nota confermata prima dell’interruzione."))
    window.open_sheet(("graph", 0))
    idle()
    project.put_layout(Layout("Pannello", 1, [project.runs[0].reference]))
    window.new_project()
    window.new_table()
    window.edit_cell(next(iter(window.project.tables)), 0, 0, "99")
    idle()
    projects = [session.project for session in window.sessions]

    def ready():
        for project in projects:  # Every confirmed change is in a copy...
            tracked = controller.tracked.get(project.recovery_key)
            if tracked is None or tracked.writing or tracked.captured != project.revision:
                return False
        try:
            records = {record["session_key"]: record for record in controller.store.list_snapshots()}
        except OSError:
            return False
        return all(project.recovery_key in records for project in projects)  # ...and verified on disk.

    if not wait_until(app, ready, 60):
        print("NOT READY", flush=True)
        return 2
    records = {record["session_key"]: record for record in controller.store.list_snapshots()}
    print("READY " + json.dumps({
        "pid": os.getpid(),
        "copies": [{"key": project.recovery_key, "title": project.title,
                    "generation": records[project.recovery_key]["generation"],
                    "sha256": records[project.recovery_key]["sha256"]} for project in projects],
        "timings": controller.timings,
    }), flush=True)
    return app.exec()


# == the drill ============================================================================================
class Drill:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.steps = []
        self.log_lines = []
        self.report = {"platform": sys.platform, "python": sys.version.split()[0], "cases": []}

    def log(self, text):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        self.log_lines.append(line)
        print(line, flush=True)

    def step(self, case, name, ok, detail=""):
        self.steps.append({"case": case, "step": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        self.log(f"{'PASS' if ok else 'FAIL'} {case} · {name} {detail}")
        return ok

    def crash(self, case, language, work):
        """Start a child on a fresh profile, wait for its two copies, kill it. Returns (profile, ready, info)."""
        profile = work / "profile"
        data = work / "dati"
        data.mkdir(parents=True)
        shutil.copy2(FIXTURE, data / "misure-salvate.alab")
        env = profile_env(profile, language)
        command = [sys.executable, "-m", "trama_qt.recovery_drill", "--child", str(data)]
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        ready = None
        output = []
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            output.append(line.rstrip())
            if line.startswith("READY "):
                ready = json.loads(line[6:])
                break
        (self.folder / f"{case}-child.log").write_text("\n".join(output) + "\n", encoding="utf-8")
        if ready is None:
            process.kill()
            process.wait(10)
            raise RuntimeError(f"the Trama process did not get ready: {output[-5:]}")
        self.log(f"{case}: child PID {process.pid} ready in {time.monotonic() - started:.1f} s")
        process.kill()  # Only that PID.
        code = process.wait(30)
        info = {"pid": process.pid, "ready_pid": ready["pid"], "exit_code": code, "copies": ready["copies"],
                "child_timings": ready.get("timings")}
        self.step(case, "child killed", ready["pid"] == process.pid and code != 0, f"exit code {code}")
        return profile, data, info

    def window(self, profile, language):
        from analisi.i18n import config_path, set_language
        from .recovery import RecoveryController
        from .window import MainWindow
        os.environ["APPDATA"] = str(profile)
        os.environ["XDG_CONFIG_HOME"] = str(profile)
        set_language(language)
        controller = RecoveryController.for_profile()
        assert controller.root == config_path().parent / "recovery"
        window = MainWindow(recovery=controller)
        window.errors = []
        window.error = lambda error: window.errors.append(str(error))
        return window

    def case_recover(self, smoke, language, work):
        from unittest import mock
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QFileDialog
        from .recovery import RecoveryDialog
        from .recovery_store import RecoveryStore

        case = f"{language}-recover"
        smoke.language = language
        profile, data, info = self.crash(case, language, work)
        original = data / "misure-salvate.alab"
        info["original_sha256_before"] = digest(FIXTURE.read_bytes())
        store_root = (profile / ("TramaStat" if sys.platform.startswith("win") else "tramastat") / "recovery")
        store = RecoveryStore(store_root)
        on_disk = {record["session_key"]: record for record in store.list_snapshots()}
        info["copies_after_kill"] = {key: {"generation": record["generation"], "sha256": record["sha256"]}
                                     for key, record in on_disk.items()}
        self.step(case, "both copies verifiable after the kill",
                  {copy["key"] for copy in info["copies"]} == set(on_disk)
                  and all(on_disk[copy["key"]]["sha256"] == copy["sha256"] for copy in info["copies"]))
        app = QApplication.instance()
        window = self.window(profile, language)
        if smoke.size:
            window.resize(*smoke.size)
        window.show()
        try:
            self.step(case, "start-up notice", wait_until(app, lambda: window.recovery.notice is not None, 20))
            smoke.shot(window, "recovery-notice")
            dialog = RecoveryDialog(window.recovery, window)
            dialog.show()
            app.processEvents()
            smoke.shot(dialog, "recovery-dialog")
            from . import theme
            theme.apply(app, dark=True)  # Contrast in the dark theme too.
            app.processEvents()
            smoke.shot(dialog, "recovery-dialog-dark")
            smoke.shot(window, "recovery-notice-dark")
            theme.apply(app, dark=False)
            app.processEvents()
            rows = dialog.list.topLevelItemCount()
            self.step(case, "dialog lists both copies", rows == 2, f"{rows} rows")
            saved_key = next(copy["key"] for copy in info["copies"] if copy["title"].endswith(".alab"))
            other_key = next(copy["key"] for copy in info["copies"] if copy["key"] != saved_key)
            for index in range(rows):
                item = dialog.list.topLevelItem(index)
                item.setSelected(item.data(0, 0x0100) == saved_key)
            dialog.accept()
            window.recovery.recover(dialog.chosen)
            dialog.deleteLater()
            wait_until(app, lambda: window.job is None, 30)
            project = window.project
            recovered = (project.recovery_key == saved_key and project.dirty and project.path is None
                         and float(project.tables[TABLE].raw.iloc[4, 1]) == 15.0
                         and (1, 1) in project.tables[TABLE].excluded
                         and next(iter(project.info_sheets.values())).notes.startswith("Nota confermata")
                         and len(project.layouts) == 1)
            self.step(case, "recovered copy holds the confirmed changes", recovered, project.title)
            smoke.shot(window, "recovery-recovered")
            offered = [record["session_key"] for record in window.recovery.offered()[0]]
            self.step(case, "the other copy is left for later", offered == [other_key])

            def choose():
                modal = QApplication.activeModalWidget()
                if isinstance(modal, RecoveryDialog):
                    smoke.shot(modal, "recovery-dialog-later")
                    modal.list.selectAll()
                    modal.accept()
                else:
                    QTimer.singleShot(50, choose)

            QTimer.singleShot(50, choose)
            window.actions["recover"].trigger()  # File → Recover projects…
            wait_until(app, lambda: window.job is None, 30)
            self.step(case, "reopened from the File command", window.project.recovery_key == other_key
                      and len(window.sessions) == 2)
            window.switch_project(window.sessions[0])
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                window.save()
            window.recovery.wait()
            self.step(case, "Save as cancelled keeps the copy", store.record(saved_key) is not None)
            target = data / "misure-recuperate.alab"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                saved = window.save()
            window.recovery.wait()
            try:
                store.record(saved_key)
                gone = False
            except FileNotFoundError:
                gone = True
            self.step(case, "Save as removes the copy", saved and gone and target.exists())
            info["saved_sha256"] = digest(target.read_bytes()) if target.exists() else None
            info["original_sha256_after"] = digest(original.read_bytes())
            self.step(case, "original bytes unchanged", info["original_sha256_after"] == info["original_sha256_before"])
            self.step(case, "no error dialogs", window.errors == [], "; ".join(window.errors))
            smoke.shot(window, "recovery-saved")
        finally:
            self.close(window)
        return info

    def case_damaged(self, smoke, language, work):
        from PySide6.QtWidgets import QApplication
        from .recovery import RecoveryDialog

        case = f"{language}-damaged"
        smoke.language = language
        profile, data, info = self.crash(case, language, work)
        original = data / "misure-salvate.alab"
        changed = original.read_bytes().replace(b"SINT-01", b"SINT-99")
        original.write_bytes(changed)  # Changed outside Trama after the crash.
        root = profile / ("TramaStat" if sys.platform.startswith("win") else "tramastat") / "recovery"
        saved_key = next(copy["key"] for copy in info["copies"] if copy["title"].endswith(".alab"))
        other_key = next(copy["key"] for copy in info["copies"] if copy["key"] != saved_key)
        reference = root / f"{other_key}.json"
        reference.write_text(reference.read_text(encoding="utf-8")[:-30], encoding="utf-8")  # Damaged index.
        app = QApplication.instance()
        window = self.window(profile, language)
        if smoke.size:
            window.resize(*smoke.size)
        window.show()
        try:
            wait_until(app, lambda: window.recovery.notice is not None, 20)
            dialog = RecoveryDialog(window.recovery, window)
            dialog.show()
            app.processEvents()
            smoke.shot(dialog, "recovery-dialog-damaged")
            state = dialog.list.topLevelItem(0).data(2, 0x0100) if dialog.list.topLevelItemCount() else None
            self.step(case, "changed original shown with a warning",
                      dialog.list.topLevelItemCount() == 1 and state == "changed" and dialog.warning.isVisible())
            self.step(case, "damaged copy listed apart", dialog.damaged.isVisible() and len(dialog.problems) == 1)
            dialog.accept()
            window.recovery.recover(dialog.chosen)
            dialog.deleteLater()
            wait_until(app, lambda: window.job is None, 30)
            self.step(case, "the good copy still opens", window.project.recovery_key == saved_key
                      and float(window.project.tables[TABLE].raw.iloc[4, 1]) == 15.0)
            self.step(case, "changed original untouched", original.read_bytes() == changed)
            smoke.shot(window, "recovery-damaged-recovered")
        finally:
            self.close(window)
        return info

    @staticmethod
    def close(window):
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        for session in window.sessions:
            session.project.dirty = False
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            window.close()
        window.deleteLater()

    def run(self, size):
        from PySide6.QtWidgets import QApplication
        from . import theme
        from .smoke import Smoke

        app = QApplication.instance() or QApplication(["trama-recovery-drill"])
        theme.load_fonts()
        theme.apply(app)
        smoke = Smoke(self.folder)
        smoke.size = size
        saved_env = {key: os.environ.get(key) for key in ("APPDATA", "XDG_CONFIG_HOME")}
        work_root = Path(tempfile.mkdtemp(prefix="trama-recovery-drill-"))
        try:
            for language in ("en", "it"):
                for name, case in (("recover", self.case_recover), ("damaged", self.case_damaged)):
                    work = work_root / f"{language}-{name}"
                    try:
                        info = case(smoke, language, work)
                        self.report["cases"].append({"case": f"{language}-{name}", **info})
                    except Exception:
                        self.step(f"{language}-{name}", "case ran", False, traceback.format_exc(limit=4))
        finally:
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(work_root, ignore_errors=True)
        for problem in smoke.problems:
            self.step("layout", "screenshot check", False, problem)
        screen = app.primaryScreen()
        self.report["screen"] = {"size": [screen.size().width(), screen.size().height()],
                                 "dpi": screen.logicalDotsPerInch(), "ratio": screen.devicePixelRatio()}
        self.report["window"] = list(size) if size else "default"
        self.report["steps"] = self.steps
        status = "PASS" if self.steps and all(step["status"] == "PASS" for step in self.steps) else "FAIL"
        self.report["status"] = status
        (self.folder / "report.json").write_text(json.dumps(self.report, indent=2, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
        (self.folder / "drill.log").write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--child"]:
        return child(argv[1])
    if not argv:
        print("Usage: python -m trama_qt.recovery_drill FOLDER [--size WIDTHxHEIGHT]")
        return 2
    size = None  # As the window sizes itself on the screen (like the application).
    if "--size" in argv:
        width, height = argv[argv.index("--size") + 1].lower().split("x")
        size = (int(width), int(height))
    status = Drill(argv[0]).run(size)
    print(f"Recovery drill: {status} ({argv[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
