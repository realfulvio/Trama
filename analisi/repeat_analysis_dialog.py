"""The Tk window of Analysis → Repeat analysis on other sheets…

Three steps over a :class:`~analisi.repeat_analysis_assistant.RepeatAssistant`: the recipe (only the selected
analysis or also its compatible downstream steps), the data sheets with the column of each sheet for every column
of the recipe, and the preview. The window only draws the assistant: every refusal comes from the engine, and
``result`` holds the plan when the user confirms. It never changes the project.
"""
import tkinter as tk
from tkinter import font as tkfont, simpledialog, ttk

from .repeat_analysis import RepeatError
from .repeat_analysis_text import error_text, t
from .window_geometry import keep_native_window_on_screen

CHECKED, UNCHECKED = "☑", "☐"
ERROR = "#ad263b"


class RepeatDialog(simpledialog.Dialog):
    def __init__(self, parent, assistant, *, notice=None):
        self.assistant, self.plan, self.notice = assistant, None, notice
        self.boxes = {}
        super().__init__(parent, t("title"))

    # -- layout ---------------------------------------------------------------------------------
    def body(self, master):
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.wrap = max(420, min(760, screen_w - 260))
        box = ttk.Frame(master, padding=(12, 10, 12, 4))
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(2, weight=1)
        head = ttk.Frame(box)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.bold = (base["family"], base["size"], "bold")
        self.heading = ttk.Label(head, font=self.bold)
        self.heading.grid(row=0, column=0, sticky="w")
        self.step = ttk.Label(head)
        self.step.grid(row=0, column=1, sticky="e")
        self.banner_var = tk.StringVar(self, "")
        self.banner = ttk.Label(box, textvariable=self.banner_var, foreground=ERROR, wraplength=self.wrap,
                                justify="left")
        self.banner.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.pages = ttk.Frame(box)
        self.pages.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self.pages.columnconfigure(0, weight=1)
        self.pages.rowconfigure(0, weight=1)
        lines = max(8, min(18, (screen_h - 360) // 22))
        self.frames = [self._recipe_page(lines), self._sheets_page(lines), self._preview_page(lines)]
        for frame in self.frames:
            frame.grid(row=0, column=0, sticky="nsew")
        self.after_idle(lambda: keep_native_window_on_screen(self))
        return None

    def _text(self, parent, lines):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, width=88, height=lines, wrap="word", state="disabled", relief="flat", borderwidth=1,
                       highlightthickness=1, padx=8, pady=6, takefocus=False, font="TkDefaultFont")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        text.tag_configure("heading", font=self.bold, spacing1=6)
        text.tag_configure("counts", font=self.bold, spacing3=4)
        text.tag_configure("item", lmargin1=12, lmargin2=24)
        text.tag_configure("note", foreground="#176676", spacing1=4, lmargin1=0, lmargin2=12)
        return frame, text

    @staticmethod
    def _fill(text, lines):
        text.configure(state="normal")
        text.delete("1.0", "end")
        for tag, line in lines:
            text.insert("end", line + "\n", tag)
        text.configure(state="disabled")

    def _recipe_page(self, lines):
        page = ttk.Frame(self.pages)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)
        ttk.Label(page, text=self.assistant.source_text(), wraplength=self.wrap, justify="left").grid(
            row=0, column=0, sticky="w")
        self.method_var = tk.StringVar(self, "")
        ttk.Label(page, textvariable=self.method_var).grid(row=1, column=0, sticky="w", pady=(2, 4))
        self.follow_var = tk.BooleanVar(self, self.assistant.follow)
        self.only_button = ttk.Radiobutton(page, text=t("only"), variable=self.follow_var, value=False,
                                           command=self._follow_changed)
        self.only_button.grid(row=2, column=0, sticky="w")
        self.follow_button = ttk.Radiobutton(page, text=t("follow"), variable=self.follow_var, value=True,
                                             command=self._follow_changed)
        self.follow_button.grid(row=3, column=0, sticky="w")
        if not self.assistant.has_followers:
            self.follow_button.state(["disabled"])
        frame, self.summary = self._text(page, lines)
        frame.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
        return page

    def _sheets_page(self, lines):
        page = ttk.Frame(self.pages)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text=t("sheets_hint"), wraplength=self.wrap, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(page, text=t("sheet_list")).grid(row=1, column=0, sticky="w", pady=(6, 2))
        self.columns_title = ttk.Label(page, text="")
        self.columns_title.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(6, 2))
        left = ttk.Frame(page)
        left.grid(row=2, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        self.sheet_list = ttk.Treeview(left, show="tree", selectmode="browse", height=lines)
        self.sheet_list.column("#0", width=230, stretch=True)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.sheet_list.yview)
        self.sheet_list.configure(yscrollcommand=scroll.set)
        self.sheet_list.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.sheet_list.tag_configure("refused", foreground="#7a7f87")
        self.refused = {}
        for title, problem in self.assistant.sheets():
            if problem is None:
                mark = CHECKED if title in self.assistant.selected else UNCHECKED
                self.sheet_list.insert("", "end", iid=title, text=f"{mark} {title}")
            else:
                self.refused[title] = error_text(problem)
                self.sheet_list.insert("", "end", iid=title, text=f"   {title} — {self.refused[title]}",
                                       tags=("refused",))
        self.sheet_list.bind("<<TreeviewSelect>>", self._sheet_selected)
        self.sheet_list.bind("<space>", lambda _event: self.toggle(self.sheet_list.focus()))
        self.sheet_list.bind("<Button-1>", self._sheet_clicked, add="+")
        right = ttk.Frame(page)
        right.grid(row=2, column=1, sticky="nsew", padx=(12, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.grid_frame = ttk.Frame(right)
        self.grid_frame.grid(row=0, column=0, sticky="nsew")
        self.status_var = tk.StringVar(self, "")
        self.status = ttk.Label(right, textvariable=self.status_var, wraplength=max(300, self.wrap - 260),
                                justify="left")
        self.status.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        return page

    def _preview_page(self, lines):
        page = ttk.Frame(self.pages)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        frame, self.preview = self._text(page, lines + 3)
        frame.grid(row=0, column=0, sticky="nsew")
        return page

    def buttonbox(self):
        box = ttk.Frame(self, padding=(12, 4, 12, 12))
        box.pack(fill="x")
        self.cancel_button = ttk.Button(box, text=t("cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.apply_button = ttk.Button(box, text=t("apply"), command=self.ok)
        self.next_button = ttk.Button(box, text=t("next"), command=lambda: self.go(self.page + 1))
        self.back_button = ttk.Button(box, text=t("back"), command=lambda: self.go(self.page - 1))
        self.next_button.pack(side="right", padx=(0, 6))
        self.back_button.pack(side="right", padx=(0, 6))
        self.bind("<Escape>", self.cancel)
        self.bind("<Return>", lambda _event: self.ok() if self.page == 2 else self.go(self.page + 1))
        self.page = 0
        self.go(self.assistant.page, notice=self.notice)

    # -- behaviour ------------------------------------------------------------------------------
    def _follow_changed(self):
        self.assistant.set_follow(self.follow_var.get())
        self._fill_recipe()

    def _fill_recipe(self):
        self.method_var.set(self.assistant.method_text())
        self._fill(self.summary, self.assistant.summary())

    def _sheet_clicked(self, event):
        """A click on a sheet not yet used checks it; a click on the mark of a checked sheet unchecks it."""
        row = self.sheet_list.identify_row(event.y)
        if not row or row in self.refused:
            return
        if row not in self.assistant.selected:
            self.toggle(row, True)
            return
        box = self.sheet_list.bbox(row, "#0")
        mark = tkfont.nametofont("TkDefaultFont").measure(CHECKED + "  ")
        if box and event.x < box[0] + 20 + mark:
            self.toggle(row, False)

    def toggle(self, title, on=None):
        """Check or uncheck a data sheet (``on`` None: the opposite of now)."""
        if not title or title in self.refused:
            if title in self.refused:
                self.status_var.set(f"{title}: {self.refused[title]}")
                self.status.configure(foreground=ERROR)
            return
        on = title not in self.assistant.selected if on is None else on
        self.assistant.choose(title, on)
        self.sheet_list.item(title, text=f"{CHECKED if title in self.assistant.selected else UNCHECKED} {title}")
        if on:
            self.sheet_list.selection_set(title)
            self.sheet_list.focus(title)
        self._fill_columns()

    def _sheet_selected(self, _event=None):
        selection = self.sheet_list.selection()
        title = selection[0] if selection else None
        if title in self.refused:
            self.status_var.set(f"{title}: {self.refused[title]}")
            self.status.configure(foreground=ERROR)
            return
        if title in self.assistant.selected and title != self.assistant.current:
            self.assistant.current = title
            self._fill_columns()

    def _fill_columns(self):
        assistant = self.assistant
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.boxes = {}
        title = assistant.current if assistant.current in assistant.selected else None
        if title is None:
            self.columns_title.configure(text=t("no_sheet"))
            self._fill_status()
            return
        self.columns_title.configure(text=t("column_target", sheet=title))
        for column, key in enumerate(("column_recipe", None, "used_by")):
            text = t(key) if key else t("column_target", sheet=title)
            ttk.Label(self.grid_frame, text=text, font=self.bold).grid(row=0, column=column, sticky="w", padx=(0, 10))
        self.grid_frame.columnconfigure(1, weight=1)
        chosen = assistant.columns.get(title, {})
        values = [t("choose"), *assistant.available(title)]
        for row, requirement in enumerate(assistant.recipe.required, start=1):
            ttk.Label(self.grid_frame, text=requirement.column).grid(row=row, column=0, sticky="w", padx=(0, 10),
                                                                    pady=2)
            var = tk.StringVar(self, chosen.get(requirement.column) or t("choose"))
            box = ttk.Combobox(self.grid_frame, textvariable=var, values=values, state="readonly", width=22)
            box.grid(row=row, column=1, sticky="ew", padx=(0, 10), pady=2)
            box.bind("<<ComboboxSelected>>",
                     lambda _event, var=var, column=requirement.column: self.set_column(title, column, var.get()))
            self.boxes[requirement.column] = box
            ttk.Label(self.grid_frame, text=assistant.usage(requirement), wraplength=260, justify="left").grid(
                row=row, column=2, sticky="w", pady=2)
        self._fill_status()

    def set_column(self, title, column, value):
        """The column of ``title`` chosen for a recipe column (the placeholder clears it)."""
        self.assistant.set_column(title, column, None if value in ("", t("choose")) else value)
        if column in self.boxes and self.assistant.current == title:
            self.boxes[column].set(value or t("choose"))
        self._fill_status()

    def _fill_status(self):
        assistant = self.assistant
        title = assistant.current if assistant.current in assistant.selected else None
        problems = assistant.problem_texts(title) if title is not None else []
        self.status_var.set("\n".join(problems) if problems else (t("ready") if title else ""))
        self.status.configure(foreground=ERROR if problems else "")
        for name in assistant.selected:
            mark = CHECKED
            suffix = "" if not assistant.problems(name) else "  ⚠"
            self.sheet_list.item(name, text=f"{mark} {name}{suffix}")
        self._buttons()

    def _buttons(self):
        page = self.page
        self.back_button.state(["!disabled"] if page > 0 else ["disabled"])
        ready = page != 1 or self.assistant.ready()
        self.next_button.state(["!disabled"] if ready else ["disabled"])
        if page == 2:
            self.next_button.pack_forget()
            self.apply_button.pack(side="right", padx=(0, 6), before=self.back_button)
        else:
            self.apply_button.pack_forget()
            self.next_button.pack(side="right", padx=(0, 6), before=self.back_button)

    def go(self, page, *, notice=None):
        page = max(0, min(2, page))
        if page == 2:
            try:
                self.plan = self.assistant.plan()
            except RepeatError as error:
                problems = [error_text(item) for item in (error.problems or (error,))]
                notice = "\n".join(dict.fromkeys(problems))
                page = 1
            else:
                self._fill(self.preview, self.assistant.preview(self.plan))
        self.page = self.assistant.page = page
        self.frames[page].tkraise()
        self.heading.configure(text=t(("page.recipe", "page.sheets", "page.preview")[page]))
        self.step.configure(text=t("step", number=page + 1))
        if page == 0:
            self._fill_recipe()
        if page == 1:
            current = self.assistant.current
            if current in self.assistant.selected:
                self.sheet_list.selection_set(current)
                self.sheet_list.see(current)
            self._fill_columns()
        self.banner_var.set(notice or "")
        self.banner.grid() if notice else self.banner.grid_remove()
        self._buttons()

    def validate(self):
        if self.page != 2:
            self.go(self.page + 1)
            return False
        try:
            self.plan = self.assistant.plan()
        except RepeatError as error:
            self.go(1, notice=error_text(error))
            return False
        return True

    def apply(self):
        self.result = self.plan
