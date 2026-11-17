"""Optional worksheet/graph workspace for the Modern theme.

A private Figure copy owns the preview canvas. Resizing or previewing an Inspector
edit cannot resize the saved figure or change its confirmed style. Only Apply
commits a validated style back to the source run. No analysis runs implicitly.
"""
from copy import deepcopy
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from . import ui_theme
from .graph_inspector import GraphInspector
from .i18n import tr, ui
from .presentation import apply_style, validate_graph_style


class ModernWorksheet(ttk.Frame):
    def __init__(self, parent, app, title):
        super().__init__(parent)
        self.app, self.title = app, title
        self.canvas = None
        self.figure = None
        self.run = None
        self.inspector = None
        self._result_identity = None
        self._disposed = False
        self._initial_sash = None
        self._resize_job = None
        self._sidebar_override = None
        self._selection_key = (app.active_project, title)
        self._last_width = 0
        self._positioned = False
        self.links = []
        self.preview_wanted = tk.BooleanVar(self, not getattr(app, '_modern_preview_hidden', False))
        self.sidebar_wanted = tk.BooleanVar(self, False)

        tools = ttk.Frame(self, padding=(0, 0, 0, 6))
        tools.pack(fill='x')
        ttk.Checkbutton(tools, text=tr('modern.preview'), variable=self.preview_wanted,
                        command=self.toggle_preview).pack(side='left')
        ttk.Checkbutton(tools, text=tr('modern.format'), variable=self.sidebar_wanted,
                        command=self.toggle_sidebar).pack(side='right')
        self.body = ttk.Panedwindow(self, orient='horizontal')
        self.body.pack(fill='both', expand=True)
        self.split = ttk.Panedwindow(self.body, orient='vertical')
        self.body.add(self.split, weight=1)
        self.grid_host = ttk.Frame(self.split, height=ui_theme.px(280))
        self.split.add(self.grid_host, weight=3)
        self.preview = ttk.Frame(self.split, height=ui_theme.px(235))
        self.header = ttk.Frame(self.preview, padding=(7, 5))
        self.header.pack(fill='x')
        ttk.Label(self.header, text=tr('modern.preview'), font=ui_theme.font(10, 'bold')).pack(side='left')
        self.choice = ttk.Combobox(self.header, state='readonly', width=23)
        self.choice.pack(side='left', fill='x', expand=True, padx=8)
        self.choice.bind('<<ComboboxSelected>>', self._chosen)
        self.open_button = ttk.Button(self.header, text=tr('modern.open_graph'), command=self.open_graph)
        self.open_button.pack(side='right')
        self.warning = ttk.Label(self.preview, foreground='#8a4b0f', wraplength=500, justify='left')
        self.plot_host = ttk.Frame(self.preview)
        self.plot_host.pack(fill='both', expand=True)
        self.sidebar = ttk.Frame(self.body, width=ui_theme.px(300))
        self.sidebar.pack_propagate(False)
        self.table_info = ttk.LabelFrame(self.sidebar, text=tr('modern.table'), padding=(10, 8))
        self.table_info.pack(fill='x', padx=(8, 0), pady=(0, 8))
        dataset = app.tables[title]
        ttk.Label(self.table_info, text=f'{tr("modern.table_type")}: {ui(dataset.table_format)}').pack(anchor='w')
        ttk.Label(self.table_info, text=tr('modern.table_size', rows=len(dataset.raw), columns=len(dataset.raw.columns))).pack(anchor='w', pady=(4, 0))
        self.inspector_host = ttk.Frame(self.sidebar)
        self.inspector_host.pack(fill='both', expand=True)
        self.toggle_preview()
        self.bind('<Configure>', self._resized)
        self.refresh()

    def _available(self):
        refs = next((entries for section, entries, *_ in self.app.sheet_sections() if section == 'Graphs'), [])
        return [(index, self.app.runs[index]) for _, (kind, index) in refs
                if kind == 'graph' and self.app.runs[index].title == self.title]

    def refresh(self):
        if self._disposed:
            return
        self.links = self._available()
        remembered = getattr(self.app, '_modern_graph_choices', {}).get(self._selection_key)
        selected = next((i for i, (_, run) in enumerate(self.links) if run.slot == remembered), len(self.links) - 1)
        names = [ui(run.method) for _, run in self.links]
        labels = [f"{name} · {i + 1}" if names.count(name) > 1 else name for i, name in enumerate(names)]
        self.choice.configure(values=labels,
                              state='readonly' if self.links else 'disabled')
        self.open_button.state(['!disabled'] if self.links else ['disabled'])
        if self.links:
            self.choice.current(max(0, selected))
        self._show_selected()

    def _chosen(self, _event=None):
        if self.links and self.choice.current() >= 0:
            if not hasattr(self.app, '_modern_graph_choices'):
                self.app._modern_graph_choices = {}
            self.app._modern_graph_choices[self._selection_key] = self.links[self.choice.current()][1].slot
        self._show_selected(force=True)

    def _selected(self):
        index = self.choice.current()
        return self.links[index] if 0 <= index < len(self.links) else (None, None)

    def _drop_preview(self):
        if self.inspector is not None:
            if self.app.inspector is self.inspector:
                self.app.dispose_inspector()
            else:
                self.inspector.dispose()
                self.inspector.destroy()
            self.inspector = None
        if self.canvas is not None:
            widget = self.canvas.get_tk_widget()
            for name in ('_idle_draw_id', '_event_loop_id'):
                job = getattr(self.canvas, name, None)
                if job:
                    try:
                        widget.after_cancel(job)
                    except tk.TclError:
                        pass
                    setattr(self.canvas, name, None)
            widget.destroy()
            self.canvas = None
        # The Figure belongs exclusively to the preview. Never clear the source Figure.
        if self.figure is not None:
            self.figure.clear()
            self.figure = None
        for parent in (self.plot_host, self.inspector_host):
            for child in parent.winfo_children():
                child.destroy()
        self._result_identity = None
        self.run = None

    def _show_selected(self, *, force=False):
        index, run = self._selected()
        note = self.app.stale_calculation_note(('graph', index)) if run is not None else None
        self.warning.configure(text=note or '')
        if note:
            self.warning.pack(fill='x', padx=8, pady=4, before=self.plot_host)
        else:
            self.warning.pack_forget()
        if not self.preview_wanted.get():
            self._drop_preview()
            return
        identity = (id(run), id(run.result)) if run is not None else None
        if not force and self.canvas is not None and identity == self._result_identity:
            return
        self._drop_preview()
        self.run = run
        if run is None:
            self._placeholder('modern.no_graph', self.app.new_graph, 'modern.create_graph')
            return
        if run.result is None or run.result.figure is None:
            pending = self.app.pending is not None
            self._placeholder('modern.calculating' if pending else 'modern.not_calculated',
                              None if pending else lambda: self.app.recalculate(index), 'modern.calculate')
            return
        try:
            self.figure = deepcopy(run.result.figure)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_host)
            self.canvas.get_tk_widget().pack(fill='both', expand=True)
            self.canvas.draw()
        except Exception as error:
            self._drop_preview()
            self.run = run
            self._placeholder('modern.preview_unavailable', self.open_graph, 'modern.open_graph')
            # A failed preview must never prevent access to data or the original graph.
            self.app.status.set(tr('modern.preview_failed', error=str(error)))
            return
        self._result_identity = identity
        self._build_inspector(run)

    def _placeholder(self, key, action=None, caption=None):
        ttk.Label(self.plot_host, text=tr(key), style='Hint.TLabel', wraplength=340,
                  justify='center').pack(expand=True, pady=12)
        if action is not None:
            ttk.Button(self.plot_host, text=tr(caption), command=action).pack(pady=(0, 12))

    def _build_inspector(self, run):
        problem = self.app.graph_format_problem(run)
        if problem:
            ttk.Label(self.inspector_host, text=ui(problem), wraplength=260, justify='left').pack(padx=12, pady=12)
            return
        proxy = SimpleNamespace(method=run.method,
                                result=SimpleNamespace(figure=self.figure, style_warning=run.result.style_warning))
        from .hierarchical_style import describe_hierarchical_artists

        hierarchical = None
        if describe_hierarchical_artists(self.figure):
            hierarchical = lambda run=run: self._edit_hierarchical(run)
        self.inspector = GraphInspector(self.inspector_host, proxy, self.canvas, None,
            confirmed=lambda: run.style, commit=lambda style: self._commit(run, style),
            closed=self.close_inspector, hierarchical_style=hierarchical)
        self.inspector.pack(fill='both', expand=True)
        self.app.inspector = self.inspector

    def _edit_hierarchical(self, run):
        """Edit the private preview. Apply commits the same section onto the saved figure."""
        from .hierarchical_style_dialog import HierarchicalStyleDialog

        if self.app.pending is not None:
            return
        if self.inspector is not None and self.inspector.has_draft:
            if not self.app.settle_graph_draft("editing the dendrogram style"):
                return
        dialog = HierarchicalStyleDialog(self.winfo_toplevel(), self.figure, self.canvas, run.style or {})
        if dialog.result is None:
            return
        self._commit(run, dialog.result)
        if self.inspector is not None and self.inspector.winfo_exists():
            self.inspector.draft = deepcopy(run.style or {})
            self.inspector._load()

    def _commit(self, run, style):
        if self.app.pending is not None or run.result is None:
            raise ValueError(tr('modern.calculating'))
        validate_graph_style(run.result.figure.axes[0], style)
        apply_style(run.result.figure, style)
        self.app.commit_graph_style(run, deepcopy(style))

    def close_inspector(self):
        if self.inspector is not None:
            self.app.dispose_inspector()
            self.inspector = None
        self.sidebar_wanted.set(False)
        self._sidebar_override = False
        self._apply_sidebar()

    def toggle_sidebar(self):
        # Checkbutton already updates its variable; public callers use show_format().
        self._sidebar_override = self.sidebar_wanted.get()
        self._apply_sidebar()
        if self.sidebar_wanted.get() and self.inspector is None and self.canvas is not None:
            self._build_inspector(self.run)

    def show_format(self):
        self.sidebar_wanted.set(not self.sidebar_wanted.get())
        self.toggle_sidebar()

    def _apply_sidebar(self):
        visible = str(self.sidebar) in self.body.panes()
        if self.sidebar_wanted.get() and not visible:
            self.body.add(self.sidebar, weight=0)
            # The fixed-width pane supplies its requested size. Do not process Tk
            # events here: a nested resize may remove the pane before sash access.
        elif not self.sidebar_wanted.get() and visible:
            self.body.forget(self.sidebar)

    def toggle_preview(self):
        visible = str(self.preview) in self.split.panes()
        wanted = self.preview_wanted.get()
        self.app._modern_preview_hidden = not wanted
        if wanted and not visible:
            self._positioned = False
            self.split.add(self.preview, weight=2)
            self._initial_sash = self.after_idle(self._position_preview)
        elif not wanted and visible:
            self.split.forget(self.preview)
        if hasattr(self, 'choice'):
            self._show_selected()

    def _position_preview(self):
        self._initial_sash = None
        if not self._disposed and not self._positioned and len(self.split.panes()) > 1:
            height = self.split.winfo_height()
            if height > 100:
                self.split.sashpos(0, max(140, round(height * .55)))
                self._positioned = True

    def _resized(self, event):
        if event.widget is not self or event.width == self._last_width:
            return
        self._last_width = event.width
        if self._sidebar_override is None:
            self.sidebar_wanted.set(event.width >= ui_theme.px(1000))
            if self._resize_job is not None:
                self.after_cancel(self._resize_job)
            self._resize_job = self.after_idle(self._finish_resize)

    def _finish_resize(self):
        self._resize_job = None
        self._apply_sidebar()
        if self._initial_sash is None:
            self._position_preview()

    def open_graph(self):
        index, _ = self._selected()
        if index is not None:
            self.app.open_graph_view(index)

    def dispose(self):
        self._disposed = True
        for job in (self._initial_sash, self._resize_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._drop_preview()
