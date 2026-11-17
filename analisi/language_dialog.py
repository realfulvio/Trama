"""Edit → Language…: choose the interface language used at the next start."""
from tkinter import StringVar, messagebox, simpledialog, ttk

from .i18n import LANGUAGE_NAMES, LANGUAGES, load_language, save_language, tr


class LanguageDialog(simpledialog.Dialog):
    """Both language names stay in their own language, so the way back to English is always readable.

    OK writes the preference file; Cancel, Esc or closing the window leave it untouched. A failed
    write is reported and the dialog stays open, so nothing claims a saved preference.
    """

    def __init__(self, parent, path, *, error=None):
        self.path = path
        self.report = error or (lambda message: messagebox.showerror("Trama", message, parent=self))
        self.saved = False
        self.choice = StringVar(parent, load_language(path))
        super().__init__(parent, tr("language.title"))

    def body(self, master):
        frame = ttk.Frame(master, padding=(10, 8, 10, 2))
        frame.pack(fill="both", expand=True)
        self.buttons = {}
        for code in LANGUAGES:
            button = ttk.Radiobutton(frame, text=LANGUAGE_NAMES[code], value=code, variable=self.choice)
            button.pack(anchor="w", pady=2)
            self.buttons[code] = button
        self.note = ttk.Label(frame, text=tr("language.note"), wraplength=300, justify="left")
        self.note.pack(anchor="w", pady=(8, 0))
        return self.buttons[self.choice.get()]

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(8, 5))
        self.ok_button = ttk.Button(bar, text=tr("language.ok"), width=10, style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=4)
        self.cancel_button = ttk.Button(bar, text=tr("language.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        bar.pack(fill="x")

    def validate(self):
        try:
            save_language(self.path, self.choice.get())
        except (OSError, ValueError) as error:
            self.report(tr("language.error", error=error))
            return False
        self.saved = True
        return True

    def apply(self):
        self.result = self.choice.get()
