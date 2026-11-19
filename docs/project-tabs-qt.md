# Several projects in one window (Qt)

The Qt window opens each project in its own tab, above the command bar. A tab keeps its own data, results, graphs,
layouts, Info sheets, undo history and unsaved state, so projects never mix, even when they use the same sheet
names and the same internal identifiers.

## Open, create and close

- **New project** (Ctrl+N, or the **+** beside the last tab) adds an empty tab.
- **Open** (Ctrl+O), a file dropped on the window, or a file named on the command line opens a project in a new tab.
  The first, empty tab is reused. Opening a project that is already open shows its tab and loses nothing, even if
  the path is spelled differently or reached through a link.
- **Import** and data files (CSV, TSV, text, XLSX) add their tables to the active tab, as before.
- **Close project** (Ctrl+W or Ctrl+F4, or the × on a tab) asks Save, Discard or Cancel only for that project.
  If saving fails or you cancel, the project and its selection stay. Closing the last tab leaves one empty tab.
- Closing the window asks about every project with changes first, one tab after the other, and only then saves or
  closes anything. Cancel (or a save that fails) keeps the window and all its tabs. A tab with unsaved changes is marked with **•** and the tooltip says so.
- Up to six projects are open at once, as in the classic window.

## Switching

Click a tab, or use **Ctrl+Tab** and **Ctrl+Shift+Tab**. Each tab returns to the sheet you left, with the same
current cell, scroll position, result tab and Inspector choice. An Inspector draft, a cell being typed and Info
notes are stored in their own project first; if you cancel the question about an Inspector draft you stay on the
original tab with the original draft.

## While a calculation runs

Calculations stay one at a time. Until one ends, tabs, New, Open and Close are disabled; **Cancel calculation**
stays available. A file that arrives meanwhile (dropped on the window, command line) opens when the calculation
ends. Closing the window during a calculation cancels it, then closes the window (asking about unsaved projects).

## Save as and tab names

**Save as** never overwrites a project that is open in another tab: choose another file or close that project
first. Tabs with the same name show the folder that tells them apart; the tooltip shows the full path.

## Files

Tabs are session state. A `.alab` file holds one project, exactly as before; nothing about the tabs is stored in it
and preferences are unchanged.
