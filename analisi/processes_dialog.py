"""Settings → Multicore calculation…: how many processes compute at the same time."""
from tkinter import IntVar, StringVar, messagebox, simpledialog, ttk

from . import parallel
from .i18n import tr

AUTO, SINGLE, FIXED = "auto", "single", "fixed"


class ProcessesDialog(simpledialog.Dialog):
    """OK writes ``processes`` in preferences.json and the caller applies it at once.

    Cancel, Esc or closing the window leave the file untouched. A failed write is reported and the dialog
    stays open, so nothing claims a saved preference.
    """

    def __init__(self, parent, path, *, error=None, processors=None):
        self.path = path
        self.report = error or (lambda message: messagebox.showerror("Trama", message, parent=self))
        self.saved = False
        self.processors = parallel.logical_processors() if processors is None else processors
        current = parallel.load_setting(path)
        mode = AUTO if current == parallel.AUTO else SINGLE if current == 1 else FIXED
        self.mode = StringVar(parent, mode)
        self.count = IntVar(parent, current if isinstance(current, int) and current > 1
                            else max(2, parallel.auto_processes(self.processors)))
        super().__init__(parent, tr("processes.title"))

    def body(self, master):
        frame = ttk.Frame(master, padding=(10, 8, 10, 2))
        frame.pack(fill="both", expand=True)
        automatic = parallel.auto_processes(self.processors)
        self.buttons = {
            AUTO: ttk.Radiobutton(frame, text=tr("processes.auto", count=automatic), value=AUTO,
                                  variable=self.mode, command=self.refresh),
            SINGLE: ttk.Radiobutton(frame, text=tr("processes.single"), value=SINGLE, variable=self.mode,
                                    command=self.refresh),
        }
        self.buttons[AUTO].pack(anchor="w", pady=2)
        self.buttons[SINGLE].pack(anchor="w", pady=2)
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=2)
        self.buttons[FIXED] = ttk.Radiobutton(row, text=tr("processes.fixed"), value=FIXED, variable=self.mode,
                                              command=self.refresh)
        self.buttons[FIXED].pack(side="left")
        self.spin = ttk.Spinbox(row, from_=2, to=parallel.MAX_PROCESSES, width=5, textvariable=self.count)
        self.spin.pack(side="left", padx=(6, 0))
        ttk.Label(frame, text=tr("processes.processors", count=self.processors)).pack(anchor="w", pady=(8, 0))
        self.note = ttk.Label(frame, text=tr("processes.note"), wraplength=340, justify="left")
        self.note.pack(anchor="w", pady=(4, 0))
        self.refresh()
        return self.buttons[self.mode.get()]

    def refresh(self):
        self.spin.configure(state="normal" if self.mode.get() == FIXED else "disabled")

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(8, 5))
        self.ok_button = ttk.Button(bar, text=tr("processes.ok"), width=10, style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=4)
        self.cancel_button = ttk.Button(bar, text=tr("processes.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        bar.pack(fill="x")

    def choice(self):
        mode = self.mode.get()
        if mode == AUTO:
            return parallel.AUTO
        if mode == SINGLE:
            return 1
        try:
            count = int(self.spin.get())
        except ValueError:
            return None
        return count if 1 <= count <= parallel.MAX_PROCESSES else None

    def validate(self):
        setting = self.choice()
        if setting is None:
            self.report(tr("processes.invalid", maximum=parallel.MAX_PROCESSES))
            return False
        try:
            parallel.save_setting(self.path, setting)
        except (OSError, ValueError) as error:
            self.report(tr("processes.error", error=error))
            return False
        self.saved = True
        return True

    def apply(self):
        self.result = self.choice()
