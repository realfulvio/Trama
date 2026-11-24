"""Entry point for the desktop application and the Windows portable."""

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    from trama_qt.app import main
    raise SystemExit(main())
