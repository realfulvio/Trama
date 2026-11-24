"""Print the current Qt sheet and render figures for direct Office insertion."""
from html import escape
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QRectF, QSignalBlocker, QSizeF, Qt
from PySide6.QtGui import (QFont, QGuiApplication, QImage, QKeySequence, QPageLayout, QPageRanges, QPainter,
                           QTextDocument, QTextOption)
from PySide6.QtPrintSupport import QPageSetupDialog, QPrintDialog, QPrintPreviewWidget, QPrinter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QSpinBox, QVBoxLayout
from PIL.ImageQt import ImageQt

from analisi.figure_export import DEFAULT_DPI, MAX_MM, MM, export_figure
from analisi.i18n import tr, ui
from analisi.info import NOTE_BOLD, NOTE_ITALIC, NOTE_UNDERLINE
from analisi.layout_geometry import PT
from analisi.legacy_pdf_preview import pdf_dimensions, render_pdf
from analisi.legacy_zip_layout import imported_paper
from analisi.worksheet_appearance import text_on_background

from . import office
from .strings import qt
from .theme import fit_dialog

FIGURE_KINDS = {"graph", "layout", "saved-layout"}
_IMAGE_MAX_SIDE = 5000


class FigureSheet:
    def __init__(self, title, pdf):
        self.title, self.pdf = title, pdf
        self.size = pdf_dimensions(pdf)
        self._image_side, self._image = None, None

    def pages(self, _width, _height):
        return (self.draw,)

    def draw(self, painter, width, height):
        # Fit to the real printable area. Rasterize the common PDF renderer at print resolution
        # so clipping, ink colours and embedded images match the export.
        drawn_width, drawn_height = office.fit_picture(self.size, (width, height))
        side = min(_IMAGE_MAX_SIDE, ceil(max(drawn_width, drawn_height) * DEFAULT_DPI / PT))
        if side != self._image_side:
            self._image = ImageQt(render_pdf(self.pdf, side))
            self._image_side = side
        target = QRectF((width - drawn_width) / 2, (height - drawn_height) / 2, drawn_width, drawn_height)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._image)

    def office_image(self, path):
        # About 300 dpi across a standard widescreen slide or an Office document page.
        render_pdf(self.pdf, 4000).save(path, dpi=(DEFAULT_DPI, DEFAULT_DPI))


def figure_sheet(project, ref):
    kind, key = ref
    with TemporaryDirectory(prefix="trama-output-") as directory:
        path = Path(directory) / "figure.pdf"
        if kind == "layout":
            layout = project.layouts[key]
            title = layout.name
            project.export_layout(layout, path)
        else:
            run = project.runs[key]
            title = project.sheet_title(ref)
            if run.calculation_error:
                raise ValueError(tr("reference.stale_export"))
            figure = run.result.figure if run.result is not None else None
            if figure is None:
                if project.imported_vector_format(run) != "pdf":
                    raise ValueError(qt("qt.not_calculated"))
                project.export_imported_vector(run, path)
            else:
                size = tuple(imported_paper(run) or figure.get_size_inches())
                scale = min(1, MAX_MM / MM / max(size))
                export_figure(figure, path, {"format": "pdf"}, size_inches=tuple(side * scale for side in size))
        return FigureSheet(title, path.read_bytes())


class TextSheet:
    """Paginate document text with Qt's text layout at 72 logical units per inch."""

    def __init__(self, title, html_chunks):
        self.title, self.html_chunks = title, html_chunks
        self._size, self._pages = None, ()
        self._metrics_device = QImage(1, 1, QImage.Format.Format_RGB32)
        points_per_metre = round(PT * 1000 / MM)
        self._metrics_device.setDotsPerMeterX(points_per_metre)
        self._metrics_device.setDotsPerMeterY(points_per_metre)

    def pages(self, width, height):
        if self._size == (width, height):
            return self._pages
        pages = []
        for html in self.html_chunks(width):
            document = QTextDocument()
            document.documentLayout().setPaintDevice(self._metrics_device)
            document.setDocumentMargin(0)
            font = QFont(document.defaultFont())
            font.setPointSize(9)
            document.setDefaultFont(font)
            option = document.defaultTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            document.setDefaultTextOption(option)
            document.setPageSize(QSizeF(width, height))
            document.setHtml(html)
            pages.extend(self._page(document, number) for number in range(document.pageCount()))
        self._size, self._pages = (width, height), pages
        return pages

    @staticmethod
    def _page(document, number):
        def draw(painter, width, height):
            offset = number * height
            painter.translate(0, -offset)
            document.drawContents(painter, QRectF(0, offset, width, height))
        return draw


def _html(value):
    return escape("" if value is None else str(value)).replace("\n", "<br>")


def table_sheet(title, model, *, worksheet=False):
    """Reuse the current table's display roles, without the worksheet's blank editing rows."""
    rows = len(model.frame)
    columns = len(model.frame.columns) if worksheet else model.columnCount()
    display = Qt.ItemDataRole.DisplayRole
    horizontal = Qt.Orientation.Horizontal

    def header(column):
        return qt("qt.print_row") if column == -1 else model.headerData(column, horizontal, display)

    def cell(row, column):
        if column == -1:
            return f'<td align="right">{row + 1}</td>'
        index = model.index(row, column)
        text = _html(model.data(index, display))
        font = model.data(index, Qt.ItemDataRole.FontRole)
        if font is not None and font.strikeOut():
            text = f"<s>{text}</s>"
        alignment = model.data(index, Qt.ItemDataRole.TextAlignmentRole)
        align = ' align="right"' if alignment & Qt.AlignmentFlag.AlignRight else ""
        key = (row, model.frame.columns[column]) if worksheet else (row, column)
        backgrounds = model.dataset.cell_backgrounds if worksheet else model.backgrounds
        colour = backgrounds.get(key)
        style = f' style="background-color:{colour}; color:{text_on_background(colour)}"' if colour else ""
        return f"<td{align}{style}>{text}</td>"

    def html_chunks(width):
        # Long tables continue down the sheet. Wide tables continue in column groups,
        # repeating the row identifier so groups can be read together.
        group_size = max(1, int(width // 90) - 1)
        start, label = (0, -1) if worksheet else (1, 0)
        for group_start in range(start, max(start + 1, columns), group_size):
            group = [label, *range(group_start, min(group_start + group_size, columns))]
            cells = "".join(f'<th width="{100 / len(group):g}%">{_html(header(column))}</th>' for column in group)
            body = ["<tr>" + "".join(cell(row, column) for column in group) + "</tr>"
                    for row in range(rows)]
            yield (f"<h1>{_html(title)}</h1>"
                   '<table width="100%" border="1" cellspacing="0" cellpadding="3">'
                   f"<thead><tr>{cells}</tr></thead><tbody>{''.join(body)}</tbody></table>")

    return TextSheet(title, html_chunks)


def info_sheet(sheet):
    def html_chunks(_width):
        title = f"<h1>{_html(sheet.title)}</h1>"
        linked = f"<p>{_html(tr('interface.linked_to', table=sheet.table))}</p>" if sheet.table else ""
        fields = "".join(f"<p><b>{_html(name)}</b> · {_html(value)}</p>" for name, value in sheet.fields)
        spans, position = [], 0
        for start, end, mask in sheet.note_styles:
            spans.append(_html(sheet.notes[position:start]))
            part = _html(sheet.notes[start:end])
            for flag, tag in ((NOTE_BOLD, "b"), (NOTE_ITALIC, "i"), (NOTE_UNDERLINE, "u")):
                if mask & flag:
                    part = f"<{tag}>{part}</{tag}>"
            spans.append(part)
            position = end
        spans.append(_html(sheet.notes[position:]))
        notes = f"<h2>{_html(ui('Notes'))}</h2><p>{''.join(spans)}</p>" if sheet.notes else ""
        yield title + linked + fields + notes

    return TextSheet(sheet.title, html_chunks)


def _page_size(printer):
    area = printer.pageLayout().paintRect(QPageLayout.Unit.Point)
    if area.isEmpty():
        raise ValueError(qt("qt.print_area"))
    return area.width(), area.height()


def print_pages(printer, sheet, *, preview=False):
    """Paint the same printable pages for a preview, a printer or Qt's PDF output."""
    printer.setFullPage(False)
    width, height = _page_size(printer)
    pages = sheet.pages(width, height)
    if not preview:
        ranges = printer.pageRanges()
        if not ranges.isEmpty():
            pages = [page for number, page in enumerate(pages, 1) if ranges.contains(number)]
        if printer.pageOrder() == QPrinter.PageOrder.LastPageFirst:
            pages = list(reversed(pages))
        if not printer.supportsMultipleCopies():
            copies = max(1, printer.copyCount())
            pages = list(pages) * copies if printer.collateCopies() else [page for page in pages for _ in range(copies)]
    if not pages:
        raise ValueError(qt("qt.print_range"))
    printer.setDocName(sheet.title)
    painter = QPainter()
    if not painter.begin(printer):
        raise OSError(qt("qt.print_begin"))
    try:
        scale = printer.resolution() / PT
        for number, draw in enumerate(pages):
            if number and not printer.newPage():
                raise OSError(qt("qt.print_failed"))
            painter.save()
            try:
                painter.scale(scale, scale)
                painter.setClipRect(QRectF(0, 0, width, height))
                draw(painter, width, height)
            finally:
                painter.restore()
    except Exception:
        if not preview:
            printer.abort()
        raise
    finally:
        finished = painter.end()
    if not finished or (not preview and printer.printerState() in {QPrinter.PrinterState.Error,
                                                                    QPrinter.PrinterState.Aborted}):
        raise OSError(qt("qt.print_failed"))


class PrintPreview(QDialog):
    def __init__(self, parent, printer, sheet, submit, setup):
        super().__init__(parent)
        self.setWindowTitle(f"{qt('qt.print_preview_title')} · {sheet.title}")
        self.preview = QPrintPreviewWidget(printer, self)
        self.preview.paintRequested.connect(self._paint)
        self.preview.previewChanged.connect(self._update_page)
        self.sheet, self.error = sheet, None

        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.setPrefix(f"{qt('qt.print_page')} ")
        self.page.setAccessibleName(qt("qt.print_page"))
        self.page.valueChanged.connect(self.preview.setCurrentPage)
        tools = QHBoxLayout()
        tools.addWidget(self.page)
        for label, tip, handler in (("−", qt("qt.print_zoom_out"), self.preview.zoomOut),
                                    ("+", qt("qt.print_zoom_in"), self.preview.zoomIn),
                                    (qt("qt.fit_entire_page"), qt("qt.fit_entire_page"), self.preview.fitInView)):
            button = QPushButton(label)
            button.setAccessibleName(tip)
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked=False, handler=handler: handler())
            tools.addWidget(button)
        tools.addStretch(1)
        self.setup_button = QPushButton(qt("qt.page_setup"))
        self.setup_button.clicked.connect(lambda: self.preview.updatePreview() if setup(self) else None)
        tools.addWidget(self.setup_button)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        print_button = QPushButton(qt("qt.print_action"))
        print_button.setObjectName("primary")
        print_button.setShortcut(QKeySequence(QKeySequence.StandardKey.Print))
        print_button.clicked.connect(lambda: self.accept() if submit(self.sheet, self) else None)
        buttons.addWidget(print_button)
        close = QPushButton(qt("qt.print_close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(tools)
        layout.addWidget(self.preview, 1)
        layout.addLayout(buttons)
        fit_dialog(self, 900, 760)

    def _paint(self, printer):
        try:
            print_pages(printer, self.sheet, preview=True)
        except (RuntimeError, ValueError, OSError) as error:
            self.error = error
            self.reject()

    def _update_page(self):
        with QSignalBlocker(self.page):
            count = max(1, self.preview.pageCount())
            self.page.setMaximum(count)
            self.page.setSuffix(f" / {count}")
            self.page.setValue(self.preview.currentPage())


class PrintCommands:
    def __init__(self, window):
        self.window = window
        self._printer = None

    @property
    def printer(self):
        if self._printer is None:
            self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        return self._printer

    def _selected_sheet(self):
        window = self.window
        if window.busy() or window.gallery is not None or not window.selected or not window.settle_graph_draft():
            return None
        kind, key = window.selected
        if kind in FIGURE_KINDS:
            return figure_sheet(window.project, window.selected)
        if kind == "data":
            window._commit_sheet_edit()
            if not window.busy() and window.sheet is not None:
                return table_sheet(key, window.sheet.model(), worksheet=True)
            return None
        if kind == "info":
            window.flush_info()
            return info_sheet(window.project.info_sheets[key])
        run = window.project.runs[key]
        if run.calculation_error:
            raise ValueError(tr("reference.stale_export"))
        tabs = window.result_tabs
        if tabs is None or tabs.currentWidget() is None:
            raise ValueError(qt("qt.not_calculated"))
        name = f"{run.name} · {tabs.tabText(tabs.currentIndex())}"
        return table_sheet(name, tabs.currentWidget().model())

    def _submit(self, sheet, parent):
        printer = self.printer
        try:
            if office.ON_WINDOWS:
                printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
                if not printer.isValid() or not printer.printerName():
                    raise ValueError(qt("qt.print_no_printer"))
            dialog = QPrintDialog(printer, parent)
            dialog.setWindowTitle(qt("qt.print_title"))
            page_count = len(sheet.pages(*_page_size(printer)))
            dialog.setMinMax(1, page_count)
            dialog.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, page_count > 1)
            printer.setPageRanges(QPageRanges())
            printer.setPrintRange(QPrinter.PrintRange.AllPages)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            dialog.deleteLater()
            if not accepted:
                return False
            print_pages(printer, sheet)
        except (RuntimeError, ValueError, OSError) as error:
            self.window.error(error)
            return False
        self.window.status(qt("qt.print_sent", name=sheet.title))
        return True

    def print_sheet(self):
        try:
            sheet = self._selected_sheet()
            if sheet is not None:
                self._submit(sheet, self.window)
        except (RuntimeError, ValueError, OSError) as error:
            self.window.error(error)

    def preview(self):
        try:
            sheet = self._selected_sheet()
            if sheet is None:
                return
            dialog = PrintPreview(self.window, self.printer, sheet, self._submit, self.page_setup)
            try:
                dialog.exec()
                if dialog.error is not None:
                    raise dialog.error
            finally:
                dialog.deleteLater()
        except (RuntimeError, ValueError, OSError) as error:
            self.window.error(error)

    def page_setup(self, parent=None):
        printer = self.printer
        if printer.outputFormat() != QPrinter.OutputFormat.NativeFormat:
            printer.setOutputFileName("")
        if not printer.isValid() or not printer.printerName():
            self.window.error(qt("qt.print_no_printer"))
            return False
        dialog = QPageSetupDialog(printer, parent or self.window)
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()

    def send(self, app_name):
        window = self.window
        if not office.ON_WINDOWS:
            window.error(qt("qt.office_windows", app=app_name))
            return
        if not window.selected or window.selected[0] not in FIGURE_KINDS:
            window.error(qt("qt.office_figure"))
            return
        try:
            sheet = self._selected_sheet()
            if sheet is None:
                return
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                with TemporaryDirectory(prefix="trama-office-") as directory:
                    path = Path(directory) / "figure.png"
                    sheet.office_image(path)
                    office.send_picture(app_name, path, sheet.title, sheet.size)
            finally:
                QGuiApplication.restoreOverrideCursor()
        except (RuntimeError, ValueError, OSError) as error:
            window.error(error)
            return
        window.status(qt("qt.office_sent", app=app_name, name=sheet.title))
