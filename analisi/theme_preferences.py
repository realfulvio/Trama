"""Interface-only theme preference; canonical values never enter an .alab recipe."""
import json
import os
from pathlib import Path
import tempfile

THEMES = ("standard", "modern")


def load_theme(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "standard"
    value = data.get("theme") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value in THEMES else "standard"


def save_theme(path, theme):
    if theme not in THEMES:
        raise ValueError("Unknown interface theme")
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["theme"] = theme
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".theme-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


from tkinter import StringVar, messagebox, simpledialog, ttk
from .i18n import tr


class ThemeDialog(simpledialog.Dialog):
    """Apply on the next launch, leaving open worksheets and unsaved edits intact."""
    def __init__(self, parent, path, *, error=None):
        self.path = path
        self.choice = StringVar(parent, load_theme(path))
        self.saved = False
        self.report = error or (lambda message: messagebox.showerror("Trama", message, parent=self))
        super().__init__(parent, tr("theme.title"))

    def body(self, master):
        frame = ttk.Frame(master, padding=(16, 12))
        frame.pack(fill="both", expand=True)
        self.buttons = {}
        for key in THEMES:
            button = ttk.Radiobutton(frame, text=tr("theme." + key), variable=self.choice, value=key)
            button.pack(anchor="w", pady=(8, 3))
            ttk.Label(frame, text=tr("theme." + key + ".description"), style="Hint.TLabel",
                      wraplength=340, justify="left").pack(anchor="w", padx=(22, 0))
            self.buttons[key] = button
        ttk.Separator(frame).pack(fill="x", pady=12)
        ttk.Label(frame, text=tr("theme.note"), wraplength=360, justify="left").pack(anchor="w")
        return self.buttons[self.choice.get()]

    def buttonbox(self):
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        self.ok_button = ttk.Button(bar, text=tr("language.ok"), style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=4)
        ttk.Button(bar, text=tr("language.cancel"), command=self.cancel).pack(side="right")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        try:
            save_theme(self.path, self.choice.get())
        except (OSError, ValueError) as error:
            self.report(tr("language.error", error=error))
            return False
        self.saved = True
        return True

    def apply(self):
        self.result = self.choice.get()
