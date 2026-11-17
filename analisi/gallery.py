"""A paged preview of sheets in the current project."""

from io import BytesIO
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from . import ui_theme


PREVIEW_SIZE = (248, 116)


def table_thumbnail(frame, display, *, index=False):
    sample = frame.iloc[:4, :4]
    headings = list(map(str, sample.columns))
    rows = [list(map(display, row)) for row in sample.itertuples(index=False, name=None)]
    if index:
        headings.insert(0, "Row")
        for title, row in zip(sample.index, rows, strict=True):
            row.insert(0, str(title))
    image = Image.new("RGB", PREVIEW_SIZE, "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline="#d3e0e9")
    draw.rectangle((1, 1, image.width - 2, 22), fill="#e6eff6")
    width = (image.width - 1) / max(len(headings), 1)
    for row, labels in enumerate([headings, *rows]):
        top = row * 23
        draw.line((0, top, image.width, top), fill="#d3e0e9")
        for column, value in enumerate(labels):
            left = round(column * width)
            draw.line((left, top, left, top + 23), fill="#d3e0e9")
            value = " ".join(value[:96].split())
            while value and draw.textlength(value) > width - 8:
                value = value[:-1]
            draw.text((left + 4, top + 4), value, fill="#244057")
    return image


def figure_thumbnail(figure):
    width, height = figure.get_size_inches()
    dpi = min(96, PREVIEW_SIZE[0] / width, PREVIEW_SIZE[1] / height)
    with BytesIO() as buffer:
        figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        buffer.seek(0)
        with Image.open(buffer) as rendered:
            return image_thumbnail(rendered)


def image_thumbnail(rendered):
    rendered = rendered.copy()
    rendered.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)
    image = Image.new("RGB", PREVIEW_SIZE, "white")
    image.paste(rendered, ((image.width - rendered.width) // 2, (image.height - rendered.height) // 2))
    return image


def empty_thumbnail():
    image = Image.new("RGB", PREVIEW_SIZE, "#edf3f8")
    draw = ImageDraw.Draw(image)
    draw.text((image.width // 2, image.height // 2), "Open sheet to view", fill="#4a637c", anchor="mm")
    return image


class SheetGallery(ttk.Frame):
    def __init__(self, parent, category, entries, preview, open_sheet, close):
        super().__init__(parent, padding=(15, 12))
        self.entries = entries
        self.preview = preview
        self.open_sheet = open_sheet
        self.close = close
        self.columns = 2
        self.page = 0
        self.cards = []
        self.rendered_previews = 0
        self.images = []

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text=f"{category} gallery", style="SheetTitle.TLabel").pack(side="left")
        self.back = ttk.Button(header, text="Back to sheet", command=self.close)
        self.back.pack(side="right")
        self.back.bind("<Escape>", self.dismiss)
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x")
        self.position = ttk.Label(footer)
        self.position.pack(side="left")
        self.next_button = ttk.Button(footer, text="Next page", command=lambda: self.move(1))
        self.next_button.pack(side="right")
        self.previous_button = ttk.Button(footer, text="Previous page", command=lambda: self.move(-1))
        self.previous_button.pack(side="right", padx=(0, 6))
        for button in (self.previous_button, self.next_button):
            button.bind("<Escape>", self.dismiss)
        self.board = ttk.Frame(self)
        self.board.pack(fill="x", pady=8)
        self.bind("<Configure>", self.resize)
        self.render()

    @property
    def page_size(self):
        return self.columns * 2

    def resize(self, event):
        columns = 2 if event.width >= 2 * (PREVIEW_SIZE[0] + 16) + 30 else 1
        if columns != self.columns:
            first = self.page * self.page_size
            focused = self.focus_get() in self.cards
            self.columns = columns
            self.page = first // self.page_size
            self.render()
            if focused:
                self.focus_first()

    def dismiss(self, _event):
        self.close()
        return "break"

    def focus_first(self):
        (self.cards[0] if self.cards else self.back).focus_set()

    def move(self, delta):
        page = self.page + delta
        if 0 <= page * self.page_size < len(self.entries):
            self.page = page
            self.render()
            self.focus_first()

    def render(self):
        for child in self.board.winfo_children():
            child.destroy()
        self.cards.clear()
        self.images.clear()
        self.rendered_previews = 0
        for column in (0, 1):
            self.board.columnconfigure(column, weight=int(column < self.columns), uniform="card")
        start = self.page * self.page_size
        page = self.entries[start:start + self.page_size]
        if not page:
            ttk.Label(self.board, text="This section has no sheets yet.").grid(row=0, column=0, sticky="w", pady=12)
        for offset, (name, ref) in enumerate(page):
            try:
                preview = self.preview(ref)
            except (ValueError, RuntimeError, OSError):
                preview = None
            self.rendered_previews += preview is not None
            image = ImageTk.PhotoImage(preview if preview is not None else empty_thumbnail(), master=self)
            self.images.append(image)
            card = tk.Button(self.board, image=image, text=name, compound="top", wraplength=PREVIEW_SIZE[0],
                             command=lambda item=ref: self.open_sheet(item), font=ui_theme.font(9),
                             height=146, bg="#ffffff", fg="#17334d", activebackground="#e6f1fb",
                             activeforeground="#17334d", relief="flat", overrelief="solid", borderwidth=1,
                             highlightthickness=1, highlightbackground="#cbdce9", highlightcolor="#28659b")
            card.grid(row=offset // self.columns, column=offset % self.columns, sticky="ew", padx=4, pady=4)
            card.bind("<Return>", lambda event: event.widget.invoke())
            card.bind("<Escape>", self.dismiss)
            self.cards.append(card)
        total = len(self.entries)
        self.position.configure(text=f"Sheets {start + 1}–{start + len(page)} of {total}" if total else "No sheets")
        self.previous_button.state(["!disabled" if start else "disabled"])
        self.next_button.state(["!disabled" if start + len(page) < total else "disabled"])
