"""Editable data grid with frozen headings and rectangular cell selection."""
from bisect import bisect_right
from itertools import accumulate
import re
import tkinter as tk
from tkinter import font, ttk

import pandas as pd

from . import ui_theme


_SUBCOLUMN = re.compile(
    r"(.*?) \[([1-9]\d*|Mean|SD|SEM|CV%|N|Center|Plus|Minus|Upper|Lower|Value|Error)\]( \(\d+\))?"
)
_HEADER_TITLE = "#ffffff"
_ROW_TITLE = "#fbfcfd"


def column_label(index):
    label = ""
    while index >= 0:
        index, letter = divmod(index, 26)
        label = chr(65 + letter) + label
        index -= 1
    return label


def _heading_bands(frame, names, source_columns, table_format):
    """Map each visible column to its display band and optional subcolumn role."""
    kind = (table_format or "").casefold()
    xy = kind == "xy" or kind.startswith("xy ")
    if kind == "column":
        group = 0
        bands = []
        for index, name in enumerate(names):
            if name.casefold() in {"row title", "row titles"}:
                label = "Row titles"
            elif index < source_columns:
                label = f"Group {column_label(group)}"
                group += 1
            else:
                label = column_label(index)
            bands.append((index, index + 1, label, name))
        return bands, []
    if not (xy or kind in {"grouped", "twoway", "two way", "nested"}):
        return [(col, col + 1, column_label(col), name) for col, name in enumerate(names)], []

    columns = frame.attrs.get("prism_columns", {})
    x_names = set(columns.get(frame.attrs.get("prism_x"), []))
    y_groups = {name: key for key in frame.attrs.get("prism_y", [])
                for name in columns.get(key, [])}
    stored = frame.attrs.get("worksheet_roles")
    if stored is not None:
        x_names = set(stored["x"])
        y_groups = {name: index for index, group in enumerate(stored["y"]) for name in group}
    row_title = source_columns and (names[0].casefold() in {"row title", "row titles"}
                                   or (y_groups and names[0] not in y_groups and names[0] not in x_names))
    first_data = int(bool(row_title))
    subcolumns = [_SUBCOLUMN.fullmatch(name) for name in names[:source_columns]]
    if xy and stored is None and "prism_x" not in frame.attrs and first_data + 1 < source_columns:
        first, second = subcolumns[first_data:first_data + 2]
        first_name = names[first_data]
        if second and second[2] == "Error" and second[1] == (first[1] if first else first_name):
            x_names.update(names[first_data:first_data + 2])
        elif not (first and second and first[1] == second[1] and first[3] == second[3]):
            # Adjacent replicates can start an XY sheet with implicit X values.
            x_names.add(first_name)

    bands, roles, group = [], [], 0
    start = 0
    while start < len(names):
        stop = start + 1
        title, band, role = names[start], "", ""
        if start >= source_columns:
            band, role = column_label(start), "Formula"
        elif start < first_data:
            band = "Row titles"
        else:
            is_x = xy and title in x_names
            match = subcolumns[start]
            if is_x:
                while stop < source_columns and names[stop] in x_names:
                    stop += 1
                band, role = "X", "X"
            else:
                if kind == "nested" and title in y_groups:
                    while stop < source_columns and y_groups.get(names[stop]) == y_groups[title]:
                        stop += 1
                else:
                    while (match and stop < source_columns and (next_match := subcolumns[stop])
                           and next_match[1] == match[1] and next_match[3] == match[3]
                           and y_groups.get(names[stop]) == y_groups.get(names[start])
                           and names[stop] not in x_names):
                        stop += 1
                band, role = f"Group {column_label(group)}", "Y" if xy else ""
                group += 1
            if stop - start > 1:
                if match:
                    title = match[1] + (match[3] or "")
                for subcolumn in subcolumns[start:stop]:
                    label = subcolumn[2] if subcolumn else role
                    if xy and not is_x and label.isdigit():
                        label = f"Y{label}"
                    roles.append(label)
        if stop == start + 1:
            roles.append(role)
        bands.extend([(start, stop, band, title)] * (stop - start))
        start = stop
    return bands, roles


class DataGrid(ttk.Frame):
    def __init__(self, parent, frame, edit, copy_cells, paste_cells, display, *, excluded, source_columns,
                 table_format=None, read_only_columns=(), address_widget=None):
        super().__init__(parent)
        self.frame = frame
        self.edit = edit
        self.display = display
        self.excluded = excluded
        self.source_columns = source_columns
        self.read_only_columns = frozenset(read_only_columns)
        self.rows = self.minimum_rows = max(20, len(frame) + 1)
        self.columns = len(frame.columns)
        self.cursor = ""
        self.format_name = {"xy": "XY", "column": "Col", "grouped": "Grp",
                            "survival": "Surv", "contingency": "Cnt", "nested": "Nest"}.get((table_format or "").split(" ")[0].casefold(), "")
        self.anchor = self.head = (0, 0)
        self.editor = None
        self.redraw = None
        self.drag_job = None
        self.drag_position = None

        family = ui_theme.family()
        self.font = font.Font(self, family=family, size=10)
        self.excluded_font = font.Font(self, family=family, size=10, slant="italic")
        self.heading_font = font.Font(self, family=family, size=10)
        self.label_font = font.Font(self, family=family, size=9)
        self.label_bold = font.Font(self, family=family, size=9, weight="bold")
        self.group_font = font.Font(self, family=family, size=9, weight="bold")
        self.stripe = ui_theme.px(3)
        self.mark = ui_theme.px(6)
        self.row_height = self.font.metrics("linespace") + (7 if ui_theme.is_modern() else 4)
        self.band_height = self.label_font.metrics("linespace") + 5
        self.gutter = max(36, self.label_font.measure(str(self.rows)) + 16)
        names = [str(name) if col < source_columns else f"ƒx   {name}"
                 for col, name in enumerate(frame.columns)]
        self.bands, self.roles = _heading_bands(frame, names, source_columns, table_format)
        self.row_titles = bool(self.bands and self.bands[0][2] == "Row titles")
        self.header_height = self.band_height + self.row_height
        if self.roles:
            self.header_height += self.band_height
        widths = []
        for first, stop, band, title in self.bands:
            span = stop - first
            title_width = (self.heading_font.measure(title) + 16 + span - 1) // span
            band_width = (self.group_font.measure(band) + 14 + span - 1) // span
            minimum = 73 if span > 1 else 92 if self.roles else 105
            if self.row_titles and first == 0:
                minimum = 76
            widths.append(max(minimum, min(248, max(title_width, band_width))))
        self.edges = list(accumulate(widths, initial=self.gutter))
        self.numeric = [pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes]

        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0, takefocus=True,
                                yscrollincrement=self.row_height)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        xbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=lambda *args: self.scrolled(xbar, *args),
                              yscrollcommand=lambda *args: self.scrolled(ybar, *args))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.address = address_widget
        if self.address is None:
            self.address = ttk.Label(self, foreground=ui_theme.MUTED, font=self.label_font)
            self.address.grid(row=2, column=0, sticky="w", padx=4, pady=2)

        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<ButtonPress-1>", self.click)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end_drag)
        self.canvas.bind("<Double-Button-1>", self.start_edit)
        self.canvas.bind("<F2>", self.start_edit)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", lambda _: self.wheel_rows(-3))
        self.canvas.bind("<Button-5>", lambda _: self.wheel_rows(3))
        self.canvas.bind("<Control-c>", lambda _: copy_cells())
        self.canvas.bind("<Control-v>", lambda _: paste_cells())
        self.canvas.bind("<Control-a>", lambda _: self.select_all())
        self.canvas.bind("<Shift-space>", lambda _: self.select_rows(self.selection[0], self.selection[2]))
        self.canvas.bind("<Control-space>", lambda _: self.select_columns(self.selection[1], self.selection[3]))
        self.canvas.bind("<Motion>", self.update_cursor)
        for key, delta in {"Up": (-1, 0), "Down": (1, 0), "Left": (0, -1), "Right": (0, 1)}.items():
            self.canvas.bind(f"<{key}>", lambda _, step=delta: self.move(*step))
            self.canvas.bind(f"<Shift-{key}>", lambda _, step=delta: self.move(*step, extend=True))
        self.canvas.bind("<Tab>", lambda _: self.move(0, 1))
        self.canvas.bind("<Shift-Tab>", lambda _: self.move(0, -1))
        self.canvas.bind("<ISO_Left_Tab>", lambda _: self.move(0, -1))
        self.canvas.bind("<Return>", lambda _: self.move(1, 0))

    @property
    def active_cell(self):
        return self.anchor

    @active_cell.setter
    def active_cell(self, cell):
        self.select(cell)

    @property
    def selection(self):
        first_row, first_column = self.anchor
        last_row, last_column = self.head
        return (min(first_row, last_row), min(first_column, last_column),
                max(first_row, last_row), max(first_column, last_column))

    def view_state(self):
        return self.anchor, self.head, self.canvas.canvasx(0), self.canvas.canvasy(0)

    def restore(self, state, *, focus=False):
        anchor, head, x, y = state
        self.anchor, self.head = self.clamp(*anchor), self.clamp(*head)
        self.canvas.xview_moveto(x / self.extent()[0])
        self.canvas.yview_moveto(y / self.extent()[1])
        if focus:
            self.canvas.focus_set()
        self.queue_draw()

    def extent(self):
        return (max(self.canvas.winfo_width(), self.edges[-1]),
                max(self.canvas.winfo_height(), self.header_height + self.rows * self.row_height))

    def resize(self, _event):
        visible_rows = max(0, self.canvas.winfo_height() - self.header_height)
        self.rows = max(self.minimum_rows, (visible_rows + self.row_height - 1) // self.row_height)
        self.canvas.configure(scrollregion=(0, 0, *self.extent()))
        self.position_editor()
        self.queue_draw()

    def scrolled(self, scrollbar, *fractions):
        scrollbar.set(*fractions)
        self.position_editor()
        self.queue_draw()

    def queue_draw(self):
        if self.redraw is None:
            self.redraw = self.after_idle(self.draw)

    def clip(self, value, width, face):
        value = " ".join(value.splitlines())
        if face.measure(value) <= width:
            return value
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if face.measure(value[:middle] + "…") <= width:
                low = middle
            else:
                high = middle - 1
        return value[:low] + "…"

    def draw(self):
        self.redraw = None
        c = self.canvas
        c.delete("all")
        x, y = c.canvasx(0), c.canvasy(0)
        right, bottom = x + c.winfo_width(), y + c.winfo_height()
        top_row, left_column, bottom_row, right_column = self.selection
        first_row = max(0, int(y) // self.row_height)
        stop_row = min(self.rows, int((bottom - self.header_height) // self.row_height) + 1)
        first_col = max(0, bisect_right(self.edges, x + self.gutter) - 1)
        stop_col = min(self.columns, bisect_right(self.edges, right))

        def box(x1, y1, x2, y2, fill, border=ui_theme.GRID_LINE, width=1):
            c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=border, width=width)

        def label(px, py, value, face, *, anchor="center", color=ui_theme.TEXT):
            c.create_text(px, py, text=value, font=face, fill=color, anchor=anchor)

        # Continue the worksheet ruling into the unused viewport without adding
        # source columns to the analysis model.
        blank_left = self.edges[-1]
        grid_bottom = min(bottom, self.header_height + self.rows * self.row_height)
        if blank_left < right:
            box(blank_left, y + self.header_height, right, grid_bottom, ui_theme.BLANK, ui_theme.BLANK_LINE)
            for edge in range(blank_left + 96, int(right), 96):
                c.create_line(edge, y + self.header_height, edge, grid_bottom, fill=ui_theme.BLANK_LINE)
            for row in range(first_row, stop_row):
                line = self.header_height + row * self.row_height
                c.create_line(blank_left, line, right, line, fill=ui_theme.BLANK_LINE)

        for row in range(first_row, stop_row):
            for col in range(first_col, stop_col):
                x1, y1, x2, y2 = self.cell_box(row, col)
                active = (row, col) == self.anchor
                selected = top_row <= row <= bottom_row and left_column <= col <= right_column
                locked = col >= self.source_columns or col in self.read_only_columns
                fill = ui_theme.DISABLED_FILL if locked else _ROW_TITLE if self.row_titles and col == 0 else "#ffffff"
                box(x1, y1, x2, y2, ui_theme.SELECTED_CELL if selected and not active else fill)
                value = ""
                if row < len(self.frame):
                    value = self.display(self.frame.iat[row, col])
                    excluded = (row, col) in self.excluded
                    if excluded:
                        value = "* " + value
                    if excluded:
                        # A corner mark and italics, so an excluded cell does not depend on its colour.
                        c.create_polygon(x1 + 1, y1 + 1, x1 + 1 + self.mark, y1 + 1, x1 + 1, y1 + 1 + self.mark,
                                         fill=ui_theme.EXCLUDED, outline="")
                    if value:
                        numeric = self.numeric[col]
                        face = self.excluded_font if excluded else self.font
                        label(x2 - 5 if numeric else x1 + 5, (y1 + y2) / 2,
                              self.clip(value, x2 - x1 - 10, face), face,
                              anchor="e" if numeric else "w", color=ui_theme.EXCLUDED if excluded else ui_theme.TEXT)
                if self.row_titles and col == 0 and not value:
                    label(x1 + 5, (y1 + y2) / 2, "Title", self.label_font, anchor="w", color="#526477")

        col = first_col
        while col < stop_col:
            _, stop, _, _ = self.bands[col]
            edge = self.edges[stop]
            c.create_line(edge, y + self.header_height, edge,
                          min(bottom, self.header_height + self.rows * self.row_height), fill=ui_theme.GROUP_LINE)
            col = stop

        x1, y1, _, _ = self.cell_box(top_row, left_column)
        _, _, x2, y2 = self.cell_box(bottom_row, right_column)
        box(x1, y1, x2, y2, "", ui_theme.ACCENT_STRONG, width=2)
        # The active cell: white ground inside the range and a dark 2 px frame, readable without colour.
        ax1, ay1, ax2, ay2 = self.cell_box(*self.anchor)
        box(ax1 + 1, ay1 + 1, ax2 - 1, ay2 - 1, "", ui_theme.ACTIVE_CELL, width=2)

        band_bottom = y + self.band_height
        title_bottom = band_bottom + self.row_height
        header_bottom = y + self.header_height
        box(x, y, right, header_bottom, ui_theme.HEADING)
        if blank_left < right:
            for edge in range(blank_left, int(right), 96):
                c.create_line(edge, y, edge, header_bottom, fill=ui_theme.BLANK_LINE)
            for line in (band_bottom, title_bottom):
                c.create_line(blank_left, line, right, line, fill=ui_theme.BLANK_LINE)
        col = first_col
        while col < stop_col:
            first, stop, band, title = self.bands[col]
            x1, x2 = self.edges[first], self.edges[stop]
            center = (x1 + x2) / 2
            selected = first <= right_column and stop > left_column
            box(x1, y, x2, band_bottom, ui_theme.SELECTED_HEADING if selected else ui_theme.group_heading_fill(band), ui_theme.GROUP_LINE)
            stripe = self.series_color(band)
            if stripe:
                # The colour a Y group takes in the default graph, as a stripe on its heading.
                c.create_rectangle(x1 + 1, y + 1, x2, y + 1 + self.stripe, fill=stripe, outline="")
            label(center, y + self.band_height / 2 + (self.stripe // 2 if stripe else 0),
                  self.clip(band, x2 - x1 - 12, self.group_font), self.group_font, color=ui_theme.TEXT)
            box(x1, band_bottom, x2, title_bottom, ui_theme.SELECTED_HEADING if selected else _HEADER_TITLE, ui_theme.GROUP_LINE)
            label(center, band_bottom + self.row_height / 2,
                  self.clip(title, x2 - x1 - 12, self.heading_font), self.heading_font)
            col = stop
        if self.roles:
            for col in range(first_col, stop_col):
                x1, x2 = self.edges[col:col + 2]
                selected = left_column <= col <= right_column
                box(x1, title_bottom, x2, header_bottom, ui_theme.SELECTED_HEADING if selected else ui_theme.HEADING, ui_theme.GRID_LINE)
                face = self.label_bold if selected else self.label_font
                label((x1 + x2) / 2, title_bottom + self.band_height / 2,
                      self.clip(self.roles[col], x2 - x1 - 12, face), face, color=ui_theme.TEXT if selected else ui_theme.MUTED)
                if selected:
                    c.create_rectangle(x1 + 1, header_bottom - self.stripe, x2, header_bottom - 1,
                                       fill=ui_theme.ACCENT, outline="")

        box(x, y, x + self.gutter, bottom, ui_theme.HEADING, ui_theme.GROUP_LINE)
        for row in range(first_row, stop_row):
            y1 = self.header_height + row * self.row_height
            chosen = top_row <= row <= bottom_row
            box(x, y1, x + self.gutter, y1 + self.row_height, ui_theme.SELECTED_HEADING if chosen else ui_theme.HEADING)
            if chosen:
                c.create_rectangle(x + self.gutter - self.stripe, y1 + 1, x + self.gutter - 1, y1 + self.row_height,
                                   fill=ui_theme.ACCENT, outline="")
            face = self.label_bold if chosen else self.label_font
            label(x + self.gutter / 2 - 1, y1 + self.row_height / 2, str(row + 1), face,
                  color=ui_theme.TEXT if chosen else ui_theme.MUTED)
        box(x, y, x + self.gutter, header_bottom, ui_theme.HEADING, ui_theme.GROUP_LINE)
        label(x + self.gutter / 2, y + self.band_height / 2, self.format_name, self.group_font, color=ui_theme.MUTED)
        c.create_polygon(x + self.gutter - 5, header_bottom - 5, x + self.gutter - 13, header_bottom - 5,
                         x + self.gutter - 5, header_bottom - 13, fill="#8796a7")

        start = f"{column_label(left_column)}{top_row + 1}"
        end = f"{column_label(right_column)}{bottom_row + 1}"
        self.address.configure(text=start if start == end else
                               f"{start}:{end}   ·   {bottom_row - top_row + 1} × {right_column - left_column + 1}")

    def series_color(self, band):
        """Graph colour of a Y group ("Group A" -> first colour), or None for X, row titles and formulas."""
        if len(band) == 7 and band.startswith("Group ") and band[-1].isalpha():
            return ui_theme.SERIES[(ord(band[-1]) - 65) % len(ui_theme.SERIES)]
        return None

    def cell_box(self, row, col):
        y = self.header_height + row * self.row_height
        return self.edges[col], y, self.edges[col + 1], y + self.row_height

    def clamp(self, row, col):
        return min(max(0, row), self.rows - 1), min(max(0, col), self.columns - 1)

    def cell_at(self, x, y):
        row = int((self.canvas.canvasy(y) - self.header_height) // self.row_height)
        col = bisect_right(self.edges, self.canvas.canvasx(x)) - 1
        return row, col

    def select(self, cell, *, extend=False, reveal=False):
        self.head = self.clamp(*cell)
        if not extend:
            self.anchor = self.head
        if reveal:
            self.reveal(self.head)
        self.queue_draw()

    def select_block(self, top, left, bottom, right):
        self.anchor = top, left
        self.select((bottom, right), extend=True)
        self.canvas.focus_set()

    def reveal(self, cell):
        c = self.canvas
        x1, y1, x2, y2 = self.cell_box(*cell)
        x, y = c.canvasx(0), c.canvasy(0)
        total_width, total_height = self.extent()
        if x1 < x + self.gutter or x2 - x1 >= c.winfo_width() - self.gutter:
            c.xview_moveto((x1 - self.gutter) / total_width)
        elif x2 > x + c.winfo_width():
            c.xview_moveto((x2 - c.winfo_width() + 1) / total_width)
        if y1 < y + self.header_height or self.row_height >= c.winfo_height() - self.header_height:
            c.yview_moveto((y1 - self.header_height) / total_height)
        elif y2 > y + c.winfo_height():
            target = y2 - c.winfo_height()
            offset = (target + self.row_height - 1) // self.row_height * self.row_height
            c.yview_moveto(offset / total_height)

    def select_rows(self, first, last):
        self.select_block(first, 0, last, self.columns - 1)
        return "break"

    def select_columns(self, first, last):
        self.select_block(0, first, max(0, len(self.frame) - 1), last)
        return "break"

    def select_all(self):
        return self.select_columns(0, self.columns - 1)

    def update_cursor(self, event):
        row, col = self.cell_at(event.x, event.y)
        row_header = event.x < self.gutter and (event.y < self.header_height or 0 <= row < self.rows)
        column_header = event.y < self.header_height and 0 <= col < self.columns
        cursor = "hand2" if row_header or column_header else ""
        # Setting a cursor makes Tk redisplay the canvas, which redraws the grid: only do it on a change.
        if cursor != self.cursor:
            self.cursor = cursor
            self.canvas.configure(cursor=cursor)

    def click(self, event):
        self.canvas.focus_set()
        row, col = self.cell_at(event.x, event.y)
        if event.x < self.gutter:
            if event.y < self.header_height:
                return self.select_all()
            if 0 <= row < self.rows:
                return self.select_rows(row, row)
        elif event.y < self.header_height:
            if 0 <= col < self.columns:
                if event.y < self.band_height + self.row_height:
                    first, stop, _, _ = self.bands[col]
                    return self.select_columns(first, stop - 1)
                return self.select_columns(col, col)
        elif (row, col) == self.clamp(row, col):
            self.select((row, col), extend=bool(event.state & 0x0001))
            self.drag_position = (event.x, event.y)

    def drag(self, event):
        if self.drag_position is not None:
            self.drag_position = event.x, event.y
            if self.drag_job is None:
                self.extend_drag()

    def extend_drag(self):
        self.drag_job = None
        x, y = self.drag_position
        c = self.canvas
        width, height = c.winfo_width(), c.winfo_height()
        dx = -1 if x < self.gutter else int(x >= width)
        dy = -1 if y < self.header_height else int(y >= height)
        if dx:
            c.xview_scroll(dx, "units")
        if dy:
            c.yview_scroll(dy, "units")
        self.select(self.cell_at(min(max(x, self.gutter), width - 1),
                                 min(max(y, self.header_height), height - 1)), extend=True)
        if dx or dy:
            self.drag_job = self.after(45, self.extend_drag)

    def end_drag(self, _event):
        self.drag_position = None
        if self.drag_job is not None:
            self.after_cancel(self.drag_job)
            self.drag_job = None

    def move(self, rows, columns, extend=False):
        row, col = self.head if extend else self.anchor
        self.select((row + rows, col + columns), extend=extend, reveal=True)
        return "break"

    def wheel(self, event):
        steps = max(1, abs(event.delta) // 120)
        return self.wheel_rows((-3 if event.delta > 0 else 3) * steps)

    def wheel_rows(self, steps):
        self.canvas.yview_scroll(steps, "units")
        return "break"

    def start_edit(self, event):
        if event.type == tk.EventType.ButtonPress:
            if event.x < self.gutter or event.y < self.header_height:
                return "break"
            cell = self.cell_at(event.x, event.y)
            if cell != self.clamp(*cell):
                return "break"
            self.select(cell)
        row, col = self.anchor
        if col >= self.source_columns or col in self.read_only_columns:
            return "break"
        self.end_drag(None)
        self.reveal((row, col))
        self.editor = ttk.Entry(self.canvas)
        if row < len(self.frame):
            value = self.frame.iat[row, col]
            self.editor.insert(0, "" if pd.isna(value) else str(value))
        self.editor.select_range(0, "end")
        self.position_editor()
        if self.editor is None:
            return "break"
        self.editor.focus_set()

        def escape(_event):
            self.cancel_edit()
            self.canvas.focus_set()
            return "break"

        self.editor.bind("<Return>", lambda _: self.commit_edit(focus=True))
        self.editor.bind("<Escape>", escape)
        self.editor.bind("<FocusOut>", lambda _: self.cancel_edit())
        return "break"

    def position_editor(self):
        if self.editor is not None:
            x1, y1, x2, y2 = self.cell_box(*self.anchor)
            x, y = self.canvas.canvasx(0), self.canvas.canvasy(0)
            if x1 < x + self.gutter or y1 < y + self.header_height:
                self.cancel_edit()
                return
            self.editor.place(x=x1 - x, y=y1 - y, width=x2 - x1, height=y2 - y1)

    def commit_edit(self, *, focus=False):
        if self.editor is not None:
            row, column = self.anchor
            value = self.editor.get()
            self.cancel_edit()
            if focus:
                self.canvas.focus_set()
            self.edit(row, column, value)
        return "break"

    def cancel_edit(self):
        if self.editor is not None:
            editor, self.editor = self.editor, None
            editor.destroy()

    def destroy(self):
        self.end_drag(None)
        if self.redraw is not None:
            self.after_cancel(self.redraw)
        super().destroy()
