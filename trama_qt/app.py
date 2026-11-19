"""Start Trama on Qt: language, fonts, theme, a short splash and the main window."""
import os
import sys

# The worksheet and graphs are drawn with the Qt backend; set before pyplot can be imported anywhere.
os.environ.setdefault("MPLBACKEND", "QtAgg")


def _file_argument(argv):
    for argument in argv[1:]:
        if not argument.startswith("--"):
            return argument
    return None


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Trama")
    app.setOrganizationName("TramaStat")

    from . import theme
    splash = None
    logo = QPixmap(str(theme.ASSETS / "brand" / "trama-wordmark-light.png"))
    if not logo.isNull():
        ratio = app.primaryScreen().devicePixelRatio() if app.primaryScreen() else 1.0
        logo = logo.scaledToWidth(int(420 * ratio), Qt.TransformationMode.SmoothTransformation)
        logo.setDevicePixelRatio(ratio)
        splash = QSplashScreen(logo)
        splash.show()
        app.processEvents()

    from analisi.i18n import config_path, load_language, set_language
    set_language(load_language(config_path()))
    import matplotlib
    matplotlib.use("QtAgg")
    theme.load_fonts()
    theme.apply(app)
    app.setWindowIcon(QIcon(str(theme.ASSETS / "trama.png")))

    if "--smoke" in argv:  # python -m trama_qt --smoke FOLDER: desktop acceptance, see trama_qt/smoke.py.
        if splash is not None:
            splash.close()
        position = argv.index("--smoke") + 1
        if position >= len(argv):
            print("Usage: python -m trama_qt --smoke FOLDER")
            return 2
        from .smoke import run
        status = run(argv[position])
        print(f"Qt smoke: {status} ({argv[position]})")
        return 0 if status == "PASS" else 1

    from .window import MainWindow
    window = MainWindow()
    window.show()
    theme.keep_on_screen(window)
    if splash is not None:
        splash.finish(window)
    path = _file_argument(argv)
    if path:
        window.open_path(path)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
