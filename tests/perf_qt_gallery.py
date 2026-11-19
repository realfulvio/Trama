"""Measure the Qt gallery on a project with many graphs: ``python tests/perf_qt_gallery.py --mode lazy|eager``.

``lazy`` opens the real gallery, waits for the visible previews and then drags the scroll bar through every
card. ``eager`` draws a preview of every card up front, with the same renderer and the same data, which is what
a gallery without a visible-cards queue would do. Run each mode in its own process so that the peak memory of
one does not hide the other. Offscreen by default; the result is printed and, with ``--json``, saved.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def rss_mb():
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6


def peak_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3  # Linux reports kilobytes.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("lazy", "eager"), required=True)
    parser.add_argument("--cards", type=int, default=120)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    from PySide6.QtCore import QElapsedTimer, QTimer
    from test_qt_gallery import _app, many_graphs
    app = _app()
    started = time.perf_counter()
    project = many_graphs(args.cards)
    build = time.perf_counter() - started
    from trama_qt.gallery import PREVIEW, GalleryPage
    from trama_qt.gallery_catalog import catalog
    from trama_qt import gallery_thumbs
    base_rss, base_peak = rss_mb(), peak_mb()
    result = {"mode": args.mode, "cards": len(catalog(project)), "build_seconds": round(build, 2),
              "rss_after_build_mb": round(base_rss, 1)}

    if args.mode == "eager":
        entries = [entry for entry in catalog(project) if entry.previewable]
        ratio = app.primaryScreen().devicePixelRatio()  # The size the real gallery draws at on this screen.
        started = time.perf_counter()
        thumbs = []
        for entry in entries:
            steps = gallery_thumbs.render(entry, project, (round(PREVIEW.width() * ratio), round(PREVIEW.height() * ratio)))
            try:
                while True:
                    next(steps)
            except StopIteration as done:
                thumbs.append(gallery_thumbs.QPixmap.fromImage(done.value))
        result.update(previews_drawn=len(thumbs), draw_seconds=round(time.perf_counter() - started, 2),
                      preview_mb=round(sum(p.width() * p.height() * 4 for p in thumbs) / 1e6, 1))
    else:
        gaps, clock = [], QElapsedTimer()
        beat = QTimer()
        beat.setInterval(5)
        clock.start()
        last = [clock.elapsed()]

        def tick():
            now = clock.elapsed()
            gaps.append(now - last[0])
            last[0] = now

        beat.timeout.connect(tick)
        beat.start()
        page = GalleryPage(lambda: project, lambda: False, {"kind": None, "text": ""})
        page.resize(1100, 700)
        started = time.perf_counter()
        page.show()

        def settle(timeout=120):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                for _ in range(10):
                    app.processEvents()
                    time.sleep(0.005)
                shown = [entry for entry in page.visible_entries() if entry.previewable]
                if (page.service.task is None and not page.service.queue and not page._scan_timer.isActive()
                        and all(page.service.cache.get(entry) is not None for entry in shown)):
                    return len(shown)
            raise SystemExit("previews were not drawn")

        visible = settle()
        result.update(visible_cards=visible, first_screen_seconds=round(time.perf_counter() - started, 2),
                      drawn_first_screen=page.service.drawn)
        bar = page.view.verticalScrollBar()
        started = time.perf_counter()
        for position in range(0, bar.maximum() + 1, max(1, bar.maximum() // 60)):
            bar.setValue(position)
            app.processEvents()
        bar.setValue(bar.maximum())
        settle()
        gaps.sort()
        result.update(previews_drawn=page.service.drawn, scroll_seconds=round(time.perf_counter() - started, 2),
                      cache_entries=len(page.service.cache), cache_limit=page.service.cache.limit,
                      preview_mb=round(page.service.cache.bytes / 1e6, 1),
                      loop_gap_ms={"p50": gaps[len(gaps) // 2], "p95": gaps[int(len(gaps) * .95)],
                                   "max": gaps[-1]})
        page.dispose()
        result["cache_entries_after_close"] = len(page.service.cache)
    result.update(rss_end_mb=round(rss_mb(), 1), peak_rss_mb=round(peak_mb(), 1),
                  peak_growth_mb=round(peak_mb() - base_peak, 1))
    text = json.dumps(result, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
