"""File → Export with options…: format, physical width, DPI, transparency and SVG text of a figure."""
from tkinter import simpledialog, ttk
import tkinter as tk

from . import figure_export as fe
from .data import decimal_comma

CUSTOM = "Custom"
FORMAT_NAMES = {"PNG": "png", "TIFF": "tiff", "SVG": "svg", "PDF": "pdf"}
# Preferences last only for the session.
SESSION = {"preset": "Screen", **fe.PRESETS["Screen"]}


class FigureExportDialog(simpledialog.Dialog):
    """``size`` is the current figure size in inches; ``raster_panels`` tells that panels are embedded images.

    ``layout_size`` is the original page size of a native layout.

    The result is a settings dict for ``figure_export`` or None when cancelled.
    """

    def __init__(self, parent, size, raster_panels=False, layout_size=None):
        self.size, self.raster_panels, self.plan = size, raster_panels, None
        self.layout_size = layout_size
        self.loading = False
        super().__init__(parent, "Export with options")

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        body = ttk.Frame(master, padding=(10, 8, 10, 4))
        body.pack(fill="both", expand=True)
        state = SESSION
        self.preset = tk.StringVar(value=state.get("preset", CUSTOM))
        self.format = tk.StringVar(value=next(k for k, v in FORMAT_NAMES.items() if v == state.get("format", "png")))
        self.width = tk.StringVar(value="" if state.get("width_mm") is None else f"{state['width_mm']:g}")
        self.dpi = tk.StringVar(value=f"{state.get('dpi', fe.DEFAULT_DPI):g}")
        self.transparent = tk.BooleanVar(value=bool(state.get("transparent", False)))
        self.svg_text = tk.StringVar(value="Paths" if state.get("svg_text") == "paths" else "Text")
        frame = ttk.LabelFrame(body, text="Output", padding=(10, 6))
        frame.pack(fill="x")
        frame.columnconfigure(1, weight=1)
        rows = [("Preset", ttk.Combobox(frame, state="readonly", width=14, textvariable=self.preset,
                                        values=[*fe.PRESETS, CUSTOM]), "preset"),
                ("Format", ttk.Combobox(frame, state="readonly", width=14, textvariable=self.format,
                                        values=list(FORMAT_NAMES)), "format"),
                ("Width (mm)", ttk.Entry(frame, width=16, textvariable=self.width), "width"),
                ("DPI", ttk.Entry(frame, width=16, textvariable=self.dpi), "dpi"),
                ("SVG text", ttk.Combobox(frame, state="readonly", width=14, textvariable=self.svg_text,
                                          values=["Text", "Paths"]), "svg_text"),
                ("", ttk.Checkbutton(frame, text="Transparent background", variable=self.transparent), "transparent")]
        self.rows = {}
        for r, (label, widget, name) in enumerate(rows):
            caption = ttk.Label(frame, text=label)
            caption.grid(row=r, column=0, sticky="w", pady=2, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="w", pady=2)
            self.rows[name] = (caption, widget)
        self.width_note = ttk.Label(frame, foreground="#46576b")
        self.width_note.grid(row=len(rows), column=0, columnspan=2, sticky="w")
        self.summary = ttk.Label(body, wraplength=380, justify="left")
        self.summary.pack(anchor="w", pady=(8, 0))
        self.note = ttk.Label(body, wraplength=380, justify="left", foreground="#46576b")
        self.note.pack(anchor="w", pady=(4, 0))
        self.preset.trace_add("write", lambda *_: self.apply_preset())
        for variable in (self.format, self.width, self.dpi, self.transparent, self.svg_text):
            variable.trace_add("write", lambda *_: self.edited())
        self.refresh()
        return self.rows["width"][1]

    def apply_preset(self):
        values = fe.PRESETS.get(self.preset.get())
        if values is None:
            return
        self.loading = True
        try:
            self.format.set(next(k for k, v in FORMAT_NAMES.items() if v == values["format"]))
            self.width.set(f"{values['width_mm']:g}")
            self.dpi.set(str(values.get("dpi", fe.DEFAULT_DPI)))
            self.transparent.set(values["transparent"])
        finally:
            self.loading = False
        self.refresh()

    def edited(self):
        if not self.loading and self.preset.get() != CUSTOM:
            self.loading = True
            self.preset.set(CUSTOM)
            self.loading = False
        self.refresh()

    def settings(self):
        fmt = FORMAT_NAMES[self.format.get()]
        text = self.width.get().strip()
        settings = {"format": fmt, "transparent": bool(self.transparent.get()),
                    "svg_text": self.svg_text.get().lower()}
        try:
            settings["width_mm"] = float(decimal_comma(text)) if text else None
        except ValueError:
            raise ValueError("Width must be a number in millimetres.") from None
        if fmt in {"png", "tiff"}:
            text = self.dpi.get().strip()
            try:
                settings["dpi"] = float(decimal_comma(text))
            except ValueError:
                raise ValueError("DPI must be a whole number.") from None
        return settings

    def _plan(self):
        settings = self.settings()
        size = self.layout_size if self.layout_size is not None else self.size
        return fe.plan_export(size, settings)

    def refresh(self):
        raster = self.format.get() in {"PNG", "TIFF"}
        native_layout = self.layout_size is not None
        self.width_note.configure(text="Empty width keeps the layout's original page size."
                                  if native_layout
                                  else "Empty width keeps the current figure size.")
        for name, visible in (("dpi", raster), ("svg_text", self.format.get() == "SVG"),
                              ("transparent", self.format.get() != "TIFF")):
            for widget in self.rows[name]:
                widget.grid() if visible else widget.grid_remove()
        try:
            self.plan = self._plan()
        except ValueError as error:
            self.plan = None
            self.summary.configure(text=str(error), foreground="#b00020")
            self.note.configure(text="")
            return
        plan = self.plan
        text = f"Final size: {plan['width_mm']:.1f} × {plan['height_mm']:.1f} mm"
        if plan["pixels"]:
            text += f" · {plan['pixels'][0]} × {plan['pixels'][1]} px ({plan['pixels'][0] * plan['pixels'][1] / 1e6:.1f} Mpx)"
        self.summary.configure(text=text, foreground="#1c2b3a")
        notes = []
        if plan["format"] == "tiff":
            notes.append("TIFF is opaque RGB with LZW compression.")
        if native_layout and not raster:
            notes.append(f"{plan['format'].upper()} preserves vector graphics and text in the layout panels. "
                         "Images inside a graph stay images.")
        elif native_layout:
            notes.append("PNG and TIFF draw the layout as a raster image. "
                         "Choose SVG or PDF to preserve vector graphics.")
        elif self.raster_panels:
            notes.append("This layout embeds its panels as images, so they stay raster even in SVG and PDF.")
        elif not raster:
            notes.append("Vector output; any raster element is drawn at 300 DPI.")
        self.note.configure(text=" ".join(notes))

    def validate(self):
        try:
            plan = self._plan()
        except ValueError as error:
            self.summary.configure(text=str(error), foreground="#b00020")
            return False
        self.plan = plan
        return True

    def apply(self):
        settings = self.settings()
        SESSION.clear()
        SESSION.update(preset=self.preset.get(), **{k: v for k, v in settings.items()
                                                    if k in {"format", "width_mm", "dpi", "transparent"}})
        self.result = settings
