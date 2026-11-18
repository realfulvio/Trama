"""Visual tokens and ttk styles for the Trama shell (proposal A, "Scientifico compatto").

Everything the shell and the data grid share lives here: palette, type, spacing and the ttk style
sheet. The values come from the approved preview in ``ui-preview/`` (see ``ui-preview/src/mock.css``,
class ``.vA``). Sizes in pixels go through :func:`px` so that they follow the Tk scaling factor, which
is how Windows display scaling of 100 %, 125 % and 150 % reaches a Tk application.
"""
from tkinter import font as tkfont, ttk

# --- palette -------------------------------------------------------------------------------------
APP = "#eef1f4"            # window ground behind panels
CHROME = "#f4f6f8"         # ribbon, status bar, dialogs
CHROME_DEEP = "#e8ecef"    # project strip, hover ground
PANEL = "#fafbfc"          # navigator
PAGE = "#e6eaee"           # ground around a figure
LINE = "#d3dae0"
LINE_STRONG = "#b1bcc5"
TEXT = "#1a2931"
MUTED = "#586874"
ACCENT = "#0a7c76"         # Trama teal
ACCENT_STRONG = "#075f5b"
ACCENT_TINT = "#dcefed"
ON_FILL = "#d5ebe8"        # a pressed or switched-on tool button
ON_LINE = "#8fc4be"
SELECTED_CELL = "#dceeec"
SELECTED_HEADING = "#bfe0dc"
GRID_LINE = "#e1e6ea"
GROUP_LINE = "#b1bcc5"
HEADING = "#eef1f4"
ACTIVE_CELL = "#10303b"
EXCLUDED = "#8a5a1c"
BLANK = "#fbfcfd"
BLANK_LINE = "#e9edf0"
ERROR = "#b3261e"
ERROR_TINT = "#fdf2f1"
DISABLED = "#a3afb7"
DISABLED_FILL = "#f1f3f5"
UNSAVED = "#df6443"
SERIES = ("#0c9c92", "#e8795d", "#6757a3", "#c99a1c", "#3f7fb5", "#8a8f98")  # the graph defaults, in order
SURFACE = CHROME
ICON_INK = "#3a4e5a"

# The standard palette remains available to users who prefer the familiar workspace;
# it never changes plot palettes, analysis recipes or the contents of a project.
_STANDARD = {key: value for key, value in globals().copy().items()
             if key.isupper() and isinstance(value, str)}
_MODERN = dict(APP="#eef2f4", CHROME="#ffffff", CHROME_DEEP="#eef2f4", PANEL="#f7f9fa",
               PAGE="#eef2f4", LINE="#e1e6ea", LINE_STRONG="#b9c6ce", TEXT="#17242d",
               MUTED="#5a6873", ACCENT="#0b7a73", ACCENT_STRONG="#075e58", ACCENT_TINT="#e2f2ef",
               ON_FILL="#d8eeea", ON_LINE="#85c4ba", SELECTED_CELL="#e0f2ed",
               SELECTED_HEADING="#bbdfd7", GRID_LINE="#e4e9ed", GROUP_LINE="#c4d2d8",
               HEADING="#f1f5f6", ACTIVE_CELL="#00635d", SURFACE="#ffffff", ICON_INK="#253d4a")


def is_modern():
    return _state.get("theme", "standard") == "modern"


def select_theme(name):
    """Reset every shared token before applying a named variant (also useful in tests)."""
    if name not in ("standard", "modern"):
        raise ValueError("Unknown interface theme")
    globals().update(_STANDARD)
    if name == "modern":
        globals().update(_MODERN)
    _state["theme"] = name


def group_heading_fill(band):
    if not is_modern() or not band.startswith("Group "):
        return HEADING
    index = 0
    for letter in band[6:]:
        if not "A" <= letter <= "Z":
            return HEADING
        index = index * 26 + ord(letter) - ord("A") + 1
    return ("#d9eee8", "#fbe4df", "#e9e3f5", "#f6edd3")[(index - 1) % 4]


FAMILIES = ("Segoe UI", "Selawik", "Inter", "DejaVu Sans")

_state = {"family": "Segoe UI", "scale": 1.0}


def family():
    """The UI font: Segoe UI on Windows, the first installed substitute elsewhere."""
    return _state["family"]


def scale():
    return _state["scale"]


def px(value):
    """A length in 100 % pixels, scaled to the current display."""
    return max(1, round(value * _state["scale"]))


def icon_size():
    factor = _state["scale"]
    return 16 if factor < 1.2 else 20 if factor < 1.45 else 24 if factor < 1.8 else 32


def font(size=9, weight="normal", slant="roman"):
    """A Tk font tuple in the UI family (points follow the Tk scaling factor by themselves)."""
    parts = [family(), size]
    flags = [name for name, on in (("bold", weight == "bold"), ("italic", slant == "italic")) if on]
    return tuple(parts + flags)


def detect(root):
    """Read the font and the display scale from ``root``. Call once before building widgets."""
    installed = {name.casefold(): name for name in tkfont.families(root)}
    _state["family"] = next((installed[name.casefold()] for name in FAMILIES if name.casefold() in installed),
                            tkfont.nametofont("TkDefaultFont", root).actual("family"))
    _state["scale"] = max(1.0, root.winfo_fpixels("1i") / 96.0)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
                 "TkTooltipFont", "TkFixedFont"):
        if name != "TkFixedFont":
            tkfont.nametofont(name, root).configure(family=family(), size=9)


def configure(root, theme="standard"):
    """Create the ttk style sheet for the whole application."""
    select_theme(theme)
    detect(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    ui = font
    flat = dict(bordercolor=CHROME, lightcolor=CHROME, darkcolor=CHROME)

    style.configure(".", font=ui(9))
    style.configure("TFrame", background=SURFACE)
    style.configure("TLabel", background=SURFACE, foreground=TEXT)
    style.configure("TCheckbutton", background=SURFACE, foreground=TEXT, focuscolor=ACCENT)
    style.configure("TRadiobutton", background=SURFACE, foreground=TEXT, focuscolor=ACCENT)
    style.configure("TLabelframe", background=SURFACE, bordercolor=LINE_STRONG)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=TEXT, font=ui(9, "bold"))
    style.configure("TSeparator", background=LINE)
    style.configure("TButton", padding=(px(9), px(3)), background="#ffffff", foreground=TEXT,
                    bordercolor=LINE_STRONG, lightcolor="#ffffff", darkcolor="#ffffff", focuscolor=ACCENT)
    style.map("TButton", background=[("disabled", DISABLED_FILL), ("pressed", ON_FILL), ("active", CHROME_DEEP)],
              foreground=[("disabled", DISABLED)], bordercolor=[("disabled", LINE), ("focus", ACCENT)],
              lightcolor=[("pressed", ON_FILL), ("active", CHROME_DEEP)], darkcolor=[("pressed", ON_FILL), ("active", CHROME_DEEP)])
    style.configure("Action.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT_STRONG,
                    lightcolor=ACCENT, darkcolor=ACCENT, font=ui(9, "bold"), focuscolor="#ffffff")
    style.map("Action.TButton", background=[("disabled", DISABLED_FILL), ("pressed", "#064b48"), ("active", ACCENT_STRONG)],
              foreground=[("disabled", DISABLED)], lightcolor=[("pressed", "#064b48"), ("active", ACCENT_STRONG)],
              darkcolor=[("pressed", "#064b48"), ("active", ACCENT_STRONG)], bordercolor=[("focus", ACTIVE_CELL)])
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground="#ffffff", foreground=TEXT, bordercolor=LINE_STRONG,
                        lightcolor="#ffffff", darkcolor="#ffffff", padding=(px(4), px(2)), insertcolor=TEXT)
        style.map(name, bordercolor=[("disabled", LINE), ("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  darkcolor=[("focus", ACCENT)], fieldbackground=[("disabled", DISABLED_FILL)],
                  foreground=[("disabled", DISABLED)])
    style.configure("TCombobox", background=CHROME, arrowcolor=MUTED, lightcolor="#ffffff", darkcolor="#ffffff")
    style.map("TCombobox", fieldbackground=[("readonly", "#ffffff"), ("disabled", DISABLED_FILL)],
              background=[("active", CHROME_DEEP)], foreground=[("readonly", TEXT), ("disabled", DISABLED)],
              selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", TEXT)])
    style.configure("Error.TEntry", fieldbackground=ERROR_TINT, bordercolor=ERROR, lightcolor=ERROR, darkcolor=ERROR)
    style.map("Error.TEntry", bordercolor=[("focus", ERROR)], lightcolor=[("focus", ERROR)], darkcolor=[("focus", ERROR)])
    style.configure("Error.TLabel", foreground=ERROR, background=SURFACE)
    style.configure("Hint.TLabel", foreground=MUTED, background=SURFACE)
    style.configure("Inspector.TLabelframe", background=SURFACE, bordercolor=LINE)
    style.configure("Inspector.TLabelframe.Label", background=SURFACE, foreground=TEXT, font=ui(9, "bold"))
    style.configure("Inspector.TCheckbutton", background=SURFACE, foreground=TEXT)
    style.configure("InspectorHead.TLabel", background=HEADING, foreground=TEXT, font=ui(9, "bold"))
    style.configure("InspectorSection.TLabel", background=HEADING, foreground="#33454f", font=ui(8, "bold"))
    style.configure("InspectorFooter.TFrame", background=CHROME)

    style.configure("Treeview", rowheight=px(22), font=ui(9), background="#ffffff", fieldbackground="#ffffff",
                    foreground=TEXT, bordercolor=LINE_STRONG)
    style.configure("Treeview.Heading", font=ui(9, "bold"), background=HEADING, foreground=TEXT, bordercolor=LINE)
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
    style.configure("TNotebook", background=SURFACE, bordercolor=LINE_STRONG, lightcolor=LINE_STRONG)
    style.configure("TNotebook.Tab", padding=(px(12), px(3)), foreground=MUTED, background=SURFACE,
                    bordercolor=LINE_STRONG, lightcolor=SURFACE)
    style.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("active", CHROME_DEEP)],
              foreground=[("selected", TEXT)], lightcolor=[("selected", ACCENT)], font=[("selected", ui(9, "bold"))])
    for orientation in ("Horizontal", "Vertical"):
        scrollbar = f"{orientation}.TScrollbar"
        style.configure(scrollbar, troughcolor=CHROME, background="#c3ccd3", bordercolor=CHROME,
                        lightcolor="#c3ccd3", darkcolor="#c3ccd3", arrowcolor=MUTED, gripcount=0)
        style.map(scrollbar, background=[("active", "#a9b6bf"), ("pressed", "#93a3ae")],
                  lightcolor=[("active", "#a9b6bf")], darkcolor=[("active", "#a9b6bf")])
    style.configure("TPanedwindow", background=LINE_STRONG)
    style.configure("Sash", sashthickness=px(5), gripcount=0, background=CHROME, bordercolor=LINE_STRONG,
                    lightcolor=CHROME, darkcolor=CHROME)

    # --- shell: ribbon, project strip, navigator, status bar
    style.configure("Ribbon.TFrame", background=CHROME)
    style.configure("RibbonRule.TFrame", background=LINE)
    style.configure("StatusRule.TFrame", background=LINE_STRONG)
    style.configure("Ribbon.TLabel", background=CHROME, foreground=MUTED, font=ui(8))
    style.configure("RibbonGroup.TLabel", background=CHROME, foreground=MUTED, font=ui(8))
    style.configure("Ribbon.TButton", padding=(px(4), px(2)), background=CHROME, foreground=TEXT, font=ui(9),
                    anchor="w", **flat)
    style.map("Ribbon.TButton", background=[("disabled", CHROME), ("pressed", ON_FILL), ("active", CHROME_DEEP)],
              foreground=[("disabled", DISABLED)], bordercolor=[("pressed", ON_LINE), ("active", LINE_STRONG)],
              lightcolor=[("pressed", ON_FILL), ("active", CHROME_DEEP)],
              darkcolor=[("pressed", ON_FILL), ("active", CHROME_DEEP)])
    style.configure("Lead.Ribbon.TButton", padding=(px(6), px(3), px(6), px(2)), anchor="center")
    style.configure("Primary.Ribbon.TButton", padding=(px(8), px(3), px(8), px(2)), background=ACCENT,
                    foreground="#ffffff", bordercolor=ACCENT_STRONG, lightcolor=ACCENT, darkcolor=ACCENT,
                    font=ui(9, "bold"), anchor="center")
    style.map("Primary.Ribbon.TButton", background=[("pressed", "#064b48"), ("active", ACCENT_STRONG)],
              lightcolor=[("pressed", "#064b48"), ("active", ACCENT_STRONG)],
              darkcolor=[("pressed", "#064b48"), ("active", ACCENT_STRONG)], foreground=[("disabled", DISABLED)])
    style.configure("SectionActive.TButton", padding=(px(4), px(2)), background=ON_FILL, foreground=TEXT,
                    bordercolor=ON_LINE, lightcolor=ON_FILL, darkcolor=ON_FILL, font=ui(9))
    style.map("SectionActive.TButton", background=[("active", "#c4e1dd"), ("pressed", "#b5d8d3")],
              lightcolor=[("active", "#c4e1dd")], darkcolor=[("active", "#c4e1dd")])
    style.configure("ProjectStrip.TFrame", background=CHROME_DEEP)
    style.configure("Projects.TNotebook", background=CHROME_DEEP, borderwidth=0, tabmargins=(0, px(3), 0, 0),
                    bordercolor=LINE, lightcolor=CHROME_DEEP, darkcolor=CHROME_DEEP)
    style.configure("Projects.TNotebook.Tab", padding=(px(14), px(3)), font=ui(9), foreground=MUTED,
                    background=CHROME_DEEP, bordercolor=CHROME_DEEP, lightcolor=CHROME_DEEP)
    style.map("Projects.TNotebook.Tab", background=[("selected", "#ffffff"), ("active", CHROME)],
              foreground=[("selected", TEXT)], bordercolor=[("selected", LINE_STRONG)],
              lightcolor=[("selected", ACCENT)], font=[("selected", ui(9, "bold"))])
    style.configure("ProjectTool.TButton", padding=(px(6), px(1)), width=2, background=CHROME_DEEP, foreground=MUTED,
                    bordercolor=CHROME_DEEP, lightcolor=CHROME_DEEP, darkcolor=CHROME_DEEP, font=ui(11))
    style.map("ProjectTool.TButton", background=[("disabled", CHROME_DEEP), ("active", LINE)],
              foreground=[("disabled", DISABLED), ("active", TEXT)])
    style.configure("Status.TLabel", background=CHROME, foreground=MUTED, font=ui(9))
    style.configure("SheetTitle.TLabel", foreground=TEXT, font=ui(14, "bold"))
    style.configure("SheetKind.TLabel", foreground=MUTED, font=ui(9))
    style.configure("Navigator.Treeview", rowheight=px(22), font=ui(9), background=PANEL, fieldbackground=PANEL,
                    foreground=TEXT, borderwidth=0, indent=px(14))
    style.map("Navigator.Treeview", background=[("selected", SELECTED_CELL)], foreground=[("selected", TEXT)])
    style.configure("NavSearch.TEntry", fieldbackground="#ffffff", bordercolor=LINE_STRONG, padding=(px(5), px(2)),
                    lightcolor="#ffffff", darkcolor="#ffffff")
    style.map("NavSearch.TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])

    # --- start page (table setup)
    style.configure("SetupRail.TFrame", background="#0f3440")
    style.configure("SetupRail.TLabel", background="#0f3440", foreground="#68d6c9", font=ui(9, "bold"))
    style.configure("SetupBrand.TLabel", background="#0f3440", foreground="#ffffff", font=ui(16, "bold"))
    style.configure("SetupVersion.TLabel", background="#0f3440", foreground="#a4c6d2", font=ui(9))
    style.configure("SetupLink.TButton", padding=(px(5), px(4)), background="#0f3440", foreground="#f2f7fa",
                    bordercolor="#36606d", lightcolor="#0f3440", darkcolor="#0f3440", anchor="w")
    style.map("SetupLink.TButton", background=[("active", "#1d4c5a"), ("pressed", "#1d4c5a")],
              lightcolor=[("active", "#1d4c5a")], darkcolor=[("active", "#1d4c5a")])
    style.configure("SetupBody.TFrame", background="#ffffff")
    style.configure("SetupBody.TLabel", background="#ffffff", foreground=MUTED)
    style.configure("SetupCaption.TLabel", background="#ffffff", foreground=MUTED, font=ui(9, "bold"))
    style.configure("SetupTitle.TLabel", background="#ffffff", foreground=TEXT, font=ui(14, "bold"))
    style.configure("Setup.TRadiobutton", background="#ffffff", foreground=TEXT)
    style.configure("Setup.Treeview", rowheight=px(19), font=ui(9))
    style.configure("DialogTitle.TLabel", font=ui(10, "bold"))
    style.configure("ErrorBanner.TFrame", background=ERROR_TINT)
    style.configure("ErrorBanner.TLabel", background=ERROR_TINT, foreground=ERROR)
    root.configure(background=SURFACE)
    # Plain tk containers (dialog bodies, panes) take the chrome colour instead of the Tk default grey.
    root.option_add("*Toplevel.background", SURFACE, 20)
    root.option_add("*Frame.background", SURFACE, 20)
    if is_modern():
        # More breathing room in navigation and headings; numerical grid density stays useful.
        style.configure("ModernNav.TLabel", background=PANEL, foreground=TEXT, font=ui(10, "bold"))
        style.configure("Navigator.Treeview", rowheight=px(29), font=ui(10), indent=px(16))
        style.configure("SheetTitle.TLabel", font=ui(19, "bold"))
        style.configure("SheetKind.TLabel", font=ui(10))
        style.configure("TNotebook.Tab", padding=(px(18), px(7)))
        style.configure("Projects.TNotebook.Tab", padding=(px(17), px(6)))
        style.configure("TButton", padding=(px(11), px(5)))
        style.configure("AnalysisPicker.TFrame", background=PANEL)
        style.configure("AnalysisPicker.TLabel", background=PANEL, foreground=TEXT, font=ui(10, "bold"))
        style.configure("Analysis.Treeview", background=PANEL, fieldbackground=PANEL, rowheight=px(26),
                        bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, indent=px(13))
        style.map("Analysis.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        style.configure("AnalysisTitle.TLabel", foreground=TEXT, font=ui(15, "bold"))
        style.configure("Analysis.TNotebook", bordercolor=LINE, lightcolor=LINE)
        style.configure("Analysis.TNotebook.Tab", padding=(px(12), px(6)))
        style.configure("AnalysisFooter.TFrame", background=PANEL)
        style.configure("Modern.Ribbon.TButton", padding=(px(8), px(5)), font=ui(9),
                        background=CHROME, foreground=TEXT, borderwidth=0,
                        bordercolor=CHROME, lightcolor=CHROME, darkcolor=CHROME)
        style.configure("ModernPrimary.Ribbon.TButton", padding=(px(13), px(5)), font=ui(9, "bold"),
                        background=ACCENT, foreground="#ffffff", bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("ModernPrimary.Ribbon.TButton", background=[("disabled", DISABLED_FILL),
                  ("pressed", ACCENT_STRONG), ("active", ACCENT_STRONG)],
                  foreground=[("disabled", DISABLED)])
        style.configure("Modern.TMenubutton", padding=(px(7), px(5)), background=CHROME,
                        foreground=TEXT, borderwidth=0, font=ui(9))
        for name, active, ink in (("Modern", ACCENT_TINT, ACCENT_STRONG),
                                  ("ModernContext", "#fbefe9", "#7a2e12")):
            tab = name + ".Tab.TButton"
            style.configure(tab, padding=(px(8), px(6)), background=CHROME,
                            bordercolor=CHROME, lightcolor=CHROME, darkcolor=CHROME,
                            foreground=MUTED, focuscolor=ACCENT, font=ui(9, "bold"))
            style.map(tab, background=[("selected", active), ("active", CHROME_DEEP)],
                      foreground=[("selected", ink), ("active", TEXT)],
                      bordercolor=[("focus", ACCENT), ("selected", active), ("active", CHROME_DEEP)],
                      lightcolor=[("selected", active)], darkcolor=[("selected", active)])
        style.configure("InspectorHead.TLabel", background=PANEL, font=ui(12, "bold"), padding=(8, 8))
        style.configure("InspectorSection.TLabel", background=PANEL, font=ui(10, "bold"), padding=(6, 5))
        style.configure("Sash", sashthickness=px(3))
    return style
