"""Choose a canonical result source independently of translated display labels."""
import tkinter as tk
from tkinter import simpledialog, ttk

from .analysis_chain import ResultSource
from .i18n import tr
from .window_geometry import keep_native_window_on_screen


class AnalysisSourceDialog(simpledialog.Dialog):
    def __init__(self, parent, run, runs, validate_source):
        self.run = run
        self.parents = [None, *(other for other in runs if other.uid != run.uid
                                and other.result is not None and not other.calculation_error)]
        self.validate_source = validate_source
        self.error = tk.StringVar(parent, '')
        super().__init__(parent, tr('chain.change_input'))

    def body(self, master):
        box = ttk.Frame(master, padding=12)
        box.pack(fill='both', expand=True)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text=tr('chain.source_analysis')).grid(row=0, column=0, sticky='w', padx=(0, 12), pady=5)
        self.labels = [tr('chain.original_data', title=self.run.title),
                       *(f'{other.name} [{index+1}]' for index, other in enumerate(self.parents[1:]))]
        self.parent_choice = ttk.Combobox(box, state='readonly', values=self.labels, width=58)
        self.parent_choice.grid(row=0, column=1, sticky='ew', pady=5)
        ttk.Label(box, text=tr('chain.result_table')).grid(row=1, column=0, sticky='w', padx=(0, 12), pady=5)
        self.table_choice = ttk.Combobox(box, state='readonly', width=58)
        self.table_choice.grid(row=1, column=1, sticky='ew', pady=5)
        ttk.Label(box, text=tr('chain.review_note'), wraplength=590).grid(row=2, column=0, columnspan=2,
                                                                       sticky='w', pady=(8, 4))
        ttk.Label(box, textvariable=self.error, foreground='#ad263b', wraplength=590).grid(
            row=3, column=0, columnspan=2, sticky='w')
        self.parent_choice.bind('<<ComboboxSelected>>', self.sync_tables)
        if self.run.source is None:
            self.parent_choice.current(0)
        else:
            index = next((i for i, other in enumerate(self.parents)
                          if other is not None and other.uid == self.run.source.analysis_id), None)
            if index is not None:
                self.parent_choice.current(index)
            else:
                self.error.set(tr('chain.current_unavailable'))
        self.sync_tables()
        if self.run.source is not None and self.run.source.table in self.table_choice.cget('values'):
            self.table_choice.set(self.run.source.table)
        elif self.run.source is not None:
            self.table_choice.set('')
            self.error.set(tr('chain.current_unavailable'))
        self.after_idle(lambda: keep_native_window_on_screen(self))
        return self.parent_choice

    def sync_tables(self, event=None):
        index = self.parent_choice.current()
        parent = self.parents[index] if index >= 0 else None
        tables = list(parent.result.tables) if parent is not None else []
        self.table_choice.configure(values=tables, state='readonly' if tables else 'disabled')
        self.table_choice.set(tables[0] if tables else '')

    def buttonbox(self):
        box = ttk.Frame(self, padding=(12, 4, 12, 12))
        box.pack(fill='x')
        self.cancel_button = ttk.Button(box, text=tr('chain.cancel'), command=self.cancel)
        self.cancel_button.pack(side='right')
        self.ok_button = ttk.Button(box, text=tr('chain.continue'), command=self.ok)
        self.ok_button.pack(side='right', padx=(0, 6))
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

    def validate(self):
        index = self.parent_choice.current()
        if index < 0:
            self.error.set(tr('chain.choose_source'))
            self.parent_choice.focus_set()
            return False
        parent = self.parents[index]
        name = self.table_choice.get()
        if parent is not None and name not in parent.result.tables:
            self.error.set(tr('chain.choose_table'))
            self.table_choice.focus_set()
            return False
        self.candidate = ResultSource(parent.uid, name) if parent is not None else None
        try:
            self.validate_source(self.candidate)
        except ValueError as error:
            message = tr('chain.error.cycle') if str(error) == 'Analysis input links contain a cycle.' else str(error)
            self.error.set(tr('chain.invalid_source', error=message))
            self.parent_choice.focus_set()
            return False
        return True

    def apply(self):
        # A one-item tuple distinguishes an explicit data source (None) from Cancel.
        self.result = (self.candidate,)
