"""Start Trama on Qt: the splash first, then language, fonts, theme and the main window."""
import os
from pathlib import Path
import sys

# The worksheet and graphs are drawn with the Qt backend; set before pyplot can be imported anywhere.
os.environ.setdefault("MPLBACKEND", "QtAgg")


def _file_argument(argv):
    for argument in argv[1:]:
        if not argument.startswith("--"):
            return argument
    return None


def _option(argv, name):
    """Return the value after a named option, or ``None``."""
    if name in argv and argv.index(name) + 1 < len(argv):
        return argv[argv.index(name) + 1]
    return None


def splash_logo():
    """The splash image, found without importing ``theme``.

    ``theme`` imports ``analisi`` and with it NumPy, pandas, SciPy and matplotlib: two to three seconds, seven
    on a first launch. The splash is there to cover that wait, so its image is located here with the rule of
    ``theme.asset_root`` (tests/test_qt_splash_first.py keeps the two together).
    """
    bundle = getattr(sys, "_MEIPASS", None)
    roots = [Path(__file__).resolve().parent.parent / "assets"]
    if bundle:
        roots.insert(0, Path(bundle) / "assets")
    return next((root for root in roots if root.is_dir()), roots[-1]) / "brand" / "trama-wordmark-light.png"


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    scenario = _option(argv, "--scenario")
    only = _option(argv, "--only")
    if "--smoke" in argv and (scenario is not None or only is not None):
        # A dedicated smoke never reads the user's preferences.
        folder = _option(argv, "--smoke")
        if folder:
            preferences = os.path.join(os.path.abspath(folder), "preferences")
            os.makedirs(preferences, exist_ok=True)
            os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = preferences
            os.environ.setdefault("TRAMA_THEME", "light")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Trama")
    app.setOrganizationName("TramaStat")

    splash = None
    logo = QPixmap(str(splash_logo()))
    if not logo.isNull():
        ratio = app.primaryScreen().devicePixelRatio() if app.primaryScreen() else 1.0
        logo = logo.scaledToWidth(int(420 * ratio), Qt.TransformationMode.SmoothTransformation)
        logo.setDevicePixelRatio(ratio)
        splash = QSplashScreen(logo)
        splash.show()
        app.processEvents()

    from . import theme  # the scientific stack loads here, behind the splash
    from analisi import parallel
    from analisi.i18n import active_language, config_path, load_language, set_language
    path = config_path()
    set_language(load_language(path))
    parallel.configure(parallel.load_setting(path))
    theme.install_qt_translations(app, active_language())
    import matplotlib
    matplotlib.use("QtAgg")
    theme.load_fonts()
    theme.STATE["mode"] = theme.saved_mode()  # Light, dark or as the system (View tab).
    theme.apply(app)
    app.setWindowIcon(QIcon(str(theme.ASSETS / "trama.png")))

    if "--smoke" in argv:  # python -m trama_qt --smoke FOLDER: desktop acceptance, see trama_qt/smoke.py.
        if splash is not None:
            splash.close()
        position = argv.index("--smoke") + 1
        if position >= len(argv):
            print("Usage: python -m trama_qt --smoke FOLDER [--scenario NAME | --only NAME]")
            return 2
        folder = argv[position]
        if only == "qt-analysis-templates":
            from .templates_smoke import run_dedicated as run  # Templates only: EN/IT, light and dark.
            status = run(folder)
        elif only == "qt-pade-calibration":
            from .pade_calibration_smoke import PadeSmoke
            status = "PASS" if PadeSmoke(folder).run() == 0 else "FAIL"
        elif only == "qt-yuen-trimmed-means":
            from .yuen_smoke import YuenSmoke
            status = "PASS" if YuenSmoke(folder).run() == 0 else "FAIL"
        elif only == "qt-brunner-munzel":
            from .brunner_munzel_smoke import BrunnerMunzelSmoke
            status = "PASS" if BrunnerMunzelSmoke(folder).run() == 0 else "FAIL"
        elif only == "qt-mood-median":
            from .mood_median_smoke import MoodMedianSmoke
            status = "PASS" if MoodMedianSmoke(folder).run() == 0 else "FAIL"
        elif only == "qt-rank-graphs":
            from .rank_graphs_smoke import RankGraphsSmoke
            status = "PASS" if RankGraphsSmoke(folder).run() == 0 else "FAIL"
        elif only == "qt-linked-axes":
            from .linked_axes_smoke import run
            status = run(folder, dark=os.environ.get("TRAMA_THEME") == "dark")
        elif only == "qt-survival-bands":
            from .survival_bands_smoke import run
            status = run(folder, dark=os.environ.get("TRAMA_THEME") == "dark")
        elif only == "qt-ecdf-graph":
            from .ecdf_graph_smoke import run
            status = run(folder, dark=os.environ.get("TRAMA_THEME") == "dark")
        elif only == "qt-interaction-plot":
            from .interaction_plot_smoke import run
            status = run(folder, dark=os.environ.get("TRAMA_THEME") == "dark")
        elif only == "qt-raincloud-plot":
            from .raincloud_plot_smoke import run
            status = run(folder, dark=os.environ.get("TRAMA_THEME") == "dark")
        elif only == "qt-mcnemar-power":
            from .mcnemar_power_smoke import run  # Paired-proportion power only: EN/IT, light and dark.
            status = run(folder)
        elif only == "qt-startup":
            from .table_setup_smoke import run
            status = run(folder)
        elif only == "qt-point-style":
            from .point_style_smoke import run_dedicated
            status = run_dedicated(folder)
        elif only == "qt-observation-labels":
            from .observation_labels_smoke import run_dedicated as observation_labels
            status = observation_labels(folder)
        elif only == "qt-rows-series":
            from .rows_series_smoke import main as rows_smoke
            language = _option(argv, "--lang") or "it"
            mode = _option(argv, "--theme") or "light"
            status = "PASS" if rows_smoke([folder, "--lang", language, "--theme", mode]) == 0 else "FAIL"
        elif only == "qt-sort-rows":
            from .sort_rows_smoke import main as sort_smoke
            language = _option(argv, "--lang") or "it"
            mode = _option(argv, "--theme") or "light"
            status = "PASS" if sort_smoke([folder, "--lang", language, "--theme", mode]) == 0 else "FAIL"
        elif only == "qt-deming-paired":
            from .deming_paired_smoke import main as deming_smoke
            language = _option(argv, "--lang") or "it"
            mode = _option(argv, "--theme") or "light"
            status = "PASS" if deming_smoke([folder, "--languages", language, "--themes", mode]) == 0 else "FAIL"
        elif only == "qt-summary-twoway":
            from .summary_twoway_smoke import main as summary_smoke
            status = "PASS" if summary_smoke([folder]) == 0 else "FAIL"
        elif only == "qt-text-style":
            from .text_style_smoke import run_dedicated as text_style
            status = text_style(folder)
        elif only == "qt-linked-tables":
            from .linked_table_smoke import run_dedicated as linked_tables
            status = linked_tables(folder)
        elif only == "qt-anova-marginal-means":
            from .marginal_means_smoke import main as means_smoke
            status = "PASS" if means_smoke([folder]) == 0 else "FAIL"
        elif only == "qt-category-levels":
            from .category_levels_smoke import run_smoke
            screen = app.primaryScreen().availableGeometry()
            sizes = tuple(dict.fromkeys((min(width, screen.width()), min(height, screen.height()))
                                        for width, height in ((1024, 768), (1600, 1000))))
            status = "PASS" if run_smoke(folder, sizes=sizes) == 0 else "FAIL"
        elif only == "qt-source-link":
            from .source_link_smoke import run_dedicated as source_link  # EN/IT, light/dark, 1024×768 and 1600×1000.
            status = source_link(folder)
        elif only == "qt-pareto-plot":
            from .pareto_plot_smoke import run
            status = run(folder, dark=os.environ.get("TRAMA_THEME") == "dark")
        else:
            from .smoke import SCENARIOS, run
            if scenario is not None and scenario not in SCENARIOS:
                print(f"Unknown scenario {scenario}. Choose: {', '.join(SCENARIOS)}")
                return 2
            status = run(folder, scenario=scenario)
        smoke_name = only or scenario
        print(f"Qt smoke: {status} ({folder}{f', {smoke_name}' if smoke_name else ''})")
        return 0 if status == "PASS" else 1

    from .recovery import RecoveryController
    from .window import MainWindow
    window = MainWindow(recovery=RecoveryController.for_profile())  # Recovery copies in the user's profile.
    window.show()
    theme.keep_on_screen(window)
    if splash is not None:
        splash.finish(window)
    filename = _file_argument(argv)
    try:
        if filename:
            window.open_path(filename)
        return app.exec()
    finally:
        parallel.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
