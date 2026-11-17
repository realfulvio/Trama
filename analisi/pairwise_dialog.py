"""Insert → Pairwise Comparisons… (and Compact Letter Display…): choose the source analysis and show the
comparisons as brackets or as compact letters."""
from tkinter import simpledialog, ttk
import tkinter as tk

from matplotlib.colors import is_color_like

from . import compact_letters as cl
from . import pairwise_graph as pg

CHECKED, UNCHECKED = "☑", "☐"


class PairwiseDialog(simpledialog.Dialog):
    """``sources`` lists ``(slot, method, caption)``. ``load_rows(slot)`` returns the source rows or raises.

    The result is ``("apply", record)`` or ``("remove", None)``; Cancel leaves it None.
    """

    def __init__(self, parent, sources, current, anchors, load_rows, display=None):
        self.sources, self.current, self.anchors, self.load_rows = list(sources), current, anchors, load_rows
        self.rows, self.checked, self.action = [], set(), "apply"
        self.initial_display = display or (pg.LETTERS if (current or {}).get("display") == "letters" else pg.BRACKETS)
        super().__init__(parent, "Compact Letter Display" if display == pg.LETTERS else "Pairwise Comparisons")

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        body = ttk.Frame(master, padding=(10, 8, 10, 4))
        body.pack(fill="both", expand=True)
        current = self.current or {}
        slots = [slot for slot, _, _ in self.sources]
        source = ttk.LabelFrame(body, text="Source", padding=(10, 6))
        source.pack(fill="x")
        self.source = ttk.Combobox(source, state="readonly", width=58, values=[caption for _, _, caption in self.sources])
        self.source.pack(fill="x")
        self.note = ttk.Label(source, wraplength=470, foreground="#46576b")
        self.note.pack(anchor="w", pady=(4, 0))

        shown = ttk.LabelFrame(body, text="Display", padding=(10, 6))
        shown.pack(fill="x", pady=(8, 0))
        self.display = tk.StringVar(value=self.initial_display)
        for value in pg.DISPLAYS:
            ttk.Radiobutton(shown, text=value, value=value, variable=self.display).pack(side="left", padx=(0, 12))

        pairs = self.pairs_frame = ttk.LabelFrame(body, text="Pairs", padding=(10, 6))
        pairs.pack(fill="both", expand=True, pady=(8, 0))
        self.selection = tk.StringVar(value=current.get("selection", pg.ALL))
        row = ttk.Frame(pairs)
        row.pack(fill="x")
        for value, text in ((pg.ALL, "All comparisons"), (pg.SELECTED, "Selected pairs")):
            ttk.Radiobutton(row, text=text, value=value, variable=self.selection).pack(side="left", padx=(0, 12))
        frame = ttk.Frame(pairs)
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(frame, columns=("use", "pair", "p"), show="headings", height=8, selectmode="browse")
        for name, title, width, anchor in (("use", "", 34, "center"), ("pair", "Pair", 300, "w"), ("p", "P", 110, "e")):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, anchor=anchor, stretch=name == "pair")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<space>", lambda _event: self.toggle(self.tree.focus()))

        look = self.look_frame = ttk.LabelFrame(body, text="Labels", padding=(10, 6))
        look.pack(fill="x", pady=(8, 0))
        self.label = tk.StringVar(value=pg.P_VALUE if current.get("label") == "p" else pg.STARS)
        self.filter = tk.StringVar(value=current.get("filter", pg.NO_FILTER))
        self.cutoff = tk.StringVar(value=f"{current.get('stored_cutoff', pg.DEFAULT_CUTOFF):g}")
        self.color = tk.StringVar(value=current.get("color", pg.DEFAULT_COLOR))
        ttk.Label(look, text="Label").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=2)
        ttk.Radiobutton(look, text="Stars", value=pg.STARS, variable=self.label).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(look, text="P value", value=pg.P_VALUE, variable=self.label).grid(row=0, column=2, sticky="w")
        ttk.Label(look, text="Show").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=2)
        ttk.Radiobutton(look, text="All", value=pg.NO_FILTER, variable=self.filter).grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(look, text="At or below cutoff", value=pg.AT_OR_BELOW, variable=self.filter
                        ).grid(row=1, column=2, sticky="w")
        ttk.Label(look, text="Cutoff").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=2)
        self.cutoff_entry = ttk.Entry(look, width=10, textvariable=self.cutoff, justify="right")
        self.cutoff_entry.grid(row=2, column=1, sticky="w")
        ttk.Label(look, foreground="#46576b", wraplength=470,
                  text="Stars: * P ≤ 0.05, ** P ≤ 0.01, *** P ≤ 0.001, **** P ≤ 0.0001, ns otherwise. "
                       "The cutoff filters on the unrounded P value and does not change the stars."
                  ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        letters = self.letters_frame = ttk.LabelFrame(body, text="Compact letters", padding=(10, 6))
        names = {value: name for name, value in pg.IDENTIFIER_NAMES.items()}
        places = {value: name for name, value in pg.PLACEMENT_NAMES.items()}
        self.alpha = tk.StringVar(value=f"{current.get('alpha', cl.DEFAULT_ALPHA):g}")
        self.identifiers = tk.StringVar(value=names[current.get("identifiers", "lower")])
        self.placement = tk.StringVar(value=places[current.get("placement", "individual")])
        self.size = tk.StringVar(value=f"{current.get('size', pg.DEFAULT_LETTER_SIZE):g}")
        ttk.Label(letters, text="Alpha").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=2)
        self.alpha_entry = ttk.Entry(letters, width=10, textvariable=self.alpha, justify="right")
        self.alpha_entry.grid(row=0, column=1, sticky="w")
        ttk.Label(letters, text="Identifiers").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=2)
        self.identifier_box = ttk.Combobox(letters, state="readonly", width=12, textvariable=self.identifiers,
                                           values=list(pg.IDENTIFIER_NAMES))
        self.identifier_box.grid(row=1, column=1, sticky="w")
        ttk.Label(letters, text="Placement").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=2)
        for column, name in enumerate(pg.PLACEMENT_NAMES, 1):
            ttk.Radiobutton(letters, text=name, value=name, variable=self.placement).grid(row=2, column=column, sticky="w")
        ttk.Label(letters, text="Text size (pt)").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=2)
        ttk.Spinbox(letters, from_=pg.LETTER_SIZES[0], to=pg.LETTER_SIZES[1], increment=1, width=6,
                    textvariable=self.size, justify="right").grid(row=3, column=1, sticky="w")
        ttk.Label(letters, foreground="#46576b", wraplength=470,
                  text=f"{pg.LETTERS_MEANING} Every pair of the shown groups needs a P value from the source; "
                       "the bracket pair selection and cutoff are not used.").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.preview = ttk.Label(letters, wraplength=470)
        self.preview.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        colors = self.color_frame = ttk.Frame(body, padding=(10, 6, 10, 0))
        ttk.Label(colors, text="Line and text color").pack(side="left", padx=(0, 10))
        ttk.Entry(colors, width=12, textvariable=self.color).pack(side="left")
        ttk.Button(colors, text="Choose…", command=self._choose_color).pack(side="left", padx=(6, 0))
        self.problem = ttk.Label(body, foreground="#b42318", wraplength=470)
        self.filter.trace_add("write", lambda *_: self._sync_cutoff())
        self._sync_cutoff()
        for variable in (self.alpha, self.identifiers):
            variable.trace_add("write", lambda *_: self._preview())
        self.display.trace_add("write", lambda *_: self._sync_display())
        self._sync_display()

        chosen = current.get("slot")
        index = slots.index(chosen) if chosen in slots else 0
        if current.get("pairs"):
            self.checked = {frozenset(pair) for pair in current["pairs"]}
        self.initial_pairs = current.get("selection") == pg.SELECTED
        if self.sources:
            self.source.current(index)
            self._load()
        else:
            self.problem.configure(text="No compatible source analysis remains. Remove the comparisons or cancel.")
        self.source.bind("<<ComboboxSelected>>", lambda _event: self._load())
        return self.source

    def buttonbox(self):
        row = ttk.Frame(self, padding=(12, 0, 12, 10))
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left")
        ttk.Button(row, text="Apply", style="Action.TButton", command=self.ok).pack(side="right", padx=(8, 0))
        ttk.Button(row, text="Cancel", command=self.cancel).pack(side="right")
        row.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    # -- pairs ---------------------------------------------------------------

    def _pair_name(self, key):
        anchor = self.anchors.get(key)
        return anchor.get("name", key) if anchor else f"{key} (not shown)"

    def _load(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        slot, method, _ = self.sources[self.source.current()]
        self.note.configure(text=pg.ADJUSTED_NOTE if method in pg.ADJUSTED_SHEETS else
                            "Labels use the P value of the paired t-test.")
        try:
            rows = self.load_rows(slot)
        except Exception as error:
            self.problem.configure(text=f"The source could not be calculated. {error}")
            return
        self.problem.configure(text="" if rows else "The source has no valid P values for this graph.")
        seen = set()
        for row in rows:
            pair = frozenset((row["left"], row["right"]))
            if pair in seen:
                continue
            seen.add(pair)
            self.rows.append(row)
        if not self.initial_pairs:
            self.checked = {frozenset((row["left"], row["right"])) for row in self.rows}
        self.initial_pairs = False
        for index, row in enumerate(self.rows):
            pair = frozenset((row["left"], row["right"]))
            self.tree.insert("", "end", iid=str(index), values=(
                CHECKED if pair in self.checked else UNCHECKED,
                f"{self._pair_name(row['left'])}  vs  {self._pair_name(row['right'])}", f"{row['p']:.4g}"))
        self._preview()

    def _click(self, event):
        if self.tree.identify_column(event.x) == "#1" and (item := self.tree.identify_row(event.y)):
            self.toggle(item)
            return "break"
        return None

    def toggle(self, item):
        if not item:
            return
        row = self.rows[int(item)]
        pair = frozenset((row["left"], row["right"]))
        self.checked ^= {pair}
        self.tree.set(item, "use", CHECKED if pair in self.checked else UNCHECKED)
        self.selection.set(pg.SELECTED)

    def set_checked(self, pairs):
        """Check exactly these pairs (by key), as a user would click them."""
        wanted = {frozenset(pair) for pair in pairs}
        for item in self.tree.get_children():
            row = self.rows[int(item)]
            if (frozenset((row["left"], row["right"])) in wanted) != (frozenset((row["left"], row["right"])) in self.checked):
                self.toggle(item)

    # -- display mode --------------------------------------------------------

    def _sync_display(self):
        """Brackets show the pair selection and bracket labels; Compact letters show the letter options."""
        letters = self.display.get() == pg.LETTERS
        for frame in (self.pairs_frame, self.look_frame, self.letters_frame, self.color_frame, self.problem):
            frame.pack_forget()
        if letters:
            self.letters_frame.pack(fill="x", pady=(8, 0))
        else:
            self.pairs_frame.pack(fill="both", expand=True, pady=(8, 0))
            self.look_frame.pack(fill="x", pady=(8, 0))
        self.color_frame.pack(fill="x")
        self.problem.pack(anchor="w", pady=(6, 0))
        self._preview()

    def _letter_choices(self):
        """``(alpha, identifiers, placement, size)`` from the fields, or raise ValueError with a message."""
        try:
            alpha = float(self.alpha.get().strip().replace(",", "."))
        except ValueError:
            alpha = None
        if alpha is None or not 0 < alpha < 1:
            raise ValueError("Enter an alpha greater than 0 and less than 1.")
        try:
            size = float(self.size.get().strip().replace(",", "."))
        except ValueError:
            size = None
        if size is None or not pg.LETTER_SIZES[0] <= size <= pg.LETTER_SIZES[1]:
            raise ValueError(f"Enter a text size from {pg.LETTER_SIZES[0]} to {pg.LETTER_SIZES[1]} points.")
        return alpha, self.identifiers.get(), self.placement.get(), int(size) if size.is_integer() else size

    def letters(self):
        """The letters of the visible groups with the current choices: ``[(key, letters)]``. Raises ValueError."""
        alpha, identifiers, _, _ = self._letter_choices()
        settings = {"alpha": alpha, "identifiers": pg.IDENTIFIER_NAMES[identifiers]}
        groups, letters = pg.assign_letters(self.anchors, self.rows, settings)
        return [(key, " ".join(letters[key])) for key in groups]

    def _preview(self):
        if not hasattr(self, "preview") or self.display.get() != pg.LETTERS:
            return
        if not self.rows:
            self.preview.configure(text="", foreground="#46576b")
            return
        try:
            shown = self.letters()
        except ValueError as error:
            self.preview.configure(text=str(error), foreground="#8a4b0f")
            return
        self.preview.configure(text="Preview:  " + "   ".join(f"{self._pair_name(key)} = {text}" for key, text in shown),
                               foreground="#1f3b57")

    # -- labels --------------------------------------------------------------

    def _sync_cutoff(self):
        self.cutoff_entry.state(["!disabled"] if self.filter.get() == pg.AT_OR_BELOW else ["disabled"])

    def _choose_color(self):
        from .graph_dialog import pick_color

        pick_color(self, self.color)

    def remove(self):
        self.action = "remove"
        self.ok()

    def record(self):
        """The recipe section for the current choices, or raise ValueError with a message for the dialog."""
        if not self.sources:
            raise ValueError("Choose a compatible source analysis.")
        slot, method, _ = self.sources[self.source.current()]
        letters = self.display.get() == pg.LETTERS
        try:
            cutoff = float(self.cutoff.get().strip().replace(",", "."))
        except ValueError:
            cutoff = None
        if cutoff is None or not 0 < cutoff <= 1:
            if not letters:
                raise ValueError("Enter a cutoff greater than 0 and at most 1.")
            # The hidden bracket cutoff does not block letters; the stored one is kept.
            cutoff = (self.current or {}).get("stored_cutoff", pg.DEFAULT_CUTOFF)
        color = self.color.get().strip()
        if not color or len(color) > 40 or not is_color_like(color):
            raise ValueError("Enter a valid color, for example #303640.")
        alpha, identifiers, placement, size = self._letter_choices() if letters else (
            (self.current or {}).get("alpha", cl.DEFAULT_ALPHA),
            {v: k for k, v in pg.IDENTIFIER_NAMES.items()}[(self.current or {}).get("identifiers", "lower")],
            {v: k for k, v in pg.PLACEMENT_NAMES.items()}[(self.current or {}).get("placement", "individual")],
            (self.current or {}).get("size", pg.DEFAULT_LETTER_SIZE))
        if isinstance(size, float) and size.is_integer():
            size = int(size)
        selection = self.selection.get()
        pairs = [[row["left"], row["right"]] for row in self.rows
                 if frozenset((row["left"], row["right"])) in self.checked] if selection == pg.SELECTED else []
        record = pg.section_record(slot, method, selection=selection, pairs=pairs, label=self.label.get(),
                                   filtering=self.filter.get(), cutoff=cutoff, color=color,
                                   display=self.display.get(), alpha=alpha, identifiers=identifiers,
                                   placement=placement, size=size)
        if letters:
            if not self.rows:
                raise ValueError("The source has no valid P values for this graph.")
            self.letters()  # Refuses an incomplete matrix of the shown groups with a clear message.
            return record
        settings, _ = pg.read_section({pg.SECTION: record})
        count = pg.effective_count(self.anchors, self.rows, pg.plan_settings(settings))
        if count > pg.MAX_BRACKETS:
            raise ValueError(f"{count} pairs would be drawn. Select at most {pg.MAX_BRACKETS} pairs, or show only "
                             "P values at or below the cutoff.")
        return record

    def validate(self):
        if self.action == "remove":
            self.result = "remove", None
            return True
        try:
            self.result = "apply", self.record()
        except ValueError as error:
            self.problem.configure(text=str(error))
            if self.preview.cget("text") == str(error):
                self.preview.configure(text="")
            self.result = None
            return False
        return True
