"""Dialog controls of the power planning page (Tools → Power and sample size)."""
import tkinter as tk
from tkinter import ttk


class MultilineEntry(ttk.Frame):
    """A few lines of text bound to a StringVar, for a list of numbers separated by semicolons or new lines.

    Return adds a line (the analysis dialog has no default button), Tab and Shift+Tab leave the box, and the
    variable follows every edit, paste or programmatic change in both directions.
    """

    def __init__(self, parent, variable, *, height=4, width=32):
        super().__init__(parent)
        self.variable = variable
        self.columnconfigure(0, weight=1)
        self.box = tk.Text(self, height=height, width=width, wrap="word", undo=True)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.box.yview)
        self.box.configure(yscrollcommand=scroll.set)
        self.box.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.box.insert("1.0", variable.get())
        self.box.edit_reset()
        self.box.edit_modified(False)
        self.box.bind("<<Modified>>", self._from_box)
        self.box.bind("<Tab>", lambda event: (event.widget.tk_focusNext().focus_set(), "break")[1])
        self.box.bind("<Shift-Tab>", lambda event: (event.widget.tk_focusPrev().focus_set(), "break")[1])
        self.box.bind("<ISO_Left_Tab>", lambda event: (event.widget.tk_focusPrev().focus_set(), "break")[1])
        self._trace = variable.trace_add("write", self._from_variable)
        self.bind("<Destroy>", self._forget, add="+")

    def focus_target(self):
        return self.box

    def _text(self):
        return self.box.get("1.0", "end-1c")

    def _from_box(self, _event=None):
        if not self.box.edit_modified():
            return
        self.box.edit_modified(False)
        text = self._text()
        if text != self.variable.get():
            self.variable.set(text)

    def _from_variable(self, *_):
        text = self.variable.get()
        if text != self._text():
            self.box.delete("1.0", "end")
            self.box.insert("1.0", text)
            self.box.edit_modified(False)

    def _forget(self, event):
        if event.widget is self:
            try:
                self.variable.trace_remove("write", self._trace)
            except tk.TclError:
                pass
