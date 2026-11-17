"""Interface language for the main window: catalogs, translation and the user preference.

Only display text goes through this module. Menu dispatch, recipe fields, table formats and
the .alab metadata keep their English identifiers, so a translation never reaches a project.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "it")
# Always shown in their own language so anyone can find the way back to English.
LANGUAGE_NAMES = {"en": "English", "it": "Italiano"}
PREFERENCES_FILE = "preferences.json"

_EN = {
    "arrange.title": "Arrange drawing objects",
    "command.arrange_shapes": "Arrange drawing objects…",
    "arrange.hint": "Select two or more drawings (Ctrl/Shift for multiple selection). Alignment uses the enclosing selected endpoint bounds; equal spacing requires three objects and enough room.",
    "arrange.horizontal": "Move horizontally",
    "arrange.vertical": "Move vertically",
    "arrange.option.none": "No change",
    "arrange.option.left": "Align left edges",
    "arrange.option.center": "Align centers",
    "arrange.option.right": "Align right edges",
    "arrange.option.top": "Align top edges",
    "arrange.option.middle": "Align middle",
    "arrange.option.bottom": "Align bottom edges",
    "arrange.option.distribute": "Equal spacing",
    "arrange.error.selection": "Select at least two distinct native drawing objects.",
    "arrange.error.three": "Select at least three objects for equal spacing.",
    "arrange.error.mode": "Choose one of the available alignment options.",
    "arrange.error.space": "There is not enough room between the outer objects for non-overlapping equal gaps.",
    "arrange.error.domain": "The arrangement would produce coordinates outside the supported axis domain.",
    "shape.hatch_color": "Pattern color", "shape.error.hatch_color": "Enter a valid pattern color, or leave blank to follow the border.",
    "shape.context.pattern_color": "Pattern color…", "shape.context.pattern_follow": "Use border color for pattern",
    "shape.clipboard.copy": "Copy drawing", "shape.clipboard.cut": "Cut drawing",
    "shape.clipboard.paste": "Paste drawing", "shape.clipboard.copied": "Drawing copied.",
    "shape.clipboard.pasted": "Drawing pasted. Undo/Redo affects this graph.",
    "shape.clipboard.select": "Select a native drawing to copy or cut.",
    "shape.clipboard.invalid": "The clipboard does not contain a supported Trama drawing.",
    # Menu headers.
    "menu.file": "File", "menu.edit": "Edit", "menu.view": "View", "menu.insert": "Insert",
    "menu.analyze": "Analyze", "menu.change": "Change", "menu.arrange": "Arrange",
    "menu.family": "Family", "menu.tools": "Tools",
    # Menu commands (File).
    "command.new_project": "New project", "command.new_table": "New table", "command.open": "Open…",
    "command.import_into_project": "Import into project…", "command.save_project": "Save project",
    "command.save_project_as": "Save project as…", "command.export": "Export…",
    "command.export_with_options": "Export with options…",
    "command.export_multiple_pdf": "Export multiple sheets to PDF…",
    "command.close_project": "Close project", "command.exit": "Exit",
    # Edit.
    "command.undo": "Undo", "command.redo": "Redo", "command.cut_cells": "Cut cells",
    "command.copy_cells": "Copy cells", "command.paste_into_table": "Paste into table",
    "command.paste_special": "Paste Special…", "command.paste_transpose": "Paste Transpose",
    "command.clear_selected_cells": "Clear selected cells", "command.paste_as_new_table": "Paste as new table",
    "command.toggle_exclusion": "Exclude / include selected cell", "command.language": "Language…",
    # View.
    "command.toggle_navigator": "Show or hide Navigator",
    "command.toggle_data_results": "Show or hide Data + Results", "command.sheet_gallery": "Sheet gallery",
    "command.previous_sheet": "Previous sheet", "command.next_sheet": "Next sheet",
    # Insert.
    "command.new_table_dialog": "New table…", "command.new_info": "New Info sheet…", "command.add_row": "Add row",
    "command.add_column": "Add column…", "command.calculated_column": "Calculated column…",
    "command.new_graph": "New graph…", "command.pairwise": "Pairwise Comparisons…", "command.compact_letters": "Compact Letter Display…",
    "command.graph_annotations": "Graph annotations…", "command.graph_shapes": "Graph shapes…",
    "command.new_layout": "New layout…",
    # Analyze, Change, Arrange.
    "command.analyze_data": "Analyze data…", "command.change_parameters": "Change parameters…",
    "command.load_example": "Load example", "command.format_graph": "Format graph…",
    "command.edit_layout": "Edit layout…", "command.info_properties": "Info sheet properties…",
    # Family.
    "command.source_table": "Source data table", "command.family_gallery": "Family gallery",
    "command.linked_info": "Linked Info sheet", "command.analysis_results": "Analysis results",
    "command.graphs": "Graphs",
    # Tools.
    "command.power": "Power and sample size…", "command.simulate": "Simulate data…",
    "command.monte_carlo": "Monte Carlo study…", "command.plot_function": "Plot a function…",
    "command.transpose_xy": "Transpose X and Y…",
    # Ribbon groups and buttons.
    "ribbon.sheet": "Sheet", "ribbon.undo_group": "Undo", "ribbon.clipboard": "Clipboard",
    "ribbon.analysis": "Analysis", "ribbon.import_export": "Import / Export", "ribbon.graph": "Graph",
    "ribbon.new": "New", "ribbon.open": "Open", "ribbon.save": "Save", "ribbon.save_as": "Save as…",
    "ribbon.exclude": "Exclude / include cell", "ribbon.formula": "Formula…", "ribbon.copy": "Copy",
    "ribbon.paste": "Paste", "ribbon.linear": "Linear regression", "ribbon.nonlinear": "Nonlinear regression",
    "ribbon.descriptive": "Descriptive statistics", "ribbon.analyze": "Analyze…",
    "ribbon.correlation": "Correlation matrix", "ribbon.format": "Format", "ribbon.add_formula": "Add formula…",
    "ribbon.import": "Import…", "ribbon.export": "Export", "ribbon.layout": "Layout",
    # Bottom bar.
    "bar.linked_sheets": "Linked sheets", "bar.data_tables": "Data tables", "bar.info_sheets": "Info sheets",
    "bar.results": "Results", "bar.layouts": "Layouts", "bar.cancel_calculation": "Cancel calculation",
    "bar.cell_hint": "Shift + arrows to select · Ctrl+C / Ctrl+V · F2 to edit",
    "bar.view_family_gallery": "View Family Gallery",
    # Navigator.
    "nav.search": "Search sheets…", "nav.family": "Family", "nav.search_results": "Search results",
    "nav.data_results": "Data + Results", "nav.data_tables": "Data Tables", "nav.info": "Info",
    "nav.results": "Results", "nav.graphs": "Graphs", "nav.layouts": "Layouts",
    "nav.new_data_table": "New Data Table…", "nav.new_info_sheet": "New Info Sheet…",
    "nav.new_analysis": "New Analysis…", "nav.new_graph": "New Graph…", "nav.new_layout": "New Layout…",
    "nav.hide_data_results": "Hide Data + Results", "nav.show_data_results": "Show Data + Results",
    "nav.expand_all": "Expand all folders", "nav.collapse_all": "Collapse all folders",
    # Project strip.
    "project.untitled": "Untitled {number}", "project.new_hint": "New project · Ctrl+Shift+N",
    "project.close_hint": "Close project · Ctrl+W",
    # Start screen and New table.
    "setup.version": "Version {version}", "setup.new_data_table": "NEW DATA TABLE",
    "setup.existing_project": "EXISTING PROJECT", "setup.open_file": "Open a file…",
    "setup.new_project_info": "New project Info…", "setup.worksheet_preview": "WORKSHEET PREVIEW",
    "setup.graph_example": "GRAPH EXAMPLE", "setup.data_table": "Data table",
    "setup.enter_data": "Enter or import data into a new table", "setup.sample_data": "Start with sample data",
    "setup.x_numbers": "X:  Numbers", "setup.data_sets": "Data sets", "setup.replicates": "Replicates",
    "setup.row_titles": "Row titles", "setup.create": "Create", "setup.cancel": "Cancel",
    "setup.heading.xy": "XY tables", "setup.heading.column": "Column tables",
    "setup.heading.grouped": "Grouped tables", "setup.heading.contingency": "Contingency tables",
    "setup.heading.survival": "Survival tables", "setup.heading.parts_of_whole": "Parts of whole tables",
    "setup.heading.multivariable": "Multiple variables tables", "setup.heading.nested": "Nested tables",
    "setup.preview_note": "Preview shows {shown} of {total} columns",
    "setup.select_sample": "Select a sample data set", "setup.options": "Options",
    "setup.structure": "Table structure", "setup.dialog_title": "New table and graph",
    # Table formats, bound to their canonical codes.
    "table.xy": "XY", "table.column": "Column", "table.grouped": "Grouped", "table.contingency": "Contingency",
    "table.survival": "Survival", "table.parts_of_whole": "Parts of whole",
    "table.multivariable": "Multiple variables", "table.nested": "Nested",
    "table_detail.xy": "Pair an X value with one or more Y series. Use this for curves and regression.",
    "table_detail.column": "Place each group in its own column. Use this for comparisons and distributions.",
    "table_detail.grouped": "Organize observations by row and column groups, with separate replicate columns.",
    "table_detail.contingency": "Enter whole counts for each combination of group and outcome.",
    "table_detail.survival": "Record a time, event indicator and group for each subject.",
    "table_detail.parts_of_whole": "Enter one value per category to plot each part as a share of the total.",
    "table_detail.multivariable": "Record each observation as a row with numeric or categorical variables.",
    "table_detail.nested": ("Give each independent subject or unit its own subcolumn and stack its "
                            "repeated measurements."),
    "format.xy_single": "A single Y value for each X", "format.replicates": "Replicates in side-by-side subcolumns",
    "format.xy_mean_sd_n": "Precalculated mean, SD and N", "format.mean_sd_n": "Mean, SD and N",
    "format.mean_sem": "Mean and SEM", "format.mean_distances": "Mean with minus and plus distances",
    "format.mean_limits": "Mean with lower and upper limits",
    "example.curves": "Curves and regression", "example.replicates": "Replicates and error bars",
    "example.dose_response": "Dose–response with two data sets",
    "example.duplicates": "Measure duplicate observations",
    "example.means": "Enter means, SD and sample sizes",
    "example.column": "Compare a control and a treated group", "example.grouped": "Repeated measurements by week",
    "example.contingency": "Treatment and event counts", "example.survival": "Time to event in two groups",
    "example.parts_of_whole": "Composition of four categories",
    "example.multivariable": "Subject, measurement and group",
    "example.nested": "Repeated measurements within independent units",
    # Essential states and prompts.
    "status.welcome": "Open a project, import data, or start with the example.",
    "status.opened": "Opened {name}.", "status.saved": "Saved {name}.",
    "status.imported": "Imported {count} data table(s).", "status.info_sheets": "{count} Info sheet(s).",
    "status.unsupported": "Unsupported sheets: {names}",
    "prompt.unsaved_title": "Unsaved data", "prompt.save_changes": 'Save changes to "{name}"?',
    "prompt.project_filetype": "Trama project", "prompt.data_files": "Data and projects",
    "prompt.prism_files": "Legacy project files", "prompt.all_files": "All files",
    "error.alab_name": "Choose a Trama project filename ending in .alab.",
    "error.open_elsewhere": "That project is open in another tab. Choose a different filename.",
    # Multi-page PDF dialog.
    "pdf.title": "Export multiple sheets to PDF",
    "pdf.sheets": "Graphs and layouts (select one or more)",
    "pdf.up": "Move up", "pdf.down": "Move down", "pdf.pages": "Pages",
    "pdf.graph": "Graph", "pdf.layout": "Layout", "pdf.width": "Width (mm)",
    "pdf.transparent": "Transparent background",
    "pdf.width_hint": "Empty width keeps each page at its original size; a width keeps each aspect ratio.",
    "pdf.invalid_width": "Width must be a number in millimetres.",
    "pdf.select": "Select at least one graph or layout.",
    "pdf.one_page": "1 page", "pdf.many_pages": "{count} pages",
    "pdf.order": "{pages}, in this order:\n{order}",
    "pdf.vector": "Native graphs and layout panels retain vector graphics and text.",
    "pdf.images": "Sheets with embedded images: {names}.",
    "layout.export_current_emf": "Export current EMF…",
    "layout.export_original_emf": "File → Export can save the original EMF.",
    "layout.create": "Compose layout", "layout.edit": "Edit layout",
    "layout.name": "Name", "layout.page": "Page", "layout.paper": "Paper", "layout.columns": "Columns",
    "layout.background": "Background", "layout.choose": "Choose…",
    "layout.available": "Available graphs", "layout.panels": "Panels in order",
    "layout.add": "Add →", "layout.remove": "Remove", "layout.up": "Move up", "layout.down": "Move down",
    "layout.panel_limit": "A layout holds up to 12 panels.",
    "layout.select": "Add at least one graph to the layout.",
    "layout.paper.Automatic": "Automatic", "layout.paper.A4 portrait": "A4 portrait",
    "layout.paper.A4 landscape": "A4 landscape", "layout.paper.Letter portrait": "Letter portrait",
    "layout.paper.Letter landscape": "Letter landscape",
    "pdf.stale": "Not calculated, so not listed (open or recalculate them first): {names}.",
    "pdf.imported": "Imported graphs and layouts keep their original export: {names}.",
    "pdf.empty": "There is no calculated native graph or layout in this project.",
    "pdf.wait": "Wait for the current calculation to finish.",
    "pdf.exported": "Exported {pages} to {name}.",
    # Language dialog.
    "language.title": "Language / Lingua",
    "language.note": "The language is applied the next time Trama starts.",
    "language.ok": "OK", "language.cancel": "Cancel",
    "language.saved": "Language saved. It applies at the next start.",
    "language.unchanged": "Language unchanged.",
    "language.error": "The language preference could not be saved: {error}",
    # Logistic regression dialog. English text matches the stored option keys.
    "analysis.logistic.tab": "Diagnostics and profiles",
    "analysis.logistic.diagnostics": "Logistic diagnostics",
    "analysis.logistic.cutoff": "Logistic cutoff",
    "analysis.logistic.profiles": "Logistic profiles",
    "analysis.logistic.confidence": "Logistic confidence (%)",
    "analysis.logistic.hint": "Up to 12 profiles. Predictions use this fit and its reference levels.",
    # PCA graph dialog. English text matches the stored option keys.
    "analysis.pca.tab": "Graph",
    "analysis.pca.display": "Graph display",
    "analysis.pca.horizontal": "Horizontal PC",
    "analysis.pca.vertical": "Vertical PC",
    "analysis.pca.label": "Label column",
    "analysis.pca.show": "Show row labels",
    # PCA component selection. English text matches the stored option keys.
    "pca.select.selection": "Selection",
    "pca.select.retained": "Retained components",
    "pca.select.threshold": "Eigenvalue threshold",
    "pca.select.cumulative": "Cumulative variance (%)",
    "pca.select.simulations": "Parallel simulations",
    "pca.select.seed": "Parallel seed",
    "pca.select.percentile": "Parallel percentile (%)",
    "pca.select.save": "Save parallel simulations",
    "pca.select.choice.all": "All",
    "pca.select.choice.fixed": "Fixed number",
    "pca.select.choice.threshold": "Eigenvalue threshold",
    "pca.select.choice.cumulative": "Cumulative variance",
    "pca.select.choice.parallel": "Parallel analysis",
    # Composition segment style dialog.
    "parts.style.title": "Segment styles",
    "parts.style.edit_button": "Edit slices…",
    "parts.style.row_hint": "Color, distance and visibility follow the row number.",
    "parts.style.note": ("Styles follow the sheet row number. Inserting or deleting rows changes which category is styled. "
                         "Two rows with the same label do not share a style."),
    "parts.style.color": "Color",
    "parts.style.pick": "Pick…",
    "parts.style.explode": "Explode",
    "parts.style.visible": "Visible",
    "parts.style.restore": "Restore default",
    "parts.style.explode_hint": "Explode is a fraction of the radius, from 0 to 0.35.",
    "parts.style.error_title": "Check the slice",
    # XY error bars dialog.
    "xy_error.group.x": "X errors",
    "xy_error.group.y": "Y errors",
    "xy_error.group.appearance": "Error appearance",
    "xy_error.field.x": "X",
    "xy_error.field.y": "Y",
    "xy_error.field.group": "Group",
    "xy_error.field.x_distance": "Symmetric X error distance",
    "xy_error.field.x_lower": "X lower error",
    "xy_error.field.x_upper": "X upper error",
    "xy_error.field.x_values": "X error values",
    "xy_error.field.x_direction": "X error direction",
    "xy_error.field.y_lower": "Y lower error",
    "xy_error.field.y_upper": "Y upper error",
    "xy_error.field.y_values": "Y error values",
    "xy_error.field.y_direction": "Y error direction",
    "xy_error.field.cap_size": "Error cap size (pt)",
    "xy_error.field.width": "Error width (pt)",
    "xy_error.field.color": "Error color",
    "xy_error.field.line_style": "Error line style",
    "xy_error.choice.distances": "Distances",
    "xy_error.choice.endpoints": "Endpoints",
    "xy_error.choice.both": "Both",
    "xy_error.choice.negative": "Negative only",
    "xy_error.choice.positive": "Positive only",
}

_IT = {
    "arrange.title": "Disponi le forme del grafico",
    "command.arrange_shapes": "Disponi forme del grafico…",
    "arrange.hint": "Seleziona almeno due forme (Ctrl/Maiusc per la selezione multipla). Allinea rispetto al rettangolo che le racchiude; per la spaziatura servono tre forme e spazio sufficiente.",
    "arrange.horizontal": "Sposta orizzontalmente",
    "arrange.vertical": "Sposta verticalmente",
    "arrange.option.none": "Nessuna modifica",
    "arrange.option.left": "Allinea bordi sinistri",
    "arrange.option.center": "Allinea centri",
    "arrange.option.right": "Allinea bordi destri",
    "arrange.option.top": "Allinea bordi superiori",
    "arrange.option.middle": "Allinea al centro in verticale",
    "arrange.option.bottom": "Allinea bordi inferiori",
    "arrange.option.distribute": "Spaziatura uguale",
    "arrange.error.selection": "Seleziona almeno due forme native distinte.",
    "arrange.error.three": "Seleziona almeno tre forme per la spaziatura uguale.",
    "arrange.error.mode": "Scegli una delle opzioni di allineamento disponibili.",
    "arrange.error.space": "Lo spazio tra le forme esterne non basta per intervalli uguali senza sovrapposizioni.",
    "arrange.error.domain": "La disposizione produrrebbe coordinate fuori dal dominio degli assi supportato.",
    "shape.hatch_color": "Colore del motivo", "shape.error.hatch_color": "Inserisci un colore valido per il motivo, oppure lascia vuoto per seguire il contorno.",
    "shape.context.pattern_color": "Colore del motivo…", "shape.context.pattern_follow": "Usa il colore del contorno per il motivo",
    "shape.clipboard.copy": "Copia disegno", "shape.clipboard.cut": "Taglia disegno",
    "shape.clipboard.paste": "Incolla disegno", "shape.clipboard.copied": "Disegno copiato.",
    "shape.clipboard.pasted": "Disegno incollato. Annulla/Ripeti agisce su questo grafico.",
    "shape.clipboard.select": "Seleziona un disegno nativo da copiare o tagliare.",
    "shape.clipboard.invalid": "Gli appunti non contengono un disegno Trama supportato.",
    "menu.file": "File", "menu.edit": "Modifica", "menu.view": "Visualizza", "menu.insert": "Inserisci",
    "menu.analyze": "Analisi", "menu.change": "Cambia", "menu.arrange": "Disponi",
    "menu.family": "Famiglia", "menu.tools": "Strumenti",
    "command.new_project": "Nuovo progetto", "command.new_table": "Nuova tabella", "command.open": "Apri…",
    "command.import_into_project": "Importa nel progetto…", "command.save_project": "Salva progetto",
    "command.save_project_as": "Salva progetto con nome…", "command.export": "Esporta…",
    "command.export_with_options": "Esporta con opzioni…",
    "command.export_multiple_pdf": "Esporta più fogli in PDF…",
    "command.close_project": "Chiudi progetto", "command.exit": "Esci",
    "command.undo": "Annulla", "command.redo": "Ripeti", "command.cut_cells": "Taglia celle",
    "command.copy_cells": "Copia celle", "command.paste_into_table": "Incolla nella tabella",
    "command.paste_special": "Incolla speciale…", "command.paste_transpose": "Incolla trasposto",
    "command.clear_selected_cells": "Cancella celle selezionate",
    "command.paste_as_new_table": "Incolla come nuova tabella",
    "command.toggle_exclusion": "Escludi / includi cella selezionata", "command.language": "Lingua…",
    "command.toggle_navigator": "Mostra/nascondi Navigatore",
    "command.toggle_data_results": "Mostra/nascondi Dati + Risultati", "command.sheet_gallery": "Galleria fogli",
    "command.previous_sheet": "Foglio precedente", "command.next_sheet": "Foglio successivo",
    "command.new_table_dialog": "Nuova tabella…", "command.new_info": "Nuovo foglio Info…",
    "command.add_row": "Aggiungi riga", "command.add_column": "Aggiungi colonna…",
    "command.calculated_column": "Colonna calcolata…", "command.new_graph": "Nuovo grafico…",
    "command.pairwise": "Confronti a coppie…", "command.compact_letters": "Lettere compatte…", "command.new_layout": "Nuovo layout…",
    "command.graph_annotations": "Annotazioni grafico…", "command.graph_shapes": "Forme del grafico…",
    "command.analyze_data": "Analizza dati…", "command.change_parameters": "Cambia parametri…",
    "command.load_example": "Carica esempio", "command.format_graph": "Formatta grafico…",
    "command.edit_layout": "Modifica layout…", "command.info_properties": "Proprietà foglio Info…",
    "command.source_table": "Tabella dati di origine", "command.family_gallery": "Galleria famiglia",
    "command.linked_info": "Foglio Info collegato", "command.analysis_results": "Risultati analisi",
    "command.graphs": "Grafici",
    "command.power": "Potenza e numerosità…", "command.simulate": "Simula dati…",
    "command.monte_carlo": "Studio Monte Carlo…", "command.plot_function": "Traccia una funzione…",
    "command.transpose_xy": "Trasponi X e Y…",
    "ribbon.sheet": "Foglio", "ribbon.undo_group": "Annulla", "ribbon.clipboard": "Appunti",
    "ribbon.analysis": "Analisi", "ribbon.import_export": "Importa/Esporta", "ribbon.graph": "Grafico",
    "ribbon.new": "Nuovo", "ribbon.open": "Apri", "ribbon.save": "Salva", "ribbon.save_as": "Salva con nome…",
    "ribbon.exclude": "Escludi / includi cella", "ribbon.formula": "Formula…", "ribbon.copy": "Copia",
    "ribbon.paste": "Incolla", "ribbon.linear": "Regressione lineare", "ribbon.nonlinear": "Regressione non lineare",
    "ribbon.descriptive": "Statistica descrittiva", "ribbon.analyze": "Analizza…",
    "ribbon.correlation": "Matrice di correlazione", "ribbon.format": "Formato",
    "ribbon.add_formula": "Aggiungi formula…", "ribbon.import": "Importa…", "ribbon.export": "Esporta",
    "ribbon.layout": "Layout",
    "bar.linked_sheets": "Fogli collegati", "bar.data_tables": "Tabelle dati", "bar.info_sheets": "Fogli Info",
    "bar.results": "Risultati", "bar.layouts": "Layout", "bar.cancel_calculation": "Annulla calcolo",
    "bar.cell_hint": "Maiusc + frecce per selezionare · Ctrl+C / Ctrl+V · F2 per modificare",
    "bar.view_family_gallery": "Apri galleria famiglia",
    "nav.search": "Cerca fogli…", "nav.family": "Famiglia", "nav.search_results": "Risultati ricerca",
    "nav.data_results": "Dati + Risultati", "nav.data_tables": "Tabelle dati", "nav.info": "Info",
    "nav.results": "Risultati", "nav.graphs": "Grafici", "nav.layouts": "Layout",
    "nav.new_data_table": "Nuova tabella dati…", "nav.new_info_sheet": "Nuovo foglio Info…",
    "nav.new_analysis": "Nuova analisi…", "nav.new_graph": "Nuovo grafico…", "nav.new_layout": "Nuovo layout…",
    "nav.hide_data_results": "Nascondi Dati + Risultati", "nav.show_data_results": "Mostra Dati + Risultati",
    "nav.expand_all": "Espandi tutte le cartelle", "nav.collapse_all": "Comprimi tutte le cartelle",
    "project.untitled": "Senza titolo {number}", "project.new_hint": "Nuovo progetto · Ctrl+Shift+N",
    "project.close_hint": "Chiudi progetto · Ctrl+W",
    "setup.version": "Versione {version}", "setup.new_data_table": "NUOVA TABELLA DATI",
    "setup.existing_project": "PROGETTO ESISTENTE", "setup.open_file": "Apri un file…",
    "setup.new_project_info": "Nuove Info progetto…", "setup.worksheet_preview": "ANTEPRIMA FOGLIO",
    "setup.graph_example": "ESEMPIO DI GRAFICO", "setup.data_table": "Tabella dati",
    "setup.enter_data": "Inserisci o importa dati in una nuova tabella",
    "setup.sample_data": "Inizia con dati di esempio",
    "setup.x_numbers": "X:  Numeri", "setup.data_sets": "Serie di dati", "setup.replicates": "Repliche",
    "setup.row_titles": "Titoli di riga", "setup.create": "Crea", "setup.cancel": "Annulla",
    "setup.heading.xy": "Tabelle XY", "setup.heading.column": "Tabelle a colonne",
    "setup.heading.grouped": "Tabelle raggruppate", "setup.heading.contingency": "Tabelle di contingenza",
    "setup.heading.survival": "Tabelle di sopravvivenza", "setup.heading.parts_of_whole": "Tabelle parti di un intero",
    "setup.heading.multivariable": "Tabelle a variabili multiple", "setup.heading.nested": "Tabelle annidate",
    "setup.preview_note": "Anteprima di {shown} colonne su {total}",
    "setup.select_sample": "Scegli un set di dati di esempio", "setup.options": "Opzioni",
    "setup.structure": "Struttura della tabella", "setup.dialog_title": "Nuova tabella e grafico",
    "table.xy": "XY", "table.column": "Colonne", "table.grouped": "Raggruppata",
    "table.contingency": "Contingenza", "table.survival": "Sopravvivenza", "table.parts_of_whole": "Parti di un intero",
    "table.multivariable": "Variabili multiple", "table.nested": "Annidata",
    "table_detail.xy": "Associa un valore X a una o più serie Y. Per curve e regressione.",
    "table_detail.column": "Ogni gruppo nella propria colonna. Per confronti e distribuzioni.",
    "table_detail.grouped": "Osservazioni per gruppi di riga e di colonna, con colonne separate per le repliche.",
    "table_detail.contingency": "Conteggi interi per ogni combinazione di gruppo ed esito.",
    "table_detail.survival": "Tempo, indicatore di evento e gruppo per ogni soggetto.",
    "table_detail.parts_of_whole": "Un valore per categoria, per mostrare ogni parte come quota del totale.",
    "table_detail.multivariable": "Ogni osservazione in una riga, con variabili numeriche o categoriche.",
    "table_detail.nested": ("Ogni soggetto o unità indipendente nella propria sottocolonna, con le misure "
                            "ripetute impilate."),
    "format.xy_single": "Un solo valore Y per ogni X", "format.replicates": "Repliche in sottocolonne affiancate",
    "format.xy_mean_sd_n": "Media, DS e N precalcolati", "format.mean_sd_n": "Media, DS e N",
    "format.mean_sem": "Media e SEM", "format.mean_distances": "Media con distanze meno e più",
    "format.mean_limits": "Media con limiti inferiore e superiore",
    "example.curves": "Curve e regressione", "example.replicates": "Repliche e barre di errore",
    "example.dose_response": "Dose–risposta con due serie di dati",
    "example.duplicates": "Misure in doppio",
    "example.means": "Medie, DS e numerosità",
    "example.column": "Confronto tra controllo e trattati", "example.grouped": "Misure ripetute per settimana",
    "example.contingency": "Trattamento e conteggi di eventi", "example.survival": "Tempo all'evento in due gruppi",
    "example.parts_of_whole": "Composizione di quattro categorie",
    "example.multivariable": "Soggetto, misura e gruppo",
    "example.nested": "Misure ripetute in unità indipendenti",
    "status.welcome": "Apri un progetto, importa dati o parti dall'esempio.",
    "status.opened": "Aperto {name}.", "status.saved": "Salvato {name}.",
    "status.imported": "Importate {count} tabelle dati.", "status.info_sheets": "{count} fogli Info.",
    "status.unsupported": "Fogli non supportati: {names}",
    "prompt.unsaved_title": "Dati non salvati", "prompt.save_changes": 'Salvare le modifiche a "{name}"?',
    "prompt.project_filetype": "Progetto Trama", "prompt.data_files": "Dati e progetti",
    "prompt.prism_files": "Progetti in formato precedente", "prompt.all_files": "Tutti i file",
    "error.alab_name": "Scegli un nome di progetto Trama che termini con .alab.",
    "error.open_elsewhere": "Il progetto è aperto in un'altra scheda. Scegli un altro nome di file.",
    "pdf.title": "Esporta più fogli in PDF",
    "pdf.sheets": "Grafici e layout (selezionane uno o più)",
    "pdf.up": "Sposta su", "pdf.down": "Sposta giù", "pdf.pages": "Pagine",
    "pdf.graph": "Grafico", "pdf.layout": "Layout", "pdf.width": "Larghezza (mm)",
    "pdf.transparent": "Sfondo trasparente",
    "pdf.width_hint": "Lascia vuoto per le dimensioni originali; una larghezza mantiene le proporzioni di ogni pagina.",
    "pdf.invalid_width": "La larghezza deve essere un numero in millimetri.",
    "pdf.select": "Seleziona almeno un grafico o un layout.",
    "pdf.one_page": "1 pagina", "pdf.many_pages": "{count} pagine",
    "pdf.order": "{pages}, in questo ordine:\n{order}",
    "pdf.vector": "Grafici e pannelli dei layout nativi conservano testo ed elementi vettoriali.",
    "pdf.images": "Fogli con immagini incorporate: {names}.",
    "layout.export_current_emf": "Esporta EMF corrente…",
    "layout.export_original_emf": "File → Esporta permette di salvare l’EMF originale.",
    "layout.create": "Componi layout", "layout.edit": "Modifica layout",
    "layout.name": "Nome", "layout.page": "Pagina", "layout.paper": "Formato", "layout.columns": "Colonne",
    "layout.background": "Sfondo", "layout.choose": "Scegli…",
    "layout.available": "Grafici disponibili", "layout.panels": "Ordine dei pannelli",
    "layout.add": "Aggiungi →", "layout.remove": "Rimuovi", "layout.up": "Sposta su", "layout.down": "Sposta giù",
    "layout.panel_limit": "Un layout contiene fino a 12 pannelli.",
    "layout.select": "Aggiungi almeno un grafico al layout.",
    "layout.paper.Automatic": "Automatico", "layout.paper.A4 portrait": "A4 verticale",
    "layout.paper.A4 landscape": "A4 orizzontale", "layout.paper.Letter portrait": "Letter verticale",
    "layout.paper.Letter landscape": "Letter orizzontale",
    "pdf.stale": "Fogli non calcolati, esclusi dalla lista (aprili o ricalcolali prima): {names}.",
    "pdf.imported": "I grafici e layout importati conservano la propria esportazione originale: {names}.",
    "pdf.empty": "Il progetto non contiene grafici o layout nativi già calcolati.",
    "pdf.wait": "Attendi la fine del calcolo in corso.",
    "pdf.exported": "PDF esportato in {name} ({pages}).",
    "language.title": "Lingua / Language",
    "language.note": "La lingua si applica al prossimo avvio di Trama.",
    "language.ok": "OK", "language.cancel": "Annulla",
    "language.saved": "Lingua salvata. Si applica al prossimo avvio.",
    "language.unchanged": "Lingua invariata.",
    "language.error": "Impossibile salvare la preferenza della lingua: {error}",
    "analysis.logistic.tab": "Diagnostica e profili",
    "analysis.logistic.diagnostics": "Diagnostica logistica",
    "analysis.logistic.cutoff": "Soglia logistica",
    "analysis.logistic.profiles": "Profili logistici",
    "analysis.logistic.confidence": "Confidenza logistica (%)",
    "analysis.logistic.hint": "Fino a 12 profili. Le previsioni usano il modello stimato e i suoi livelli di riferimento.",
    "analysis.pca.tab": "Grafico",
    "analysis.pca.display": "Vista del grafico",
    "analysis.pca.horizontal": "Componente orizzontale",
    "analysis.pca.vertical": "Componente verticale",
    "analysis.pca.label": "Colonna etichette",
    "analysis.pca.show": "Mostra etichette di riga",
    "pca.select.selection": "Selezione",
    "pca.select.retained": "Componenti trattenute",
    "pca.select.threshold": "Soglia degli autovalori",
    "pca.select.cumulative": "Varianza cumulata (%)",
    "pca.select.simulations": "Simulazioni parallele",
    "pca.select.seed": "Seme parallelo",
    "pca.select.percentile": "Percentile parallelo (%)",
    "pca.select.save": "Salva le simulazioni parallele",
    "pca.select.choice.all": "Tutte",
    "pca.select.choice.fixed": "Numero fisso",
    "pca.select.choice.threshold": "Soglia degli autovalori",
    "pca.select.choice.cumulative": "Varianza cumulata",
    "pca.select.choice.parallel": "Analisi parallela",
    "parts.style.title": "Stili dei segmenti",
    "parts.style.edit_button": "Modifica segmenti…",
    "parts.style.row_hint": "Colore, distanza e visibilità seguono il numero di riga.",
    "parts.style.note": ("Gli stili seguono il numero di riga del foglio. Inserire o eliminare righe cambia "
                         "la categoria associata allo stile. Due righe con la stessa etichetta non condividono lo stile."),
    "parts.style.color": "Colore",
    "parts.style.pick": "Scegli…",
    "parts.style.explode": "Distacco",
    "parts.style.visible": "Visibile",
    "parts.style.restore": "Ripristina predefinito",
    "parts.style.explode_hint": "Il distacco è una frazione del raggio, da 0 a 0.35.",
    "parts.style.error_title": "Controlla il segmento",
    "xy_error.group.x": "Errori X",
    "xy_error.group.y": "Errori Y",
    "xy_error.group.appearance": "Aspetto degli errori",
    "xy_error.field.x": "X",
    "xy_error.field.y": "Y",
    "xy_error.field.group": "Gruppo",
    "xy_error.field.x_distance": "Distanza X simmetrica",
    "xy_error.field.x_lower": "Errore X inferiore",
    "xy_error.field.x_upper": "Errore X superiore",
    "xy_error.field.x_values": "Valori errore X",
    "xy_error.field.x_direction": "Direzione errore X",
    "xy_error.field.y_lower": "Errore Y inferiore",
    "xy_error.field.y_upper": "Errore Y superiore",
    "xy_error.field.y_values": "Valori errore Y",
    "xy_error.field.y_direction": "Direzione errore Y",
    "xy_error.field.cap_size": "Dimensione cappucci (pt)",
    "xy_error.field.width": "Spessore errori (pt)",
    "xy_error.field.color": "Colore errori",
    "xy_error.field.line_style": "Stile linea errori",
    "xy_error.choice.distances": "Distanze",
    "xy_error.choice.endpoints": "Estremi",
    "xy_error.choice.both": "Entrambe",
    "xy_error.choice.negative": "Solo negativa",
    "xy_error.choice.positive": "Solo positiva",
}

# Format Graph and Inspector. Choice labels are display text only: the dialogs keep and store the
# canonical values (linear/log, upper right, marker names, Left/Right, ...).
_GRAPH_EN = {
    "graph.format.title": "Format Graph", "graph.format.appearance": "Appearance", "graph.format.axes": "Axes",
    "annotation.title": "Graph annotations", "annotation.button": "Annotations…",
    "annotation.add": "Add…", "annotation.edit": "Edit…", "annotation.remove": "Remove",
    "annotation.text": "Text", "annotation.units": "Coordinates", "annotation.align": "Alignment",
    "annotation.position": "Text X, Y", "annotation.target": "Arrow X, Y", "annotation.arrow": "Add an arrow",
    "annotation.arrow_short": "Arrow", "annotation.size": "Text size (pt)", "annotation.color": "Color",
    "annotation.option.axes": "Plot fractions (0–1)", "annotation.option.data": "Data (left Y axis)",
    "annotation.option.left": "Left", "annotation.option.center": "Center", "annotation.option.right": "Right",
    "annotation.invalid_fields": "Enter valid coordinates and text size.",
    "annotation.axis_domain": "Choose coordinates within the domain of the current axis scales.",
    "annotation.native": "Select a calculated native graph to add annotations.",
    "annotation.applied": "Graph annotations applied.",
    "annotation.error.text": "Enter annotation text between 1 and 500 characters.",
    "annotation.error.coordinates": "Enter finite X and Y coordinates.",
    "annotation.error.fractions": "Plot fractions must be between 0 and 1.",
    "annotation.error.size": "Enter a text size between 4 and 72 points.",
    "annotation.error.color": "Enter a valid text color.",
    "shape.title": "Graph shapes", "shape.button": "Graph shapes…",
    "shape.add": "Add…", "shape.edit": "Edit…", "shape.duplicate": "Duplicate",
    "shape.remove": "Remove", "shape.clear": "Clear all", "shape.up": "Up", "shape.down": "Down",
    "shape.preview": "Preview", "shape.kind": "Shape", "shape.units": "Coordinates",
    "shape.point1": "First point (X1, Y1)", "shape.point2": "Second point (X2, Y2)", "shape.points": "Points",
    "shape.stroke": "Stroke color", "shape.width": "Line width (pt)", "shape.line_style": "Line style",
    "shape.fill": "Fill color", "shape.no_fill": "No fill", "shape.alpha": "Opacity (0–1)", "shape.layer": "Layer",
    "shape.fill_hint": "Leave fill blank for a transparent interior. Line shapes do not use fill.",
    "shape.axis_hint": "Data coordinates use the primary X and left Y axes.",
    "shape.option.line": "Line", "shape.option.rectangle": "Rectangle", "shape.option.ellipse": "Ellipse",
    "shape.option.axes": "Plot fractions (0–1)", "shape.option.data": "Data (left Y axis)",
    "shape.option.below": "Below data", "shape.option.above": "Above data",
    "shape.option.solid": "Solid", "shape.option.dashed": "Dashed", "shape.option.dotted": "Dotted",
    "shape.option.dash-dot": "Dash-dot",
    "shape.native": "Select a calculated native graph to edit shapes.",
    "shape.applied": "Graph shapes applied.",
    "shape.domain_warning": "Some data shapes are outside the current axis domain and were skipped.",
    "shape.error.limit": "A graph supports up to 100 shapes.",
    "shape.error.coordinates": "Enter finite X and Y coordinates.",
    "shape.error.fractions": "Plot fractions must be between 0 and 1.",
    "shape.error.line_zero": "Line endpoints must be distinct.",
    "shape.error.box_zero": "Shape width and height must be positive.",
    "shape.error.stroke": "Enter a valid stroke color.",
    "shape.error.fill": "Enter a valid fill color or leave it blank.",
    "shape.error.width": "Enter a line width between 0.1 and 12 points.",
    "shape.error.alpha": "Enter an opacity between 0 and 1.",
    "shape.error.line_style": "Choose a valid line style.",
    "shape.error.layer": "Choose a valid shape layer.",
    "shape.error.kind": "Choose a valid shape type.",
    "shape.error.units": "Choose valid shape coordinates.",
    "shape.error.axis_domain": "Choose coordinates within the domain of the current axis scales.",
    "graph.format.series": "Series", "graph.format.references": "Reference Lines",
    "graph.format.apply": "Apply", "graph.format.cancel": "Cancel", "graph.format.reset": "Reset to Defaults",
    "graph.format.error_title": "Check graph style",
    "graph.field.title": "Graph title", "graph.field.xlabel": "X axis title", "graph.field.ylabel": "Y axis title",
    "graph.field.font_family": "Font family", "graph.field.legend_position": "Legend position",
    "graph.field.frame": "Frame", "graph.field.major_grid": "Major grid lines",
    "graph.field.minor_grid": "Minor grid lines", "graph.field.font_sizes": "Font sizes in points",
    "graph.field.font_title": "Title", "graph.field.font_labels": "Axis titles",
    "graph.field.font_ticks": "Tick labels", "graph.field.font_legend": "Legend",
    "graph.field.font_hint": "Leave blank to use the analysis default.",
    "graph.field.accent": "Legacy first-series color", "graph.field.pick": "Pick…",
    "graph.axis.block": "{axis} axis", "graph.axis.scale": "Scale", "graph.axis.min": "Minimum",
    "graph.axis.max": "Maximum", "graph.axis.step": "Major interval", "graph.axis.start": "Major tick origin",
    "graph.axis.minor": "Minor divisions", "graph.axis.decimals": "Decimal places",
    "graph.axis.categorical": "Categorical labels",
    "graph.axis.hint": ("Leave both limits blank for auto range. Leave tick settings blank for auto ticks.\n"
                        "Enter 0 to hide minor ticks, or choose from 2 to 10 on linear axes."),
    "graph.axis.right": "Right axis", "graph.axis.right_title": "Title",
    "graph.series.element": "Plot element", "graph.series.label": "Legend label", "graph.series.color": "Color",
    "graph.series.line_style": "Line pattern", "graph.series.width": "Line width (pt)",
    "graph.series.marker": "Symbol", "graph.series.marker_size": "Symbol size (pt)",
    "graph.series.marker_color": "Symbol color", "graph.series.draw_style": "Draw style",
    "graph.series.side": "Axis",
    "graph.series.hint": "Choose a plot element. Blank fields keep their original settings.",
    "graph.series.inactive_hint": ("Choose a plot element. Blank fields keep their original settings. "
                                   "Disabled fields stay saved for the other draw styles."),
    "graph.series.none": "This graph has no individual plot elements to format.",
    "graph.kind.line": "Line", "graph.kind.errorbar": "Error bars", "graph.kind.scatter": "Scatter",
    "graph.kind.bar": "Bar",
    "graph.references.hint": ("Add up to 12 reference lines, one per row.\n"
                              "Use X or Y, followed by a comma and a value. Add an optional label.\n"
                              "Example  Y, 2.5, Response threshold"),
    "graph.references.error": "Enter each reference line as X or Y, a number, and an optional label.",
    # Inspector.
    "graph.inspector.title": "Inspector", "graph.inspector.apply": "Apply", "graph.inspector.cancel": "Cancel",
    "graph.inspector.review": "Saved graph settings need review. {warning}",
    "graph.inspector.data": "Data", "graph.inspector.axes": "Axes", "graph.inspector.page": "Page",
    "graph.inspector.reset_section": "Reset section", "graph.inspector.element": "Element",
    "graph.inspector.xy_hint": ("Use Format Graph to change the draw style, axis side, "
                                "Y scale and right-axis settings."),
    "graph.inspector.xy_inactive": ("Use Format Graph to change the draw style, axis side, Y scale and right-axis "
                                    "settings. Disabled fields stay saved for the other draw styles."),
    "graph.inspector.label": "Label", "graph.inspector.color": "Color", "graph.inspector.line_style": "Line",
    "graph.inspector.width": "Width (pt)", "graph.inspector.marker": "Symbol",
    "graph.inspector.marker_size": "Size (pt)", "graph.inspector.marker_color": "Symbol color",
    "graph.inspector.show": "Show", "graph.inspector.show_kind.box": "Show box",
    "graph.inspector.show_kind.violin": "Show violin", "graph.inspector.show_kind.pair": "Show pair",
    "graph.inspector.show_kind.trajectory": "Show trajectory",
    "graph.inspector.show_kind.trajectory-mean": "Show trajectory-mean",
    "graph.inspector.blank_hint": "Blank fields keep the analysis default.",
    "graph.inspector.scale": "{axis} scale", "graph.inspector.range": "{axis} range",
    "graph.inspector.automatic": "Blank means automatic.", "graph.inspector.categorical": "Categorical labels.",
    "graph.inspector.legend": "Legend", "graph.inspector.fix_fields": "Fix the highlighted fields, or press Cancel.",
    "graph.inspector.applied": "Applied.",
    "graph.inspector.enter_number": "Enter a number.",
    "graph.inspector.enter_minimum": "Enter a number for the minimum.",
    "graph.inspector.enter_maximum": "Enter a number for the maximum.",
    "graph.inspector.enter_size": "Enter a size between 0.1 and 72 points.",
    "graph.inspector.both_limits": "Enter both limits, or leave both blank for an automatic range.",
    "qq.panels.button": "Q–Q panels…",
    "qq.panels.dialog_title": "Q–Q panels",
    "qq.panels.panel_label": "Panel",
    "qq.panels.panel.normal": "Normal Q–Q (normal)",
    "qq.panels.panel.lognormal": "Lognormal Q–Q (lognormal)",
    "qq.panels.tab.axes": "Axes & title",
    "qq.panels.tab.points": "Points",
    "qq.panels.tab.reference": "Reference line",
    "qq.panels.title": "Title",
    "qq.panels.xlabel": "X label",
    "qq.panels.ylabel": "Y label",
    "qq.panels.xrange": "X range",
    "qq.panels.yrange": "Y range",
    "qq.panels.show_legend": "Show legend",
    "qq.panels.hint": "Leave fields blank for automatic defaults. Labels are shown literally (no math formatting).",
    "qq.panels.points.visible": "Show points",
    "qq.panels.points.marker": "Symbol",
    "qq.panels.points.size": "Size (0.5–36 pt)",
    "qq.panels.points.color": "Color (#RRGGBB)",
    "qq.panels.points.alpha": "Opacity (0–1)",
    "qq.panels.points.hint": "Leave Auto or blank to inherit defaults. Size is the marker diameter in points (area = size²; default area 26).",
    "qq.panels.ref.visible": "Show reference line",
    "qq.panels.ref.color": "Color (#RRGGBB)",
    "qq.panels.ref.width": "Line width (0.1–10 pt)",
    "qq.panels.ref.style": "Line style",
    "qq.panels.ref.alpha": "Opacity (0–1)",
    "qq.panels.ref.hint": "Leave Auto or blank to inherit defaults.",
    "qq.panels.ref.unavailable": "No reference line was produced by this analysis (disabled in options or zero variance). Controls are disabled; any saved preferences are kept.",
    "qq.panels.choose_color": "Choose…",
    "qq.panels.auto": "Auto (default)",
    "qq.panels.preview": "Preview",
    "qq.panels.reset_selected": "Reset selected",
    "qq.panels.apply": "Apply",
    "qq.panels.cancel": "Cancel",
    "qq.panels.error.title": "Check Q–Q panel settings",
    "qq.panels.error.label_length": "Graph labels are limited to 160 characters.",
    "qq.panels.error.both_limits": "Enter both axis limits, or leave both blank for an automatic range.",
    "qq.panels.error.number": "Enter finite numbers for axis options.",
    "qq.panels.error.order": "The axis minimum must be smaller than the maximum and the span must be finite.",
    "qq.panels.error.nonsingular": "These axis limits are too close together to render.",
    "qq.panels.error.size": "Enter a finite point size between 0.5 and 36 points.",
    "qq.panels.error.width": "Enter a finite line width between 0.1 and 10 points.",
    "qq.panels.error.alpha": "Enter a finite opacity between 0 and 1.",
    "qq.panels.error.color": "Enter a valid color, for example #127A78.",
    # Choices: display labels of canonical values.
    "graph.choice.analysis_default": "Analysis default", "graph.choice.default": "Default",
    "graph.choice.linear": "Linear", "graph.choice.log": "Logarithmic",
    "graph.choice.probability": "Probability", "graph.choice.probability_percent": "Probability %",
    "graph.legend.hidden": "hidden", "graph.legend.best": "best", "graph.legend.upper_right": "upper right",
    "graph.legend.upper_left": "upper left", "graph.legend.lower_left": "lower left",
    "graph.legend.lower_right": "lower right", "graph.legend.center_left": "center left",
    "graph.legend.center_right": "center right", "graph.legend.lower_center": "lower center",
    "graph.legend.upper_center": "upper center",
    "graph.frame.open": "open", "graph.frame.box": "box",
    "graph.line.solid": "solid", "graph.line.dashed": "dashed", "graph.line.dotted": "dotted",
    "graph.line.dash_dot": "dash-dot", "graph.line.none": "none",
    "graph.marker.circle": "Circle", "graph.marker.square": "Square", "graph.marker.diamond": "Diamond",
    "graph.marker.triangle_up": "Triangle up", "graph.marker.triangle_down": "Triangle down",
    "graph.marker.plus": "Plus", "graph.marker.cross": "Cross", "graph.marker.star": "Star",
    "graph.marker.none": "No symbol",
    "graph.draw.points": "Points", "graph.draw.line": "Line", "graph.draw.line_points": "Line and points",
    "graph.side.left": "Left", "graph.side.right": "Right",
    # Validation messages of presentation.py, matched by their English text (see translate_message).
    "graph.error.float": "could not convert string to float: {value}",
    "graph.error.int": "invalid literal for int() with base 10: {value}",
    "graph.error.math": "Invalid math notation in graph label {label}.",
    "graph.error.axis_options": "Invalid axis options.",
    "graph.error.finite": "Enter finite numbers for axis options.",
    "graph.error.both_limits": "Enter both axis limits, or leave both blank for an automatic range.",
    "graph.error.limit_order": "The axis minimum must be smaller than the maximum and the span must be finite.",
    "graph.error.limits_close": "These axis limits are too close together to render.",
    "graph.error.minor": "Use 0 to hide minor ticks, or enter 2 to 10 divisions per major interval.",
    "graph.error.decimals": "Enter 0 to 10 decimal places.",
    "graph.error.start": "Enter a major interval to choose its starting value.",
    "graph.error.step_positive": "The major interval must be positive.",
    "graph.error.too_many_ticks": "The major interval places too many ticks or is too small at this range.",
    "graph.error.probability_limits": "Probability limits must be strictly between 0 and {limit}.",
    "graph.error.probability_ticks": "Probability axes use fixed tick positions and labels.",
    "graph.error.log_limits": "Logarithmic axis limits must be strictly positive.",
    "graph.error.log_ticks": "Logarithmic axes use logarithmic tick spacing.",
    "graph.error.series_reference": "Invalid graph series reference.",
    "graph.error.series_setting": "This setting is not available for the selected series.",
    "graph.error.color": "Enter a valid color, for example #2866ae.",
    "graph.error.sizes": "Enter line widths and symbol sizes between 0.1 and 72 points.",
    "graph.error.line_style": "Choose a valid line style.",
    "graph.error.marker": "Choose a valid symbol.",
    "graph.error.series_label": ("Enter a series legend label of up to 160 characters that does not start "
                                 "with an underscore."),
    "graph.error.group_count": "Format up to {count} box or violin groups.",
    "graph.error.group_reference": "Invalid graph group reference.",
    "graph.error.group_setting": "This setting is not available for box and violin groups.",
    "graph.error.group_visibility": "Invalid group visibility.",
    "graph.error.style": "Invalid graph style.",
    "graph.error.label_length": "Graph labels are limited to 160 characters.",
    "graph.error.scale": "Choose a supported axis scale.",
    "graph.error.grid": "Invalid grid setting.",
    "graph.error.frame": "Invalid graph frame.",
    "graph.error.font_family": "Choose a valid font family.",
    "graph.error.font_sizes": "Enter font sizes between 4 and 72 points.",
    "graph.error.legend": "Choose a valid legend position.",
    "graph.error.axis": "Invalid graph axis.",
    "graph.error.series_count": "Format up to 256 individual series.",
    "graph.error.reference_count": "Add up to 12 reference lines per graph.",
    "graph.error.reference": ("Each reference needs an axis, a finite value and an optional label "
                              "up to 160 characters."),
    "graph.error.not_available": "This setting is not available for {series}.",
    "graph.error.numeric_ticks": "The {axis} axis needs numeric ticks for these settings.",
    "graph.error.stacked_log": ("Stacked bars start at zero, so the {axis} axis cannot use a logarithmic "
                                "scale. Choose linear, or change Placement of groups in Graph settings."),
    "graph.error.stacked_probability": ("Stacked bars start at zero, so the {axis} axis cannot use a probability "
                                        "scale. Choose linear, or change Placement of groups in Graph settings."),
    "graph.error.log_data": "A logarithmic axis requires strictly positive data.",
    "graph.error.log_reference": "A reference on a logarithmic axis must be strictly positive.",
    "graph.error.probability_data": "A probability axis accepts data from 0 to {limit}.",
    "graph.error.probability_reference": "A probability reference must be inside the probability range.",
}

_GRAPH_IT = {
    "graph.format.title": "Formato grafico", "graph.format.appearance": "Aspetto", "graph.format.axes": "Assi",
    "annotation.title": "Annotazioni grafico", "annotation.button": "Annotazioni…",
    "annotation.add": "Aggiungi…", "annotation.edit": "Modifica…", "annotation.remove": "Rimuovi",
    "annotation.text": "Testo", "annotation.units": "Coordinate", "annotation.align": "Allineamento",
    "annotation.position": "X, Y del testo", "annotation.target": "X, Y della freccia", "annotation.arrow": "Aggiungi una freccia",
    "annotation.arrow_short": "Freccia", "annotation.size": "Dimensione testo (pt)", "annotation.color": "Colore",
    "annotation.option.axes": "Frazioni del grafico (0–1)", "annotation.option.data": "Dati (asse Y sinistro)",
    "annotation.option.left": "Sinistra", "annotation.option.center": "Centro", "annotation.option.right": "Destra",
    "annotation.invalid_fields": "Inserisci coordinate e dimensione del testo valide.",
    "annotation.axis_domain": "Scegli coordinate nel dominio delle scale correnti degli assi.",
    "annotation.native": "Seleziona un grafico nativo già calcolato per aggiungere annotazioni.",
    "annotation.applied": "Annotazioni applicate.",
    "annotation.error.text": "Inserisci un testo tra 1 e 500 caratteri.",
    "annotation.error.coordinates": "Inserisci coordinate X e Y finite.",
    "annotation.error.fractions": "Le frazioni del grafico devono essere comprese tra 0 e 1.",
    "annotation.error.size": "Inserisci una dimensione del testo tra 4 e 72 punti.",
    "annotation.error.color": "Inserisci un colore di testo valido.",
    "shape.title": "Forme del grafico", "shape.button": "Forme del grafico…",
    "shape.add": "Aggiungi…", "shape.edit": "Modifica…", "shape.duplicate": "Duplica",
    "shape.remove": "Elimina", "shape.clear": "Elimina tutto", "shape.up": "Su", "shape.down": "Giù",
    "shape.preview": "Anteprima", "shape.kind": "Forma", "shape.units": "Coordinate",
    "shape.point1": "Primo punto (X1, Y1)", "shape.point2": "Secondo punto (X2, Y2)", "shape.points": "Punti",
    "shape.stroke": "Colore contorno", "shape.width": "Spessore linea (pt)", "shape.line_style": "Stile linea",
    "shape.fill": "Colore riempimento", "shape.no_fill": "Senza riempimento", "shape.alpha": "Opacità (0–1)",
    "shape.layer": "Livello",
    "shape.fill_hint": "Lascia vuoto il riempimento per un interno trasparente. Le linee non usano riempimento.",
    "shape.axis_hint": "Le coordinate dati usano l'asse X primario e l'asse Y sinistro.",
    "shape.option.line": "Linea", "shape.option.rectangle": "Rettangolo", "shape.option.ellipse": "Ellisse",
    "shape.option.axes": "Frazioni del grafico (0–1)", "shape.option.data": "Dati (asse Y sinistro)",
    "shape.option.below": "Sotto i dati", "shape.option.above": "Sopra i dati",
    "shape.option.solid": "Continua", "shape.option.dashed": "Tratteggiata", "shape.option.dotted": "Punteggiata",
    "shape.option.dash-dot": "Tratto-punto",
    "shape.native": "Seleziona un grafico nativo già calcolato per modificare le forme.",
    "shape.applied": "Forme del grafico applicate.",
    "shape.domain_warning": "Alcune forme in coordinate dati sono fuori dal dominio corrente degli assi e sono state omesse.",
    "shape.error.limit": "Un grafico supporta fino a 100 forme.",
    "shape.error.coordinates": "Inserisci coordinate X e Y finite.",
    "shape.error.fractions": "Le frazioni del grafico devono essere comprese tra 0 e 1.",
    "shape.error.line_zero": "Gli estremi della linea devono essere distinti.",
    "shape.error.box_zero": "Larghezza e altezza della forma devono essere positive.",
    "shape.error.stroke": "Inserisci un colore di contorno valido.",
    "shape.error.fill": "Inserisci un colore di riempimento valido oppure lascia vuoto.",
    "shape.error.width": "Inserisci uno spessore linea tra 0.1 e 12 punti.",
    "shape.error.alpha": "Inserisci un'opacità compresa tra 0 e 1.",
    "shape.error.line_style": "Scegli uno stile di linea valido.",
    "shape.error.layer": "Scegli un livello valido.",
    "shape.error.kind": "Scegli un tipo di forma valido.",
    "shape.error.units": "Scegli coordinate valide per la forma.",
    "shape.error.axis_domain": "Scegli coordinate nel dominio delle scale correnti degli assi.",
    "graph.format.series": "Serie", "graph.format.references": "Linee di riferimento",
    "graph.format.apply": "Applica", "graph.format.cancel": "Annulla",
    "graph.format.reset": "Ripristina predefiniti",
    "graph.format.error_title": "Controlla lo stile del grafico",
    "graph.field.title": "Titolo del grafico", "graph.field.xlabel": "Titolo asse X",
    "graph.field.ylabel": "Titolo asse Y", "graph.field.font_family": "Famiglia di caratteri",
    "graph.field.legend_position": "Posizione della legenda", "graph.field.frame": "Cornice",
    "graph.field.major_grid": "Griglia principale", "graph.field.minor_grid": "Griglia secondaria",
    "graph.field.font_sizes": "Dimensioni dei caratteri in punti",
    "graph.field.font_title": "Titolo", "graph.field.font_labels": "Titoli assi",
    "graph.field.font_ticks": "Etichette tacche", "graph.field.font_legend": "Legenda",
    "graph.field.font_hint": "Lascia vuoto per usare il valore predefinito dell'analisi.",
    "graph.field.accent": "Colore prima serie (versioni precedenti)", "graph.field.pick": "Scegli…",
    "graph.axis.block": "Asse {axis}", "graph.axis.scale": "Scala", "graph.axis.min": "Minimo",
    "graph.axis.max": "Massimo", "graph.axis.step": "Intervallo principale",
    "graph.axis.start": "Origine tacche principali", "graph.axis.minor": "Suddivisioni secondarie",
    "graph.axis.decimals": "Cifre decimali", "graph.axis.categorical": "Etichette categoriali",
    "graph.axis.hint": ("Lascia vuoti entrambi i limiti per l'intervallo automatico e le impostazioni delle "
                        "tacche per le tacche automatiche.\nInserisci 0 per nascondere le tacche secondarie, "
                        "oppure da 2 a 10 sugli assi lineari."),
    "graph.axis.right": "Asse destro", "graph.axis.right_title": "Titolo",
    "graph.series.element": "Elemento del grafico", "graph.series.label": "Etichetta in legenda",
    "graph.series.color": "Colore", "graph.series.line_style": "Tratto della linea",
    "graph.series.width": "Spessore linea (pt)", "graph.series.marker": "Simbolo",
    "graph.series.marker_size": "Dimensione simbolo (pt)", "graph.series.marker_color": "Colore simbolo",
    "graph.series.draw_style": "Stile di disegno", "graph.series.side": "Asse",
    "graph.series.hint": "Scegli un elemento del grafico. I campi vuoti mantengono le impostazioni originali.",
    "graph.series.inactive_hint": ("Scegli un elemento del grafico. I campi vuoti mantengono le impostazioni "
                                   "originali; i campi disabilitati restano salvati per gli altri stili di disegno."),
    "graph.series.none": "Questo grafico non ha singoli elementi da formattare.",
    "graph.kind.line": "Linea", "graph.kind.errorbar": "Barre di errore", "graph.kind.scatter": "Punti",
    "graph.kind.bar": "Barre",
    "graph.references.hint": ("Aggiungi fino a 12 linee di riferimento, una per riga.\n"
                              "Scrivi X o Y, una virgola e un valore. Puoi aggiungere un'etichetta.\n"
                              "Esempio  Y, 2.5, Soglia di risposta"),
    "graph.references.error": ("Scrivi ogni linea di riferimento come X o Y, un numero e un'etichetta "
                               "facoltativa."),
    "graph.inspector.title": "Ispettore", "graph.inspector.apply": "Applica", "graph.inspector.cancel": "Annulla",
    "graph.inspector.review": "Le impostazioni salvate del grafico vanno ricontrollate. {warning}",
    "graph.inspector.data": "Dati", "graph.inspector.axes": "Assi", "graph.inspector.page": "Pagina",
    "graph.inspector.reset_section": "Ripristina sezione", "graph.inspector.element": "Elemento",
    "graph.inspector.xy_hint": ("Usa Formato grafico per cambiare stile di disegno, lato dell'asse, "
                                "scala Y e asse destro."),
    "graph.inspector.xy_inactive": ("Usa Formato grafico per cambiare stile di disegno, lato dell'asse, scala Y e "
                                    "asse destro. I campi disabilitati restano salvati per gli altri stili di disegno."),
    "graph.inspector.label": "Etichetta", "graph.inspector.color": "Colore", "graph.inspector.line_style": "Linea",
    "graph.inspector.width": "Spessore (pt)", "graph.inspector.marker": "Simbolo",
    "graph.inspector.marker_size": "Dimensione (pt)", "graph.inspector.marker_color": "Colore simbolo",
    "graph.inspector.show": "Mostra", "graph.inspector.show_kind.box": "Mostra box",
    "graph.inspector.show_kind.violin": "Mostra violino", "graph.inspector.show_kind.pair": "Mostra coppia",
    "graph.inspector.show_kind.trajectory": "Mostra traiettoria",
    "graph.inspector.show_kind.trajectory-mean": "Mostra traiettoria media",
    "graph.inspector.blank_hint": "I campi vuoti mantengono il valore dell'analisi.",
    "graph.inspector.scale": "Scala {axis}", "graph.inspector.range": "Intervallo {axis}",
    "graph.inspector.automatic": "Vuoto significa automatico.", "graph.inspector.categorical": "Etichette categoriali.",
    "graph.inspector.legend": "Legenda",
    "graph.inspector.fix_fields": "Correggi i campi evidenziati, oppure premi Annulla.",
    "graph.inspector.applied": "Applicato.",
    "graph.inspector.enter_number": "Inserisci un numero.",
    "graph.inspector.enter_minimum": "Inserisci un numero per il minimo.",
    "graph.inspector.enter_maximum": "Inserisci un numero per il massimo.",
    "graph.inspector.enter_size": "Inserisci una dimensione tra 0.1 e 72 punti.",
    "graph.inspector.both_limits": "Inserisci entrambi i limiti, oppure lasciali vuoti per l'intervallo automatico.",
    "qq.panels.button": "Pannelli Q–Q…",
    "qq.panels.dialog_title": "Pannelli Q–Q",
    "qq.panels.panel_label": "Pannello",
    "qq.panels.panel.normal": "Q–Q normale (normal)",
    "qq.panels.panel.lognormal": "Q–Q lognormale (lognormal)",
    "qq.panels.tab.axes": "Assi e titolo",
    "qq.panels.tab.points": "Punti",
    "qq.panels.tab.reference": "Retta di riferimento",
    "qq.panels.title": "Titolo",
    "qq.panels.xlabel": "Etichetta X",
    "qq.panels.ylabel": "Etichetta Y",
    "qq.panels.xrange": "Intervallo X",
    "qq.panels.yrange": "Intervallo Y",
    "qq.panels.show_legend": "Mostra legenda",
    "qq.panels.hint": "Lascia i campi vuoti per i predefiniti automatici. Le etichette sono letterali (nessuna formattazione matematica).",
    "qq.panels.points.visible": "Mostra punti",
    "qq.panels.points.marker": "Simbolo",
    "qq.panels.points.size": "Dimensione (0,5–36 pt)",
    "qq.panels.points.color": "Colore (#RRGGBB)",
    "qq.panels.points.alpha": "Opacità (0–1)",
    "qq.panels.points.hint": "Lascia Auto o vuoto per ereditare i predefiniti. La dimensione è in punti (area = dimensione²; area predefinita 26).",
    "qq.panels.ref.visible": "Mostra retta di riferimento",
    "qq.panels.ref.color": "Colore (#RRGGBB)",
    "qq.panels.ref.width": "Spessore linea (0,1–10 pt)",
    "qq.panels.ref.style": "Stile linea",
    "qq.panels.ref.alpha": "Opacità (0–1)",
    "qq.panels.ref.hint": "Lascia Auto o vuoto per ereditare i predefiniti.",
    "qq.panels.ref.unavailable": "Nessuna retta di riferimento prodotta da questa analisi (disattivata nelle opzioni o varianza nulla). I controlli sono disabilitati; le eventuali preferenze salvate restano conservate.",
    "qq.panels.choose_color": "Scegli…",
    "qq.panels.auto": "Auto (predefinito)",
    "qq.panels.preview": "Anteprima",
    "qq.panels.reset_selected": "Ripristina selezionato",
    "qq.panels.apply": "Applica",
    "qq.panels.cancel": "Annulla",
    "qq.panels.error.title": "Controlla le impostazioni dei pannelli Q–Q",
    "qq.panels.error.label_length": "Le etichette possono contenere al massimo 160 caratteri.",
    "qq.panels.error.both_limits": "Inserisci entrambi i limiti, oppure lasciali vuoti per l’intervallo automatico.",
    "qq.panels.error.number": "Inserisci numeri finiti per le opzioni dell’asse.",
    "qq.panels.error.order": "Il minimo dell’asse deve essere minore del massimo e l’intervallo deve essere finito.",
    "qq.panels.error.nonsingular": "Questi limiti dell’asse sono troppo vicini per essere disegnati.",
    "qq.panels.error.size": "Inserisci una dimensione punti finita tra 0,5 e 36 punti.",
    "qq.panels.error.width": "Inserisci uno spessore linea finito tra 0,1 e 10 punti.",
    "qq.panels.error.alpha": "Inserisci un’opacità finita tra 0 e 1.",
    "qq.panels.error.color": "Inserisci un colore valido, ad esempio #127A78.",
    "graph.choice.analysis_default": "Predefinito dell'analisi", "graph.choice.default": "Predefinito",
    "graph.choice.linear": "Lineare", "graph.choice.log": "Logaritmica",
    "graph.choice.probability": "Probabilità", "graph.choice.probability_percent": "Probabilità %",
    "graph.legend.hidden": "nascosta", "graph.legend.best": "posizione migliore",
    "graph.legend.upper_right": "in alto a destra", "graph.legend.upper_left": "in alto a sinistra",
    "graph.legend.lower_left": "in basso a sinistra", "graph.legend.lower_right": "in basso a destra",
    "graph.legend.center_left": "al centro a sinistra", "graph.legend.center_right": "al centro a destra",
    "graph.legend.lower_center": "in basso al centro", "graph.legend.upper_center": "in alto al centro",
    "graph.frame.open": "aperta", "graph.frame.box": "riquadro",
    "graph.line.solid": "continua", "graph.line.dashed": "tratteggiata", "graph.line.dotted": "punteggiata",
    "graph.line.dash_dot": "tratto-punto", "graph.line.none": "nessuna",
    "graph.marker.circle": "Cerchio", "graph.marker.square": "Quadrato", "graph.marker.diamond": "Rombo",
    "graph.marker.triangle_up": "Triangolo in su", "graph.marker.triangle_down": "Triangolo in giù",
    "graph.marker.plus": "Più", "graph.marker.cross": "Croce", "graph.marker.star": "Stella",
    "graph.marker.none": "Nessun simbolo",
    "graph.draw.points": "Punti", "graph.draw.line": "Linea", "graph.draw.line_points": "Linea e punti",
    "graph.side.left": "Sinistra", "graph.side.right": "Destra",
    "graph.error.float": "Inserisci un numero: {value} non è valido.",
    "graph.error.int": "Inserisci un numero intero: {value} non è valido.",
    "graph.error.math": "Notazione matematica non valida nell'etichetta {label}.",
    "graph.error.axis_options": "Opzioni dell'asse non valide.",
    "graph.error.finite": "Inserisci numeri finiti nelle opzioni dell'asse.",
    "graph.error.both_limits": ("Inserisci entrambi i limiti dell'asse, oppure lasciali vuoti per "
                                "l'intervallo automatico."),
    "graph.error.limit_order": ("Il minimo dell'asse deve essere minore del massimo e l'intervallo deve "
                                "essere finito."),
    "graph.error.limits_close": "Questi limiti dell'asse sono troppo vicini per essere disegnati.",
    "graph.error.minor": ("Usa 0 per nascondere le tacche secondarie, oppure da 2 a 10 suddivisioni per "
                          "intervallo principale."),
    "graph.error.decimals": "Inserisci da 0 a 10 cifre decimali.",
    "graph.error.start": "Inserisci un intervallo principale per sceglierne il valore iniziale.",
    "graph.error.step_positive": "L'intervallo principale deve essere positivo.",
    "graph.error.too_many_ticks": ("L'intervallo principale crea troppe tacche o è troppo piccolo per "
                                   "questo intervallo."),
    "graph.error.probability_limits": "I limiti di probabilità devono essere strettamente tra 0 e {limit}.",
    "graph.error.probability_ticks": "Gli assi di probabilità usano posizioni ed etichette fisse delle tacche.",
    "graph.error.log_limits": "I limiti di un asse logaritmico devono essere strettamente positivi.",
    "graph.error.log_ticks": "Gli assi logaritmici usano una spaziatura logaritmica delle tacche.",
    "graph.error.series_reference": "Riferimento alla serie non valido.",
    "graph.error.series_setting": "Questa impostazione non è disponibile per la serie selezionata.",
    "graph.error.color": "Inserisci un colore valido, per esempio #2866ae.",
    "graph.error.sizes": "Inserisci spessori di linea e dimensioni dei simboli tra 0.1 e 72 punti.",
    "graph.error.line_style": "Scegli un tratto di linea valido.",
    "graph.error.marker": "Scegli un simbolo valido.",
    "graph.error.series_label": ("Inserisci un'etichetta di legenda di al massimo 160 caratteri che non "
                                 "inizi con un trattino basso."),
    "graph.error.group_count": "Formatta al massimo {count} gruppi box o violino.",
    "graph.error.group_reference": "Riferimento al gruppo non valido.",
    "graph.error.group_setting": "Questa impostazione non è disponibile per i gruppi box e violino.",
    "graph.error.group_visibility": "Visibilità del gruppo non valida.",
    "graph.error.style": "Stile del grafico non valido.",
    "graph.error.label_length": "Le etichette del grafico sono limitate a 160 caratteri.",
    "graph.error.scale": "Scegli una scala dell'asse supportata.",
    "graph.error.grid": "Impostazione della griglia non valida.",
    "graph.error.frame": "Cornice del grafico non valida.",
    "graph.error.font_family": "Scegli una famiglia di caratteri valida.",
    "graph.error.font_sizes": "Inserisci dimensioni dei caratteri tra 4 e 72 punti.",
    "graph.error.legend": "Scegli una posizione della legenda valida.",
    "graph.error.axis": "Asse del grafico non valido.",
    "graph.error.series_count": "Formatta al massimo 256 serie singole.",
    "graph.error.reference_count": "Aggiungi al massimo 12 linee di riferimento per grafico.",
    "graph.error.reference": ("Ogni riferimento richiede un asse, un valore finito e un'etichetta facoltativa "
                              "di al massimo 160 caratteri."),
    "graph.error.not_available": "Questa impostazione non è disponibile per {series}.",
    "graph.error.numeric_ticks": "Per queste impostazioni l'asse {axis} deve avere tacche numeriche.",
    "graph.error.stacked_log": ("Le barre impilate partono da zero, quindi l'asse {axis} non può usare una scala "
                                "logaritmica. Scegli lineare, oppure cambia la disposizione dei gruppi nelle "
                                "impostazioni del grafico."),
    "graph.error.stacked_probability": ("Le barre impilate partono da zero, quindi l'asse {axis} non può usare "
                                        "una scala di probabilità. Scegli lineare, oppure cambia la disposizione "
                                        "dei gruppi nelle impostazioni del grafico."),
    "graph.error.log_data": "Un asse logaritmico richiede dati strettamente positivi.",
    "graph.error.log_reference": "Un riferimento su un asse logaritmico deve essere strettamente positivo.",
    "graph.error.probability_data": "Un asse di probabilità accetta dati da 0 a {limit}.",
    "graph.error.probability_reference": "Un riferimento di probabilità deve stare nell'intervallo di probabilità.",
}
# Compare models (AICc): the model picker. Equation names, columns and recipe keys stay literal.
_AICC_EN = {
    "aicc.add": "Add…", "aicc.remove": "Remove", "aicc.up": "Up", "aicc.down": "Down",
    "aicc.count": "{count} selected (choose {minimum} to {maximum}, in the order of the legend)",
    "aicc.note": ("Akaike weights are shares relative to the selected models, not the probability that a model "
                  "is true. All fits are unweighted and no p value is produced."),
}
_AICC_IT = {
    "aicc.add": "Aggiungi…", "aicc.remove": "Rimuovi", "aicc.up": "Su", "aicc.down": "Giù",
    "aicc.count": "{count} selezionati (da {minimum} a {maximum}, nell'ordine della legenda)",
    "aicc.note": ("I pesi di Akaike sono quote relative ai modelli scelti, non la probabilità che un modello sia "
                  "vero. Tutti i fit sono non pesati e non si ottiene alcun p value."),
}
_EN.update(_GRAPH_EN)
_IT.update(_GRAPH_IT)
_EN.update(_AICC_EN)
_IT.update(_AICC_IT)

# Nonlinear and global nonlinear regression: one line under the Weighting field explains its denominator.
_WEIGHTING_EN = {
    "weighting.note.unweighted": "Every point counts equally: the fit minimises the sum of squared residuals r².",
    "weighting.note.inverse_variance": "Each residual is divided by the value in the SD column: the fit minimises "
                                       "the sum of r² / SD².",
    "weighting.note.abs_y": "The denominator is the observed |Y| of each point: the fit minimises the sum of r² / |Y|. "
                            "Y values of zero are not allowed.",
    "weighting.note.y_squared": "The denominator is the observed Y² of each point: the fit minimises the sum of "
                                "r² / Y² (relative distances). Y values of zero are not allowed.",
    "weighting.note.abs_yfit": "The denominator is |Yfit|, the fitted value at each point: the fit minimises the sum "
                               "of r² / |Yfit|. It starts unweighted and is refitted up to 50 times with the previous "
                               "weights held fixed. Intervals and comparisons use the final weights.",
    "weighting.note.yfit_squared": "The denominator is Yfit², the fitted value squared at each point: the fit minimises "
                                   "the sum of r² / Yfit². It starts unweighted and is refitted up to 50 times with the "
                                   "previous weights held fixed. Intervals and comparisons use the final weights.",
}
_WEIGHTING_IT = {
    "weighting.note.unweighted": "Ogni punto conta allo stesso modo: il fit minimizza la somma dei residui al quadrato r².",
    "weighting.note.inverse_variance": "Ogni residuo è diviso per il valore della colonna SD: il fit minimizza "
                                       "la somma di r² / SD².",
    "weighting.note.abs_y": "Il denominatore è |Y| osservato di ogni punto: il fit minimizza la somma di r² / |Y|. "
                            "Non sono ammessi valori Y uguali a zero.",
    "weighting.note.y_squared": "Il denominatore è Y² osservato di ogni punto: il fit minimizza la somma di "
                                "r² / Y² (distanze relative). Non sono ammessi valori Y uguali a zero.",
    "weighting.note.abs_yfit": "Il denominatore è |Yfit|, il valore stimato in ogni punto: il fit minimizza la somma di "
                               "r² / |Yfit|. Parte senza pesi e viene rifatto fino a 50 volte con i pesi precedenti "
                               "tenuti fissi. Intervalli e confronti usano i pesi finali.",
    "weighting.note.yfit_squared": "Il denominatore è Yfit², il valore stimato al quadrato in ogni punto: il fit "
                                   "minimizza la somma di r² / Yfit². Parte senza pesi e viene rifatto fino a 50 volte "
                                   "con i pesi precedenti tenuti fissi. Intervalli e confronti usano i pesi finali.",
}
_EN.update(_WEIGHTING_EN)
_IT.update(_WEIGHTING_IT)

# Mann–Whitney and Wilcoxon signed-rank dialogs.
_EN["rank.hint"] = ("Automatic uses the exact conditional p value, with ties, while it fits the work limit, "
                    "and otherwise the normal approximation. The continuity correction applies only to the "
                    "normal approximation.")
_IT["rank.hint"] = ("Automatico usa il valore p esatto condizionato, con i legami, finché rientra nel limite di "
                    "calcolo, altrimenti l'approssimazione normale. La correzione di continuità vale solo per "
                    "l'approssimazione normale.")
_EN.update({
    "rank.field.p_value": "P value", "rank.field.alternative": "Alternative",
    "rank.field.continuity": "Continuity correction", "rank.field.zero_differences": "Zero differences",
    "rank.choice.automatic": "Automatic", "rank.choice.exact": "Exact conditional",
    "rank.choice.normal": "Normal approximation", "rank.choice.two_sided": "Two-sided",
    "rank.choice.less": "Less", "rank.choice.greater": "Greater",
    "rank.choice.discard": "Discard", "rank.choice.pratt": "Pratt",
})
_IT.update({
    "rank.field.p_value": "Valore p", "rank.field.alternative": "Ipotesi alternativa",
    "rank.field.continuity": "Correzione di continuità", "rank.field.zero_differences": "Differenze nulle",
    "rank.choice.automatic": "Automatico", "rank.choice.exact": "Esatto condizionato",
    "rank.choice.normal": "Approssimazione normale", "rank.choice.two_sided": "Bilaterale",
    "rank.choice.less": "Minore", "rank.choice.greater": "Maggiore",
    "rank.choice.discard": "Escludi", "rank.choice.pratt": "Pratt",
})

# Nonlinear regression bands (0.61).
_EN.update({
    "bands.field.band": "Band", "bands.field.level": "Confidence level (%)", "bands.field.drawing": "Band drawing",
    "bands.choice.none": "None", "bands.choice.mean": "Confidence (mean)",
    "bands.choice.prediction": "Prediction (new observation)", "bands.choice.filled": "Filled",
    "bands.choice.lines": "Lines",
    "bands.hint": ("Pointwise bands on the fitted curve, not simultaneous. Confidence (mean) bounds the mean "
                   "response at each X; Prediction bounds one new observation and needs an unweighted fit. "
                   "With observed-Y or fitted-Y weights only the mean band is offered, using the final weights."),
})
_IT.update({
    "bands.field.band": "Banda", "bands.field.level": "Livello di confidenza (%)", "bands.field.drawing": "Disegno banda",
    "bands.choice.none": "Nessuna", "bands.choice.mean": "Confidenza (media)",
    "bands.choice.prediction": "Predizione (nuova osservazione)", "bands.choice.filled": "Area",
    "bands.choice.lines": "Linee",
    "bands.hint": ("Bande puntuali sulla curva stimata, non simultanee. Confidenza (media) delimita la risposta "
                   "media a ogni X; Predizione delimita una nuova osservazione e richiede un fit non pesato. "
                   "Con pesi su Y osservato o stimato è ammessa solo la banda della media, con i pesi finali."),
})

# Fit custom equation (0.61). The custom.error.* texts are the exact messages of the engine with placeholders.
_EN.update({
    "custom.tab.variables": "Variables", "custom.tab.output": "Output",
    "custom.field.Equation": "Equation", "custom.field.Parameters": "Parameters", "custom.field.X": "X",
    "custom.field.Y": "Y", "custom.field.Group": "Group", "custom.field.Weighting": "Weighting",
    "custom.field.SD column": "SD column", "custom.field.Confidence level (%)": "Confidence level (%)",
    "custom.field.Curve points": "Curve points",
    "custom.weighting.unweighted": "Unweighted", "custom.weighting.inverse_variance": "Inverse variance (column)",
    "custom.preview": "Formula", "custom.check": "Check equation", "custom.check_ok": "The equation is valid and defined at the starting values.",
    "custom.grammar": "Use X, the coefficients listed in Parameters, pi, e, numbers, + - * / ^ ( ) and the "
                      "functions {functions}.",
    "custom.add": "Add", "custom.remove": "Remove", "custom.from_equation": "Add from equation",
    "custom.start": "Starting value", "custom.value": "Fixed value", "custom.fixed_hint": "Fixed (keep this value, do not estimate)",
    "custom.parameters_note": "Leave a limit empty for no limit. A fixed coefficient is used as typed and is not estimated.",
    "custom.column.name": "Name", "custom.column.start": "Start / value", "custom.column.fixed": "Fixed",
    "custom.column.lower": "Lower", "custom.column.upper": "Upper",
    "custom.group_prefix": "Group {group}:",
    "custom.error.name_chars": "Coefficient name {name} must be letters, digits and underscores, starting with a letter.",
    "custom.error.name_long": "Coefficient name {name}… is longer than 32 characters.",
    "custom.error.reserved": "{name} is reserved (X, Y, pi, e and function names cannot be coefficients).",
    "custom.error.too_long": "The equation is longer than 1024 characters.",
    "custom.error.unexpected_long": "Unexpected {char} at position {position}. Use numbers, X, the coefficients, + - * / ^ ( ) and the functions {functions}.",
    "custom.error.unexpected": "Unexpected {char} at position {position}.",
    "custom.error.bad_number": "Invalid number near position {position} (complex, hexadecimal and attribute syntax are not supported).",
    "custom.error.not_finite_number": "The number {number} is not finite.",
    "custom.error.too_many_nodes": "The equation has more than 128 elements.",
    "custom.error.too_deep": "The equation is nested deeper than 32 levels.",
    "custom.error.function_call": "{name} is a function: write it with an argument in parentheses, for example {example}.",
    "custom.error.close_call": "Missing ) after the argument of {name}.",
    "custom.error.one_argument": "{name} takes exactly one argument.",
    "custom.error.unknown_function": "{name} is not an available function. Functions: {functions}.",
    "custom.error.y_in_equation": "Y is the response and cannot appear in the equation.",
    "custom.error.undeclared": "{name} is not declared as a coefficient. Add it to Parameters or check the spelling (names are case-sensitive).",
    "custom.error.close_paren": "Missing ) to close a parenthesis.",
    "custom.error.ends_early": "The equation ends too early: something is missing after position {position}.",
    "custom.error.missing_value": "Missing a value for {name}.",
    "custom.error.empty": "Enter an equation, for example A + B*X.",
    "custom.error.too_many_parameters": "Use at most 12 coefficients.",
    "custom.error.distinct_names": "Coefficient names must be distinct.",
    "custom.error.unused": "The equation does not use {names}. Remove the coefficient or add it to the equation.",
    "custom.error.parameter_list": "Parameters must be a list of coefficients.",
    "custom.error.parameter_record": "Each coefficient needs a name, a starting value and its limits.",
    "custom.error.duplicate": "The coefficient {name} appears more than once.",
    "custom.error.fixed_flag": "{name}: Fixed must be true or false.",
    "custom.error.value_number": "{name}: the value must be a finite number.",
    "custom.error.start_number": "{name}: the starting value must be a finite number.",
    "custom.error.limit_order": "{name}: the lower limit must be smaller than the upper limit.",
    "custom.error.value_outside": "{name}: the value {value} lies outside its limits.",
    "custom.error.start_outside": "{name}: the starting value {value} lies outside its limits.",
    "custom.error.lower_number": "{name}: the lower limit must be a finite number or empty.",
    "custom.error.upper_number": "{name}: the upper limit must be a finite number or empty.",
    "custom.error.column": "Choose an existing column for {field}.",
    "custom.error.distinct_xy": "Select distinct columns for X and Y.",
    "custom.error.group_column": "Group must be an existing column different from X and Y.",
    "custom.error.weighting": "Choose Unweighted or Inverse variance (column).",
    "custom.error.sd_choose": "Choose the column with the relative standard deviations.",
    "custom.error.sd_differ": "The SD column must differ from X, Y and Group.",
    "custom.error.level": "The confidence level must be between 0 and 100 (exclusive).",
    "custom.error.points": "Curve points must be a whole number from 20 to 10000.",
    "custom.error.non_numeric": "Column {column} contains non-numeric values (first at source row {row}).",
    "custom.error.infinite": "Column {column} contains infinite values.",
    "custom.error.group_ambiguous": "Different group values look the same as text; make them distinct first.",
    "custom.error.groups_max": "Use at most 12 groups.",
    "custom.error.groups_none": "The group column has no values.",
    "custom.error.sd_positive": "The SD column needs positive values on every used row (source row {row}). Leave a cell empty to skip that row.",
    "custom.error.pairs_max": "The analysis supports up to 100,000 complete pairs.",
    "custom.error.undefined_start": "The equation is not defined with the starting values at X = {x} (source row {row}). Check divisions, logarithms and roots.",
    "custom.error.undefined_solution": "The equation is not defined at the solution at X = {x} (source row {row}). Check divisions, logarithms and roots.",
    "custom.error.undefined_curve": "The equation is not defined on the drawn curve at X = {x}.",
    "custom.error.no_pairs": "No complete X and Y pairs.",
    "custom.error.too_few_rows": "{n} complete rows cannot estimate {p} free coefficients; fix some coefficients or add data.",
    "custom.error.no_convergence": "The fit did not converge within {count} evaluations. Change the starting values or limits, or fix some coefficients.",
    "custom.error.rank": "The coefficients are not identifiable from these data (the Jacobian is rank deficient). Fix or remove coefficients, or check the equation.",
})
_IT.update({
    "custom.tab.variables": "Variabili", "custom.tab.output": "Risultati",
    "custom.field.Equation": "Equazione", "custom.field.Parameters": "Coefficienti", "custom.field.X": "X",
    "custom.field.Y": "Y", "custom.field.Group": "Gruppo", "custom.field.Weighting": "Pesatura",
    "custom.field.SD column": "Colonna SD", "custom.field.Confidence level (%)": "Livello di confidenza (%)",
    "custom.field.Curve points": "Punti della curva",
    "custom.weighting.unweighted": "Senza pesi", "custom.weighting.inverse_variance": "Varianza inversa (colonna)",
    "custom.preview": "Formula", "custom.check": "Verifica equazione", "custom.check_ok": "L'equazione è valida e definita ai valori iniziali.",
    "custom.grammar": "Usa X, i coefficienti elencati in Coefficienti, pi, e, numeri, + - * / ^ ( ) e le funzioni "
                      "{functions}.",
    "custom.add": "Aggiungi", "custom.remove": "Rimuovi", "custom.from_equation": "Aggiungi dall'equazione",
    "custom.start": "Valore iniziale", "custom.value": "Valore fissato", "custom.fixed_hint": "Fisso (mantieni questo valore, non stimare)",
    "custom.parameters_note": "Lascia vuoto un limite per non imporlo. Un coefficiente fisso è usato come scritto e non viene stimato.",
    "custom.column.name": "Nome", "custom.column.start": "Iniziale / valore", "custom.column.fixed": "Fisso",
    "custom.column.lower": "Minimo", "custom.column.upper": "Massimo",
    "custom.group_prefix": "Gruppo {group}:",
    "custom.error.name_chars": "Il nome del coefficiente {name} deve essere formato da lettere, cifre e trattini bassi, e iniziare con una lettera.",
    "custom.error.name_long": "Il nome del coefficiente {name}… supera i 32 caratteri.",
    "custom.error.reserved": "{name} è riservato (X, Y, pi, e e i nomi delle funzioni non possono essere coefficienti).",
    "custom.error.too_long": "L'equazione supera i 1024 caratteri.",
    "custom.error.unexpected_long": "Carattere {char} inatteso alla posizione {position}. Usa numeri, X, i coefficienti, + - * / ^ ( ) e le funzioni {functions}.",
    "custom.error.unexpected": "Carattere {char} inatteso alla posizione {position}.",
    "custom.error.bad_number": "Numero non valido vicino alla posizione {position} (numeri complessi, esadecimali e attributi non sono supportati).",
    "custom.error.not_finite_number": "Il numero {number} non è finito.",
    "custom.error.too_many_nodes": "L'equazione ha più di 128 elementi.",
    "custom.error.too_deep": "L'equazione è annidata per più di 32 livelli.",
    "custom.error.function_call": "{name} è una funzione: scrivila con un argomento tra parentesi, per esempio {example}.",
    "custom.error.close_call": "Manca ) dopo l'argomento di {name}.",
    "custom.error.one_argument": "{name} accetta un solo argomento.",
    "custom.error.unknown_function": "{name} non è una funzione disponibile. Funzioni: {functions}.",
    "custom.error.y_in_equation": "Y è la risposta e non può comparire nell'equazione.",
    "custom.error.undeclared": "{name} non è dichiarato come coefficiente. Aggiungilo ai Coefficienti o controlla l'ortografia (i nomi distinguono maiuscole e minuscole).",
    "custom.error.close_paren": "Manca ) per chiudere una parentesi.",
    "custom.error.ends_early": "L'equazione finisce troppo presto: manca qualcosa dopo la posizione {position}.",
    "custom.error.missing_value": "Manca il valore di {name}.",
    "custom.error.empty": "Scrivi un'equazione, per esempio A + B*X.",
    "custom.error.too_many_parameters": "Usa al massimo 12 coefficienti.",
    "custom.error.distinct_names": "I nomi dei coefficienti devono essere distinti.",
    "custom.error.unused": "L'equazione non usa {names}. Rimuovi il coefficiente o aggiungilo all'equazione.",
    "custom.error.parameter_list": "I coefficienti devono essere un elenco.",
    "custom.error.parameter_record": "Ogni coefficiente ha bisogno di un nome, di un valore iniziale e dei suoi limiti.",
    "custom.error.duplicate": "Il coefficiente {name} compare più di una volta.",
    "custom.error.fixed_flag": "{name}: Fisso deve essere vero o falso.",
    "custom.error.value_number": "{name}: il valore deve essere un numero finito.",
    "custom.error.start_number": "{name}: il valore iniziale deve essere un numero finito.",
    "custom.error.limit_order": "{name}: il limite minimo deve essere minore del massimo.",
    "custom.error.value_outside": "{name}: il valore {value} è fuori dai suoi limiti.",
    "custom.error.start_outside": "{name}: il valore iniziale {value} è fuori dai suoi limiti.",
    "custom.error.lower_number": "{name}: il limite minimo deve essere un numero finito oppure vuoto.",
    "custom.error.upper_number": "{name}: il limite massimo deve essere un numero finito oppure vuoto.",
    "custom.error.column": "Scegli una colonna esistente per {field}.",
    "custom.error.distinct_xy": "Scegli colonne diverse per X e Y.",
    "custom.error.group_column": "Il gruppo deve essere una colonna esistente diversa da X e Y.",
    "custom.error.weighting": "Scegli Senza pesi oppure Varianza inversa (colonna).",
    "custom.error.sd_choose": "Scegli la colonna con le deviazioni standard relative.",
    "custom.error.sd_differ": "La colonna SD deve essere diversa da X, Y e Gruppo.",
    "custom.error.level": "Il livello di confidenza deve essere compreso tra 0 e 100 (estremi esclusi).",
    "custom.error.points": "I punti della curva devono essere un intero da 20 a 10000.",
    "custom.error.non_numeric": "La colonna {column} contiene valori non numerici (prima riga sorgente {row}).",
    "custom.error.infinite": "La colonna {column} contiene valori infiniti.",
    "custom.error.group_ambiguous": "Valori diversi del gruppo risultano uguali come testo: rendili distinti prima.",
    "custom.error.groups_max": "Usa al massimo 12 gruppi.",
    "custom.error.groups_none": "La colonna dei gruppi non ha valori.",
    "custom.error.sd_positive": "La colonna SD richiede valori positivi in ogni riga usata (riga sorgente {row}). Lascia vuota una cella per saltare quella riga.",
    "custom.error.pairs_max": "L'analisi supporta fino a 100.000 coppie complete.",
    "custom.error.undefined_start": "L'equazione non è definita con i valori iniziali in X = {x} (riga sorgente {row}). Controlla divisioni, logaritmi e radici.",
    "custom.error.undefined_solution": "L'equazione non è definita nella soluzione in X = {x} (riga sorgente {row}). Controlla divisioni, logaritmi e radici.",
    "custom.error.undefined_curve": "L'equazione non è definita sulla curva disegnata in X = {x}.",
    "custom.error.no_pairs": "Nessuna coppia completa di X e Y.",
    "custom.error.too_few_rows": "{n} righe complete non bastano a stimare {p} coefficienti liberi: fissa alcuni coefficienti o aggiungi dati.",
    "custom.error.no_convergence": "Il fit non è convergente entro {count} valutazioni. Cambia i valori iniziali o i limiti, oppure fissa alcuni coefficienti.",
    "custom.error.rank": "I coefficienti non sono identificabili da questi dati (lo Jacobiano ha rango incompleto). Fissa o rimuovi coefficienti, oppure controlla l'equazione.",
})

# Global fit custom equation. gfit.error.* texts are the engine sentences that Fit custom equation does not already use.
_EN.update({
    "gfit.tab.variables": "Variables", "gfit.tab.equation": "Equation", "gfit.tab.parameters": "Parameters",
    "gfit.tab.series": "Series constraints", "gfit.tab.output": "Output",
    "gfit.field.X": "X", "gfit.field.Y": "Y", "gfit.field.Group": "Group", "gfit.field.Equation": "Equation",
    "gfit.field.Parameters": "Parameters", "gfit.field.Series constraints": "Series constraints",
    "gfit.field.Weighting": "Weighting", "gfit.field.SD column": "SD column",
    "gfit.field.Confidence level (%)": "Confidence level (%)", "gfit.field.Curve points": "Curve points",
    "gfit.weighting.unweighted": "Unweighted", "gfit.weighting.inverse_variance": "Inverse variance (column)",
    "gfit.check_ok": "The equation is valid and defined at the starting values.",
    "gfit.scope.local": "Local", "gfit.scope.shared": "Shared", "gfit.scope.fixed": "Fixed",
    "gfit.column.name": "Name", "gfit.column.scope": "Local / shared", "gfit.column.start": "Start / value",
    "gfit.column.lower": "Lower", "gfit.column.upper": "Upper",
    "gfit.add": "Add", "gfit.remove": "Remove", "gfit.from_equation": "Add from equation",
    "gfit.start": "Starting value", "gfit.value": "Fixed value",
    "gfit.parameters_note": "Local estimates one value per series. Shared estimates one value for every series. "
                            "Fixed keeps the typed value. Leave a limit empty for no limit.",
    "gfit.unused": "Not used by the equation: {names}. Remove the coefficient or add it to the equation.",
    "gfit.series.title": "Override limits and values for one series.",
    "gfit.series.series": "Series", "gfit.series.clear": "Clear this series", "gfit.series.clear_all": "Clear all overrides",
    "gfit.series.blank": "A blank field inherits the common setting. A fixed value and a start apply only to a local "
                         "coefficient. Bounds also apply to a shared coefficient.",
    "gfit.series.outside": "outside selection",
    "gfit.series.none": "Select X, Y and Group on the Variables tab.",
    "gfit.series.parameter": "Coefficient", "gfit.series.fixed": "Fixed value", "gfit.series.lower": "Lower",
    "gfit.series.upper": "Upper", "gfit.series.initial": "Start",
    "gfit.series.leftover": "Overrides remain for {names}. Remove them or restore the coefficient.",
    "gfit.series.outside_list": "Overrides remain for series outside the selection: {names}.",
    "gfit.error.flag": "{name}: {flag} must be true or false.",
    "gfit.error.both": "{name}: a coefficient cannot be both fixed and shared.",
    "gfit.error.group_required": "Group is required and must be an existing column different from X and Y.",
    "gfit.error.constraints_list": "Series constraints must be a list of series records.",
    "gfit.error.constraints_record": "Invalid series constraint record.",
    "gfit.error.constraints_duplicate": "Duplicate series constraint record for {label}.",
    "gfit.error.constraints_parameters": "Invalid parameters for series {label}.",
    "gfit.error.series_label": "A series label must be text or a finite number.",
    "gfit.error.series_unknown": "Series {label} is not among the series with complete rows. Remove that override or correct the name.",
    "gfit.error.series_shape": "Series {label}: specify overrides by coefficient.",
    "gfit.error.series_coefficient": "Series {label}, {name} is not a coefficient of this equation. Remove the override or restore the coefficient.",
    "gfit.error.series_keys": "Series {label}, {name}: use only fixed, lower, upper and initial.",
    "gfit.error.series_shared_override": "Series {label}, {name}: a shared coefficient cannot have its own fixed value or starting value. Set the common value on Parameters, or stop sharing it.",
    "gfit.error.series_already_fixed": "Series {label}, {name}: this coefficient is already fixed for every series. Remove the series override.",
    "gfit.error.series_limit_order": "Series {label}, {name}: the lower limit must be smaller than the upper limit.",
    "gfit.error.series_number": "Series {label}, {name}: {item} must be a finite number.",
    "gfit.error.series_fixed_and_initial": "Series {label}, {name}: a fixed coefficient does not need a starting value.",
    "gfit.error.series_fixed_outside": "Series {label}, {name}: the fixed value {value} lies outside its limits.",
    "gfit.error.series_start_outside": "Series {label}, {name}: the starting value {value} lies outside its limits.",
    "gfit.error.shared_overlap": "{name}: the shared limits do not overlap. Widen a series limit.",
    "gfit.error.shared_start": "{name}: the starting value {value} lies outside the shared limits. Change the start or the series limits.",
    "gfit.error.series_start_limits": "Series {label}, {name}: the starting value {value} lies outside the limits of this series.",
    "gfit.error.interior": "The limits leave no usable interior starting value.",
    "gfit.error.budget": "The global fit exceeds the dense Jacobian budget. Use fewer rows or share more coefficients.",
    "gfit.error.convergence": "The fit did not converge. Change the starting values or limits, or fix some coefficients.",
    "gfit.error.rss_range": "The residual sum of squares exceeds the numerical range.",
    "gfit.error.covariance_range": "The covariance of the global fit exceeds the numerical range.",
    "gfit.error.undefined_solution": "The equation is not defined at the solution.",
    "gfit.error.two_series": "Global fitting needs at least two series with complete observations.",
})
_IT.update({
    "gfit.tab.variables": "Variabili", "gfit.tab.equation": "Equazione", "gfit.tab.parameters": "Coefficienti",
    "gfit.tab.series": "Vincoli di serie", "gfit.tab.output": "Risultati",
    "gfit.field.X": "X", "gfit.field.Y": "Y", "gfit.field.Group": "Gruppo", "gfit.field.Equation": "Equazione",
    "gfit.field.Parameters": "Coefficienti", "gfit.field.Series constraints": "Vincoli di serie",
    "gfit.field.Weighting": "Pesatura", "gfit.field.SD column": "Colonna SD",
    "gfit.field.Confidence level (%)": "Livello di confidenza (%)", "gfit.field.Curve points": "Punti della curva",
    "gfit.weighting.unweighted": "Senza pesi", "gfit.weighting.inverse_variance": "Varianza inversa (colonna)",
    "gfit.check_ok": "L'equazione è valida e definita ai valori iniziali.",
    "gfit.scope.local": "Locale", "gfit.scope.shared": "Condiviso", "gfit.scope.fixed": "Fisso",
    "gfit.column.name": "Nome", "gfit.column.scope": "Locale / condiviso", "gfit.column.start": "Iniziale / valore",
    "gfit.column.lower": "Minimo", "gfit.column.upper": "Massimo",
    "gfit.add": "Aggiungi", "gfit.remove": "Rimuovi", "gfit.from_equation": "Aggiungi dall'equazione",
    "gfit.start": "Valore iniziale", "gfit.value": "Valore fissato",
    "gfit.parameters_note": "Locale stima un valore per ogni serie. Condiviso stima un solo valore per tutte le serie. "
                            "Fisso mantiene il valore scritto. Lascia vuoto un limite per non imporlo.",
    "gfit.unused": "Non usati nell'equazione: {names}. Rimuovi il coefficiente o aggiungilo all'equazione.",
    "gfit.series.title": "Sovrascrivi limiti e valori di una serie.",
    "gfit.series.series": "Serie", "gfit.series.clear": "Azzera questa serie",
    "gfit.series.clear_all": "Azzera tutti i vincoli",
    "gfit.series.blank": "Un campo vuoto eredita l'impostazione comune. Il valore fisso e l'iniziale valgono solo per un "
                         "coefficiente locale. I limiti valgono anche per un coefficiente condiviso.",
    "gfit.series.outside": "fuori selezione",
    "gfit.series.none": "Scegli X, Y e Gruppo nella scheda Variabili.",
    "gfit.series.parameter": "Coefficiente", "gfit.series.fixed": "Valore fisso", "gfit.series.lower": "Minimo",
    "gfit.series.upper": "Massimo", "gfit.series.initial": "Iniziale",
    "gfit.series.leftover": "Restano vincoli per {names}. Rimuovili o ripristina il coefficiente.",
    "gfit.series.outside_list": "Restano vincoli per serie fuori selezione: {names}.",
    "gfit.error.flag": "{name}: {flag} deve essere vero o falso.",
    "gfit.error.both": "{name}: un coefficiente non può essere insieme fisso e condiviso.",
    "gfit.error.group_required": "Il gruppo è obbligatorio e deve essere una colonna esistente diversa da X e Y.",
    "gfit.error.constraints_list": "I vincoli di serie devono essere un elenco di schede.",
    "gfit.error.constraints_record": "Scheda di vincolo di serie non valida.",
    "gfit.error.constraints_duplicate": "Scheda di vincolo duplicata per la serie {label}.",
    "gfit.error.constraints_parameters": "Coefficienti non validi per la serie {label}.",
    "gfit.error.series_label": "L'etichetta di una serie deve essere testo o un numero finito.",
    "gfit.error.series_unknown": "La serie {label} non è tra le serie con righe complete. Rimuovi quel vincolo o correggi il nome.",
    "gfit.error.series_shape": "Serie {label}: indica i vincoli coefficiente per coefficiente.",
    "gfit.error.series_coefficient": "Serie {label}, {name} non è un coefficiente di questa equazione. Rimuovi il vincolo o ripristina il coefficiente.",
    "gfit.error.series_keys": "Serie {label}, {name}: usa solo fixed, lower, upper e initial.",
    "gfit.error.series_shared_override": "Serie {label}, {name}: un coefficiente condiviso non può avere un valore fisso o iniziale proprio. Imposta il valore comune nei Coefficienti, oppure smetti di condividerlo.",
    "gfit.error.series_already_fixed": "Serie {label}, {name}: questo coefficiente è già fisso per ogni serie. Rimuovi il vincolo della serie.",
    "gfit.error.series_limit_order": "Serie {label}, {name}: il limite minimo deve essere minore del massimo.",
    "gfit.error.series_number": "Serie {label}, {name}: {item} deve essere un numero finito.",
    "gfit.error.series_fixed_and_initial": "Serie {label}, {name}: un coefficiente fisso non ha bisogno di un valore iniziale.",
    "gfit.error.series_fixed_outside": "Serie {label}, {name}: il valore fisso {value} è fuori dai suoi limiti.",
    "gfit.error.series_start_outside": "Serie {label}, {name}: il valore iniziale {value} è fuori dai suoi limiti.",
    "gfit.error.shared_overlap": "{name}: i limiti condivisi non si sovrappongono. Allarga un limite di serie.",
    "gfit.error.shared_start": "{name}: il valore iniziale {value} è fuori dai limiti condivisi. Cambia l'iniziale o i limiti di serie.",
    "gfit.error.series_start_limits": "Serie {label}, {name}: il valore iniziale {value} è fuori dai limiti di questa serie.",
    "gfit.error.interior": "I limiti non lasciano un valore iniziale interno utilizzabile.",
    "gfit.error.budget": "Il fit globale supera il budget dello Jacobiano denso. Usa meno righe o condividi più coefficienti.",
    "gfit.error.convergence": "Il fit non è convergente. Cambia i valori iniziali o i limiti, oppure fissa alcuni coefficienti.",
    "gfit.error.rss_range": "La somma dei quadrati dei residui supera l'intervallo numerico.",
    "gfit.error.covariance_range": "La covarianza del fit globale supera l'intervallo numerico.",
    "gfit.error.undefined_solution": "L'equazione non è definita nella soluzione.",
    "gfit.error.two_series": "Il fit globale richiede almeno due serie con osservazioni complete.",
})

# Global fit custom equation, 0.70: response bands and predictions for new X. Recipes keep the English keys and
# values; gfit.error.* are the engine sentences of global_uncertainty, matched with their placeholders.
_EN.update({
    "gfit.tab.response": "Response",
    "gfit.field.Curve band": "Curve band", "gfit.field.Response level (%)": "Response level (%)",
    "gfit.field.Band drawing": "Band drawing", "gfit.field.Predict responses": "Predict responses",
    "gfit.field.Query X": "Query X", "gfit.field.Query group": "Query group",
    "gfit.field.Query interval": "Query interval", "gfit.field.Query replicate count": "Query replicate count",
    "gfit.field.Allow extrapolation": "Allow extrapolation",
    "gfit.choice.none": "None", "gfit.choice.confidence": "Confidence (mean)",
    "gfit.choice.prediction": "Prediction (new observations)", "gfit.choice.filled": "Filled",
    "gfit.choice.lines": "Lines",
    "gfit.response.note": "Confidence is for the fitted mean response; Prediction is for new observations, so it "
                          "adds the residual variance. The curve band is for one new observation. For a query, "
                          "Query replicate count k gives the interval of the mean of k new observations (empty = 1). "
                          "Intervals are pointwise, at the response level, from the covariance of this one joint "
                          "fit; the Confidence level (%) on Output applies to the coefficients only. Query columns "
                          "never add observations to the fit.",
    "gfit.error.response_level": "The response level must be a number strictly between 0 and 100.",
    "gfit.error.band_choice": "Choose None, Confidence or Prediction for the curve band.",
    "gfit.error.band_weights": "Curve bands are available for Unweighted fits only. With an SD column the variance "
                               "of a new observation is not defined along the curve. Use Unweighted, or turn the band "
                               "off.",
    "gfit.error.band_unweighted": "Curve bands are available for Unweighted fits only.",
    "gfit.error.drawing_choice": "Choose Filled or Lines for the band drawing.",
    "gfit.error.flag_on_off": "{field} must be on or off.",
    "gfit.error.query_x_column": "Choose the column with the X values to predict.",
    "gfit.error.query_group_column": "Choose the column that assigns each new X to a series.",
    "gfit.error.query_group_same": "Query group must be a different column from Query X.",
    "gfit.error.query_interval_choice": "Choose None, Confidence or Prediction for the query interval.",
    "gfit.error.query_weights": "Intervals for new X values are available for Unweighted fits only. With an SD "
                                "column only the predicted values are given: choose None.",
    "gfit.error.query_k_column": "Choose an existing column for the replicate count, or leave it empty for k = 1.",
    "gfit.error.query_k_same": "The replicate count column must differ from Query X and Query group.",
    "gfit.error.query_x_infinite": "Column {column} contains infinite values (source row {row}).",
    "gfit.error.query_x_text": "Column {column} must hold real numbers; source row {row} contains {value}.",
    "gfit.error.query_k_value": "Column {column}: the replicate count must be a whole number from 1 to 2^53 "
                                "(source row {row} contains {value}).",
    "gfit.error.query_limit": "Predict at most {count} rows at a time.",
    "gfit.error.budget_bands": "The response bands exceed the uncertainty budget of {cells} cells. Use fewer curve "
                               "points.",
    "gfit.error.budget_bands_queries": "The response bands exceed the uncertainty budget of {cells} cells. Use fewer "
                                       "curve points or fewer queries.",
    "gfit.error.budget_queries": "The predictions exceed the uncertainty budget of {cells} cells. Use fewer query "
                                 "rows.",
})
_IT.update({
    "gfit.tab.response": "Bande e previsioni",
    "gfit.field.Curve band": "Banda della curva", "gfit.field.Response level (%)": "Livello della risposta (%)",
    "gfit.field.Band drawing": "Disegno della banda", "gfit.field.Predict responses": "Prevedi risposte",
    "gfit.field.Query X": "X da prevedere", "gfit.field.Query group": "Serie della previsione",
    "gfit.field.Query interval": "Intervallo della previsione", "gfit.field.Query replicate count": "Numero di repliche",
    "gfit.field.Allow extrapolation": "Consenti estrapolazione",
    "gfit.choice.none": "Nessuno", "gfit.choice.confidence": "Confidenza (media)",
    "gfit.choice.prediction": "Predizione (nuove osservazioni)", "gfit.choice.filled": "Area",
    "gfit.choice.lines": "Linee",
    "gfit.response.note": "Confidenza riguarda la risposta media prevista; Predizione riguarda nuove osservazioni e "
                          "aggiunge la varianza residua. La banda della curva vale per una nuova osservazione. Per "
                          "una previsione, il Numero di repliche k dà l'intervallo della media di k nuove "
                          "osservazioni (vuoto = 1). Gli intervalli sono puntuali, al livello della risposta, dalla "
                          "covarianza di questo unico fit congiunto; il Livello di confidenza (%) in Risultati vale "
                          "solo per i coefficienti. Le colonne delle previsioni non aggiungono osservazioni al fit.",
    "gfit.error.response_level": "Il livello della risposta deve essere un numero strettamente compreso tra 0 e 100.",
    "gfit.error.band_choice": "Scegli Nessuno, Confidenza o Predizione per la banda della curva.",
    "gfit.error.band_weights": "Le bande della curva sono disponibili solo per i fit senza pesi. Con una colonna SD la "
                               "varianza di una nuova osservazione non è definita lungo la curva. Usa Senza pesi "
                               "oppure disattiva la banda.",
    "gfit.error.band_unweighted": "Le bande della curva sono disponibili solo per i fit senza pesi.",
    "gfit.error.drawing_choice": "Scegli Area o Linee per il disegno della banda.",
    "gfit.error.flag_on_off": "{field}: scegli attivo o disattivo.",
    "gfit.error.query_x_column": "Scegli la colonna con le X da prevedere.",
    "gfit.error.query_group_column": "Scegli la colonna che assegna ogni nuova X a una serie.",
    "gfit.error.query_group_same": "La serie della previsione deve essere una colonna diversa da X da prevedere.",
    "gfit.error.query_interval_choice": "Scegli Nessuno, Confidenza o Predizione per l'intervallo della previsione.",
    "gfit.error.query_weights": "Gli intervalli per nuove X sono disponibili solo per i fit senza pesi. Con una "
                                "colonna SD si ottengono solo i valori previsti: scegli Nessuno.",
    "gfit.error.query_k_column": "Scegli una colonna esistente per il numero di repliche, oppure lasciala vuota per "
                                 "k = 1.",
    "gfit.error.query_k_same": "La colonna del numero di repliche deve essere diversa da X da prevedere e dalla serie "
                               "della previsione.",
    "gfit.error.query_x_infinite": "La colonna {column} contiene valori infiniti (riga sorgente {row}).",
    "gfit.error.query_x_text": "La colonna {column} deve contenere numeri reali; la riga sorgente {row} contiene "
                               "{value}.",
    "gfit.error.query_k_value": "Colonna {column}: il numero di repliche deve essere un intero da 1 a 2^53 (la riga "
                                "sorgente {row} contiene {value}).",
    "gfit.error.query_limit": "Prevedi al massimo {count} righe alla volta.",
    "gfit.error.budget_bands": "Le bande della risposta superano il limite di calcolo di {cells} celle. Usa meno "
                               "punti della curva.",
    "gfit.error.budget_bands_queries": "Le bande della risposta superano il limite di calcolo di {cells} celle. Usa "
                                       "meno punti della curva o meno previsioni.",
    "gfit.error.budget_queries": "Le previsioni superano il limite di calcolo di {cells} celle. Usa meno righe da "
                                 "prevedere.",
})

# Ordinal trend after ordinary one-way ANOVA. English text matches the engine fallbacks.
_EN.update({
    "analysis.trend.heading.trend": "Linear trend",
    "analysis.trend.heading.order": "Trend group order",
    "analysis.trend.up": "Up",
    "analysis.trend.down": "Down",
    "analysis.trend.note.positions": "Scores are equally spaced positions. Group titles are not doses.",
    "analysis.trend.removed": "removed",
    "analysis.trend.added": "new",
    "analysis.trend.review": "Review the order. Removed: {removed}. New: {added}.",
    "analysis.trend.kind.number": "number",
    "analysis.trend.kind.text": "text",
    "analysis.trend.error.order_shape": "Trend group order must list each level as text or a finite number.",
    "analysis.trend.error.duplicate": "Trend group order lists the same level more than once.",
    "analysis.trend.error.levels": "Trend group order must list each remaining level once. Review {levels}.",
    "analysis.trend.error.identity": "Linear trend cannot use this group level. Turn the trend off or remove the unsupported level.",
    "analysis.trend.error.degrees": "Linear trend needs at least two groups and residual degrees of freedom.",
    "analysis.trend.error.numeric": "Linear trend is outside the supported numeric range.",
    "analysis.trend.error.variance": "Linear trend needs a positive pooled variance.",
    "analysis.trend.error.method": "Linear trend requires an ordinary independent ANOVA.",
    "analysis.trend.note.planned": "The linear and nonlinear tests are planned contrasts and are not adjusted for multiplicity. "
                                   "The slope is the change in the response for one group position, not for a dose written in the title.",
    "analysis.trend.note.flat": "The group means do not differ, so R² alerting is not available.",
    "analysis.trend.note.few_groups": "The nonlinear test is published from four groups upward.",
})
_IT.update({
    "analysis.trend.heading.trend": "Trend lineare",
    "analysis.trend.heading.order": "Ordine dei gruppi del trend",
    "analysis.trend.up": "Su",
    "analysis.trend.down": "Giù",
    "analysis.trend.note.positions": "I punteggi sono posizioni equidistanti. I titoli dei gruppi non sono dosi.",
    "analysis.trend.removed": "rimosso",
    "analysis.trend.added": "nuovo",
    "analysis.trend.review": "Rivedi l'ordine. Rimossi: {removed}. Nuovi: {added}.",
    "analysis.trend.kind.number": "numero",
    "analysis.trend.kind.text": "testo",
    "analysis.trend.error.order_shape": "L'ordine dei gruppi del trend deve elencare ogni livello come testo o come numero finito.",
    "analysis.trend.error.duplicate": "L'ordine dei gruppi del trend elenca lo stesso livello più di una volta.",
    "analysis.trend.error.levels": "L'ordine dei gruppi del trend deve elencare ogni livello rimasto una sola volta. Rivedi {levels}.",
    "analysis.trend.error.identity": "Il trend lineare non può usare questo livello di gruppo. Spegni il trend o rimuovi il livello non supportato.",
    "analysis.trend.error.degrees": "Il trend lineare richiede almeno due gruppi e gradi di libertà residui.",
    "analysis.trend.error.numeric": "Il trend lineare è fuori dall'intervallo numerico supportato.",
    "analysis.trend.error.variance": "Il trend lineare richiede una varianza pooled positiva.",
    "analysis.trend.error.method": "Il trend lineare richiede un'ANOVA ordinaria su gruppi indipendenti.",
    "analysis.trend.note.planned": "I test lineare e non lineare sono contrasti pianificati e non sono corretti di nuovo per la molteplicità. "
                                   "La pendenza è la variazione della risposta per una posizione di gruppo, non per una dose scritta nel titolo.",
    "analysis.trend.note.flat": "Le medie dei gruppi non differiscono, quindi R² alerting non è disponibile.",
    "analysis.trend.note.few_groups": "Il test non lineare è pubblicato da quattro gruppi in su.",
})

# Optional nonlinear-fit diagnostics. English text matches the engine fallbacks.
_EN.update({
    "analysis.fit.heading.runs": "Runs test",
    "analysis.fit.heading.replicates": "Replicate lack of fit",
    "analysis.fit.heading.residuals": "Residuals versus X",
    "analysis.fit.note.diagnostics": "The runs test and the replicate lack-of-fit test require an unweighted fit. "
                                     "Residuals versus X shows the raw residuals.",
    "analysis.fit.error.unweighted": "This diagnostic requires unweighted fitting.",
    "analysis.fit.runs.nonfinite": "Runs test needs finite X values and finite residuals.",
    "analysis.fit.runs.duplicate": "X values are repeated. Use the replicate lack-of-fit test instead of the runs test.",
    "analysis.fit.runs.order": "X values are not strictly increasing. Reorder the source rows and calculate again.",
    "analysis.fit.runs.budget": "Runs test uses an exact distribution and is available for up to 2000 fitted rows.",
    "analysis.fit.runs.domain": "Runs test needs more than five non-zero residuals and at least two of each sign.",
    "analysis.fit.runs.available": "Exact lower tail conditional on the sign counts. This does not prove that the errors are independent.",
    "analysis.fit.lof.parameters": "Replicate lack of fit needs a nonnegative whole number of free parameters.",
    "analysis.fit.lof.nonfinite": "Replicate lack of fit needs finite X values, observations and predictions.",
    "analysis.fit.lof.inconsistent": "Predictions at the same X do not agree, so lack of fit was not calculated.",
    "analysis.fit.lof.residuals": "The stored residuals do not agree with the fit, so lack of fit was not calculated.",
    "analysis.fit.lof.negative": "The lack-of-fit sum of squares is negative beyond the numeric tolerance.",
    "analysis.fit.lof.no_replicates": "Replicate lack of fit needs repeated X values.",
    "analysis.fit.lof.no_degrees": "Replicate lack of fit needs more distinct X values than free parameters.",
    "analysis.fit.lof.zero_both": "Pure error is zero and lack of fit is zero, so F and p are not available.",
    "analysis.fit.lof.zero_pure": "Pure error is zero while lack of fit is positive, so F and p are not available.",
    "analysis.fit.lof.available": "Comparison of lack of fit with the variation among replicates.",
    "analysis.fit.lof.clamped": "A tiny negative lack-of-fit sum of squares was set to zero.",
    "analysis.fit.lof.note": "The F reference is exact for a regular linear model with independent normal "
                             "homoscedastic errors. For a nonlinear mean it is an approximate diagnostic. "
                             "A p value that is not small does not show that the curve is correct.",
})
_IT.update({
    "analysis.fit.heading.runs": "Test delle sequenze",
    "analysis.fit.heading.replicates": "Mancato adattamento tra repliche",
    "analysis.fit.heading.residuals": "Residui rispetto a X",
    "analysis.fit.note.diagnostics": "Il runs test e il test di lack of fit sulle repliche richiedono un fit senza pesi. "
                                     "Residui contro X mostra i residui grezzi.",
    "analysis.fit.error.unweighted": "Questa diagnostica richiede un fit senza pesi.",
    "analysis.fit.runs.nonfinite": "Il runs test richiede valori di X e residui finiti.",
    "analysis.fit.runs.duplicate": "I valori di X sono ripetuti. Usa il test di lack of fit sulle repliche al posto del runs test.",
    "analysis.fit.runs.order": "I valori di X non sono strettamente crescenti. Riordina le righe di origine e calcola di nuovo.",
    "analysis.fit.runs.budget": "Il runs test usa una distribuzione esatta ed è disponibile fino a 2000 righe del fit.",
    "analysis.fit.runs.domain": "Il runs test richiede più di cinque residui non nulli e almeno due per ciascun segno.",
    "analysis.fit.runs.available": "Coda inferiore esatta condizionata ai conteggi dei segni. Questo non dimostra che gli errori siano indipendenti.",
    "analysis.fit.lof.parameters": "Il lack of fit sulle repliche richiede un numero intero non negativo di parametri liberi.",
    "analysis.fit.lof.nonfinite": "Il lack of fit sulle repliche richiede X, osservazioni e previsioni finite.",
    "analysis.fit.lof.inconsistent": "Le previsioni allo stesso X non coincidono, quindi il lack of fit non è stato calcolato.",
    "analysis.fit.lof.residuals": "I residui salvati non coincidono con il fit, quindi il lack of fit non è stato calcolato.",
    "analysis.fit.lof.negative": "La somma dei quadrati di lack of fit è negativa oltre la tolleranza numerica.",
    "analysis.fit.lof.no_replicates": "Il lack of fit sulle repliche richiede valori di X ripetuti.",
    "analysis.fit.lof.no_degrees": "Il lack of fit sulle repliche richiede più valori distinti di X che parametri liberi.",
    "analysis.fit.lof.zero_both": "L'errore puro è zero e il lack of fit è zero, quindi F e p non sono disponibili.",
    "analysis.fit.lof.zero_pure": "L'errore puro è zero mentre il lack of fit è positivo, quindi F e p non sono disponibili.",
    "analysis.fit.lof.available": "Confronto del lack of fit con la variazione fra le repliche.",
    "analysis.fit.lof.clamped": "Una somma dei quadrati di lack of fit negativa e minuscola è stata posta a zero.",
    "analysis.fit.lof.note": "Il riferimento F è esatto per un modello lineare regolare con errori normali indipendenti "
                             "e omoschedastici. Per una media non lineare è una diagnostica approssimata. "
                             "Un valore p non piccolo non dimostra che la curva sia corretta.",
})

# Independent native arrowheads and hatch fills. Recipe values stay canonical.
_EN.update({
    "shape.arrow_heads": "Line endings", "shape.arrow_style": "Ending style", "shape.arrow_size": "Ending size (pt)",
    "shape.hatch": "Fill pattern", "shape.option.none": "None", "shape.option.start": "At start",
    "shape.option.end": "At end", "shape.option.both": "At both ends", "shape.option.open": "Open",
    "shape.option.filled": "Filled", "shape.option.diagonal": "Diagonal", "shape.option.cross": "Crosshatch",
    "shape.option.dots": "Dots", "shape.option.arrow": "Arrow",
    "shape.error.arrow_heads": "Choose a valid arrowhead direction.",
    "shape.option.capped_line": "Capped line", "shape.option.cap": "Perpendicular cap",
    "shape.error.arrow_style": "Choose open or filled arrowheads, or perpendicular caps.",
    "shape.error.arrow_size": "Enter an arrowhead size between 3 and 40 points.",
    "shape.error.hatch": "Choose a valid fill pattern.",
})
_IT.update({
    "shape.arrow_heads": "Terminali della linea", "shape.arrow_style": "Stile dei terminali", "shape.arrow_size": "Dimensione terminali (pt)",
    "shape.hatch": "Motivo riempimento", "shape.option.none": "Nessuno", "shape.option.start": "All'inizio",
    "shape.option.end": "Alla fine", "shape.option.both": "A entrambe le estremità", "shape.option.open": "Aperte",
    "shape.option.filled": "Piene", "shape.option.diagonal": "Diagonale", "shape.option.cross": "Incrociato",
    "shape.option.dots": "Punti", "shape.option.arrow": "Freccia",
    "shape.error.arrow_heads": "Scegli una direzione valida per le punte della freccia.",
    "shape.option.capped_line": "Linea con terminali", "shape.option.cap": "Barra perpendicolare",
    "shape.error.arrow_style": "Scegli punte aperte o piene, oppure barre perpendicolari.",
    "shape.error.arrow_size": "Inserisci una dimensione delle punte tra 3 e 40 punti.",
    "shape.error.hatch": "Scegli un motivo di riempimento valido.",
})

_EN.update({
    "shape.page.appearance": "Appearance", "shape.page.position": "Position",
    "shape.group.stroke": "Line / border", "shape.group.fill": "Interior",
    "shape.group.endings": "Line endings", "shape.group.order": "Opacity and order",
})
_IT.update({
    "shape.page.appearance": "Aspetto", "shape.page.position": "Posizione",
    "shape.group.stroke": "Linea / contorno", "shape.group.fill": "Interno",
    "shape.group.endings": "Terminali della linea", "shape.group.order": "Opacità e ordine",
})

_EN.update({
    'shape.context.format':'Format object…', 'shape.context.color_line':'Line color…',
    'shape.context.color_area':'Border color…', 'shape.context.width_line':'Line thickness',
    'shape.context.width_area':'Border thickness', 'shape.context.style_line':'Line style',
    'shape.context.style_area':'Border style', 'shape.context.fill_color':'Fill color…',
    'shape.context.no_fill':'No fill', 'shape.context.duplicate':'Duplicate object',
    'shape.context.remove':'Remove object', 'shape.context.front':'Bring drawing to front',
    'shape.context.back':'Send drawing to back', 'shape.context.missing':'The drawing is no longer available.',
    'shape.context.invalid':'Choose a supported drawing action.',
})
_IT.update({
    'shape.context.format':'Formatta oggetto…', 'shape.context.color_line':'Colore linea…',
    'shape.context.color_area':'Colore contorno…', 'shape.context.width_line':'Spessore linea',
    'shape.context.width_area':'Spessore contorno', 'shape.context.style_line':'Stile linea',
    'shape.context.style_area':'Stile contorno', 'shape.context.fill_color':'Colore riempimento…',
    'shape.context.no_fill':'Nessun riempimento', 'shape.context.duplicate':'Duplica oggetto',
    'shape.context.remove':'Elimina oggetto', 'shape.context.front':'Porta il disegno in primo piano',
    'shape.context.back':'Porta il disegno sullo sfondo', 'shape.context.missing':'Il disegno non è più disponibile.',
    'shape.context.invalid':'Scegli un’azione valida per il disegno.',
})

# Direct drawing uses independent explicit plot-coordinate conventions.
_EN.update({
    "shape.canvas.manage": "Manage shapes…", "shape.canvas.select": "Select / move shapes",
    "shape.canvas.line": "Draw line", "shape.canvas.arrow": "Draw arrow",
    "shape.canvas.rectangle": "Draw rectangle", "shape.canvas.ellipse": "Draw ellipse",
    "shape.canvas.stop": "Stop drawing", "shape.canvas.off": "Drawing mode off.",
    "shape.canvas.help": "Drag to move; Ctrl: horizontal, Shift: vertical. Arrows: 1 px, Ctrl+arrows: 10 px. Delete removes, Esc cancels.",
    "shape.canvas.draw_help": "Drag inside the plot to draw. Ctrl makes a square/circle; Shift keeps the tool; Esc cancels.",
    "shape.canvas.invalid": "Keep the shape within its coordinate and axis limits. The change was cancelled.",
    "shape.canvas.changed": "Shape updated. Undo/Redo affects shapes on this graph.",
    "shape.canvas.undo": "Undid shape edit.", "shape.canvas.redo": "Redid shape edit.",
})
_IT.update({
    "shape.canvas.manage": "Gestisci forme…", "shape.canvas.select": "Seleziona / sposta forme",
    "shape.canvas.line": "Disegna linea", "shape.canvas.arrow": "Disegna freccia",
    "shape.canvas.rectangle": "Disegna rettangolo", "shape.canvas.ellipse": "Disegna ellisse",
    "shape.canvas.stop": "Termina disegno", "shape.canvas.off": "Modalità disegno disattivata.",
    "shape.canvas.help": "Trascina per spostare; Ctrl: orizzontale, Maiusc: verticale. Frecce: 1 px, Ctrl+frecce: 10 px. Canc elimina, Esc annulla.",
    "shape.canvas.draw_help": "Trascina nel grafico. Ctrl crea quadrati/cerchi; Maiusc mantiene lo strumento; Esc annulla.",
    "shape.canvas.invalid": "Mantieni la forma entro i limiti delle coordinate e degli assi. Modifica annullata.",
    "shape.canvas.changed": "Forma aggiornata. Annulla/Ripeti agisce sulle forme di questo grafico.",
    "shape.canvas.undo": "Modifica della forma annullata.", "shape.canvas.redo": "Modifica della forma ripristinata.",
})

# Lognormal t-test: captions and choices on screen; recipes keep the English field names and values.
_EN.update({
    "ratio_t.tab.data": "Data", "ratio_t.tab.test": "Test and graph",
    "ratio_t.field.design": "Design", "ratio_t.field.first": "First column", "ratio_t.field.second": "Second column",
    "ratio_t.field.report": "Report ratio", "ratio_t.field.null": "Null ratio",
    "ratio_t.field.reference": "Hypothetical geometric mean", "ratio_t.field.level": "Confidence level (%)",
    "ratio_t.field.alternative": "Alternative", "ratio_t.field.base": "Log base", "ratio_t.field.graph": "Graph",
    "ratio_t.field.pairing": "Pairing correlation",
    "ratio_t.choice.paired": "Paired", "ratio_t.choice.welch": "Welch", "ratio_t.choice.student": "Student",
    "ratio_t.choice.one_sample": "One-sample", "ratio_t.choice.first_second": "First / Second",
    "ratio_t.choice.second_first": "Second / First", "ratio_t.choice.two_sided": "Two-sided",
    "ratio_t.choice.greater": "Greater", "ratio_t.choice.less": "Less", "ratio_t.choice.natural": "e (natural)",
    "ratio_t.choice.estimation": "Ratio estimation", "ratio_t.choice.observations": "Log observations",
    "ratio_t.choice.ratios": "Log ratios", "ratio_t.choice.none": "None",
})
_IT.update({
    "ratio_t.tab.data": "Dati", "ratio_t.tab.test": "Test e grafico",
    "ratio_t.field.design": "Disegno", "ratio_t.field.first": "Prima colonna", "ratio_t.field.second": "Seconda colonna",
    "ratio_t.field.report": "Rapporto riportato", "ratio_t.field.null": "Rapporto nullo",
    "ratio_t.field.reference": "Media geometrica ipotetica", "ratio_t.field.level": "Livello di confidenza (%)",
    "ratio_t.field.alternative": "Ipotesi alternativa", "ratio_t.field.base": "Base del logaritmo",
    "ratio_t.field.graph": "Grafico", "ratio_t.field.pairing": "Correlazione di appaiamento",
    "ratio_t.choice.paired": "Appaiato", "ratio_t.choice.welch": "Welch", "ratio_t.choice.student": "Student",
    "ratio_t.choice.one_sample": "Un campione", "ratio_t.choice.first_second": "Primo / Secondo",
    "ratio_t.choice.second_first": "Secondo / Primo", "ratio_t.choice.two_sided": "Bilaterale",
    "ratio_t.choice.greater": "Maggiore", "ratio_t.choice.less": "Minore", "ratio_t.choice.natural": "e (naturale)",
    "ratio_t.choice.estimation": "Stima del rapporto", "ratio_t.choice.observations": "Osservazioni logaritmiche",
    "ratio_t.choice.ratios": "Rapporti logaritmici", "ratio_t.choice.none": "Nessuno",
})

# Equivalence test (TOST): captions, choices and validation messages; recipes keep the English names and values.
# The "tost.error." entries match the English text raised by the engine (see translate_message).
_EN.update({
    "tost.tab.data": "Data", "tost.tab.zone": "Equivalence zone",
    "tost.field.design": "Design", "tost.field.response": "Response", "tost.field.reference": "Reference",
    "tost.field.first": "First column", "tost.field.second": "Second column",
    "tost.field.lower": "Lower margin", "tost.field.upper": "Upper margin", "tost.field.alpha": "Alpha",
    "tost.choice.one_sample": "One-sample", "tost.choice.paired": "Paired", "tost.choice.student": "Student",
    "tost.choice.welch": "Welch",
    "tost.hint": "Declare the zone before looking at the data, in the units of the difference "
                 "(First − Second; Sample − Reference for One-sample). Equivalence is concluded only when both "
                 "one-sided tests are below Alpha, that is, when the whole interval lies inside the zone.",
    "tost.error.design": "Design: choose One-sample, Paired, Student or Welch.",
    "tost.error.number": "{field} must be a finite number.",
    "tost.error.lower": "Lower margin must be below zero.",
    "tost.error.upper": "Upper margin must be above zero.",
    "tost.error.alpha": "Alpha must be greater than 0 and less than 0.5.",
    "tost.error.choose": "Choose a column for {field}.",
    "tost.error.exists": 'Choose an existing column for {field}: "{column}" is not in the worksheet.',
    "tost.error.unique": "Worksheet column names must be unique.",
    "tost.error.different": "Choose different columns for First and Second.",
    "tost.error.cell": 'Column "{column}" must hold finite numbers in the rows used. '
                       "Source row {row} is not a finite number.",
    "tost.error.cells": 'Column "{column}" must hold finite numbers in the rows used. '
                        "Source row {row} is not a finite number ({count} cells are unusable).",
    "tost.error.few": 'Column "{column}" needs at least two finite values; {count} found.',
    "tost.error.pairs": "A paired test needs at least two complete pairs; {count} found.",
})
_IT.update({
    "tost.tab.data": "Dati", "tost.tab.zone": "Zona di equivalenza",
    "tost.field.design": "Disegno", "tost.field.response": "Risposta", "tost.field.reference": "Valore di riferimento",
    "tost.field.first": "Prima colonna", "tost.field.second": "Seconda colonna",
    "tost.field.lower": "Margine inferiore", "tost.field.upper": "Margine superiore", "tost.field.alpha": "Alfa",
    "tost.choice.one_sample": "Un campione", "tost.choice.paired": "Appaiato", "tost.choice.student": "Student",
    "tost.choice.welch": "Welch",
    "tost.hint": "Dichiara la zona prima di guardare i dati, nelle unità della differenza "
                 "(Prima − Seconda; Campione − Riferimento per Un campione). L’equivalenza si conclude solo se "
                 "entrambi i test unilaterali sono sotto Alfa, cioè se l’intero intervallo sta dentro la zona.",
    "tost.error.design": "Disegno: scegli Un campione, Appaiato, Student o Welch.",
    "tost.error.number": "Il campo {field} deve essere un numero finito.",
    "tost.error.lower": "Margine inferiore: deve essere minore di zero.",
    "tost.error.upper": "Margine superiore: deve essere maggiore di zero.",
    "tost.error.alpha": "Alfa: deve essere maggiore di 0 e minore di 0,5.",
    "tost.error.choose": "Scegli una colonna nel campo {field}.",
    "tost.error.exists": 'Scegli una colonna esistente nel campo {field}: "{column}" non è nel foglio.',
    "tost.error.unique": "I nomi delle colonne del foglio devono essere univoci.",
    "tost.error.different": "Scegli colonne diverse per la prima e la seconda.",
    "tost.error.cell": 'La colonna "{column}" deve contenere numeri finiti nelle righe usate. '
                       "La riga origine {row} non è un numero finito.",
    "tost.error.cells": 'La colonna "{column}" deve contenere numeri finiti nelle righe usate. '
                        "La riga origine {row} non è un numero finito ({count} celle non utilizzabili).",
    "tost.error.few": 'La colonna "{column}" richiede almeno due valori finiti; ne risultano {count}.',
    "tost.error.pairs": "Un test appaiato richiede almeno due coppie complete; ne risultano {count}.",
})

# Robust curve fit (0.73): captions, choices, editor and validation messages. The "analysis.robust_curve.error."
# entries are the exact English messages of the engine with placeholders (see translate_message). Recipes keep the
# English field names and values.
_EN.update({
    "analysis.robust_curve.tab.variables": "Variables", "analysis.robust_curve.tab.loss": "Loss and scale",
    "analysis.robust_curve.tab.output": "Output",
    "analysis.robust_curve.field.X": "X", "analysis.robust_curve.field.Y columns": "Y columns",
    "analysis.robust_curve.field.Group": "Group", "analysis.robust_curve.field.Model": "Model",
    "analysis.robust_curve.field.Loss": "Loss", "analysis.robust_curve.field.Scale method": "Scale method",
    "analysis.robust_curve.field.Residual scale": "Residual scale",
    "analysis.robust_curve.field.Initial parameters": "Initial parameters",
    "analysis.robust_curve.field.Maximum evaluations": "Maximum evaluations",
    "analysis.robust_curve.field.Low weight threshold": "Low weight threshold",
    "analysis.robust_curve.field.Compare ordinary fit": "Compare ordinary fit",
    "analysis.robust_curve.field.Graph display": "Graph display",
    "analysis.robust_curve.choice.cauchy": "Cauchy", "analysis.robust_curve.choice.huber": "Huber",
    "analysis.robust_curve.choice.soft_l1": "Soft L1", "analysis.robust_curve.choice.fixed": "Fixed",
    "analysis.robust_curve.choice.pilot_mad": "Pilot MAD", "analysis.robust_curve.choice.curve": "Curve",
    "analysis.robust_curve.choice.residuals": "Residuals", "analysis.robust_curve.choice.weights": "Weights",
    "analysis.robust_curve.hint.scale": "Fixed uses one residual scale for the whole fit. Pilot MAD first fits "
                                        "ordinary least squares and takes the scale from the median absolute "
                                        "deviation of its residuals.",
    "analysis.robust_curve.hint.output": "Influence weights are diagnostics, not an outlier test: every point "
                                         "stays in the fit and in the graph. A point with an extreme X can still "
                                         "pull the curve.",
    "analysis.robust_curve.initial.catalog": "Catalog starting values",
    "analysis.robust_curve.initial.custom": "Custom: {values}", "analysis.robust_curve.initial.edit": "Edit…",
    "analysis.robust_curve.editor.title": "Initial parameters", "analysis.robust_curve.editor.model": "Model: {model}",
    "analysis.robust_curve.editor.note": "The catalog values are proposed from the data of the first fit. Reset "
                                         "returns to the catalog; Apply stores every value shown.",
    "analysis.robust_curve.editor.parameter": "Parameter", "analysis.robust_curve.editor.start": "Starting value",
    "analysis.robust_curve.editor.catalog": "Catalog", "analysis.robust_curve.editor.limits": "Limits",
    "analysis.robust_curve.editor.reset": "Reset", "analysis.robust_curve.editor.apply": "Apply",
    "analysis.robust_curve.editor.cancel": "Cancel",
    "analysis.robust_curve.error.choose": "Choose a column for {field}.",
    "analysis.robust_curve.error.select": "Select at least one column for {field}.",
    "analysis.robust_curve.error.exists": 'Choose an existing column for {field}: "{column}" is not in the worksheet.',
    "analysis.robust_curve.error.unique": "Worksheet column names must be unique.",
    "analysis.robust_curve.error.y_empty": "Choose at least one Y column.",
    "analysis.robust_curve.error.y_duplicate": 'Y columns must be distinct: "{column}" is chosen more than once.',
    "analysis.robust_curve.error.x_in_y": 'X and Y columns must be different: "{column}" is both.',
    "analysis.robust_curve.error.group_role": 'Group must differ from X and the Y columns: "{column}" is already used.',
    "analysis.robust_curve.error.model": "Model: choose a supported model of the catalog.",
    "analysis.robust_curve.error.loss": "Loss: choose Cauchy, Huber or Soft L1.",
    "analysis.robust_curve.error.scale_method": "Scale method: choose Fixed or Pilot MAD.",
    "analysis.robust_curve.error.scale": "Residual scale must be a finite number greater than 0.",
    "analysis.robust_curve.error.evaluations": "Maximum evaluations must be a whole number from {low} to {high}.",
    "analysis.robust_curve.error.threshold": "Low weight threshold must be a finite number greater than 0 and less "
                                             "than 1.",
    "analysis.robust_curve.error.compare": "Compare ordinary fit must be true or false.",
    "analysis.robust_curve.error.display": "Graph display: choose Curve, Residuals or Weights.",
    "analysis.robust_curve.error.initial_type": "Initial parameters must list parameter names and values; leave it "
                                                "empty to use the catalog values.",
    "analysis.robust_curve.error.initial_missing": "Initial parameters must give every parameter of the model; "
                                                   "missing: {names}.",
    "analysis.robust_curve.error.initial_unknown": "Initial parameters name unknown parameters for this model: "
                                                   "{names}.",
    "analysis.robust_curve.error.initial_number": "Initial parameter {name} must be a finite number.",
    "analysis.robust_curve.error.initial_bounds": "Initial parameter {name} = {value} lies outside its limits "
                                                  "({low} to {high}).",
    "analysis.robust_curve.error.complex": 'Column "{column}" contains complex values.',
    "analysis.robust_curve.error.text": 'Column "{column}" contains non-numeric values (first at source row {row}).',
    "analysis.robust_curve.error.infinite": 'Column "{column}" contains infinite values (first at source row {row}).',
    "analysis.robust_curve.error.no_pairs": "No complete X and Y pairs.",
    "analysis.robust_curve.error.no_pairs_column": 'Column "{column}" has no complete X and Y pairs.',
    "analysis.robust_curve.error.too_many_pairs": "The analysis supports up to {limit} complete pairs; found {count}.",
    "analysis.robust_curve.error.too_many_fits": "The analysis supports up to {limit} fits (Y columns × groups); "
                                                 "found {count}.",
    "analysis.robust_curve.error.too_many_parameters": "{model} has more than {limit} parameters.",
    "analysis.robust_curve.error.too_few": "{series}: {count} complete pairs cannot estimate {parameters} "
                                           "parameters; the model needs more pairs than parameters.",
    "analysis.robust_curve.error.distinct": "{series}: {count} distinct X values cannot estimate {parameters} "
                                            "parameters.",
    "analysis.robust_curve.error.positive": "{model} requires positive X values; {series} has X = {x} at source "
                                            "row {row}.",
    "analysis.robust_curve.error.nonnegative": "{model} requires nonnegative X values; {series} has X = {x} at "
                                               "source row {row}.",
    "analysis.robust_curve.error.catalog_start": "The catalog starting values cannot be calculated from these data "
                                                 "({series}); enter starting values.",
    "analysis.robust_curve.error.undefined_start": "The model is not defined at the starting values for {series} at "
                                                   "X = {x} (source row {row}). Change the starting values.",
    "analysis.robust_curve.error.pilot_converge": "{series}: the ordinary pilot fit did not converge within {limit} "
                                                  "evaluations.",
    "analysis.robust_curve.error.pilot_identifiable": "{series}: the ordinary pilot fit is not identifiable from "
                                                      "these data.",
    "analysis.robust_curve.error.pilot_estimate": "{series}: the ordinary pilot fit could not be estimated "
                                                  "reliably.",
    "analysis.robust_curve.error.pilot_scale": "{series}: the pilot residual scale is not finite.",
    "analysis.robust_curve.error.robust_estimate": "{series}: the robust fit could not be estimated reliably.",
    "analysis.robust_curve.error.converge": "{series}: the optimizer did not converge within {limit} evaluations. "
                                            "Increase Maximum evaluations or change the starting values.",
    "analysis.robust_curve.error.identifiable": "{series}: the model is not identifiable from these data (the "
                                                "parameters cannot be estimated separately). Choose a simpler "
                                                "model.",
    "analysis.robust_curve.error.overflow": "{series}: the loss exceeds the numerical range; check the residual "
                                            "scale and the units.",
    "analysis.robust_curve.error.number": "{field} must be a number.",
    "analysis.robust_curve.error.whole": "{field} must be a whole number.",
    "analysis.robust_curve.error.finite": "{field} must be finite.",
    "analysis.robust_curve.error.range": "{field} exceeds the supported integer range.",
})
_IT.update({
    "analysis.robust_curve.tab.variables": "Variabili", "analysis.robust_curve.tab.loss": "Perdita e scala",
    "analysis.robust_curve.tab.output": "Risultati",
    "analysis.robust_curve.field.X": "X", "analysis.robust_curve.field.Y columns": "Colonne Y",
    "analysis.robust_curve.field.Group": "Gruppo", "analysis.robust_curve.field.Model": "Modello",
    "analysis.robust_curve.field.Loss": "Perdita", "analysis.robust_curve.field.Scale method": "Metodo di scala",
    "analysis.robust_curve.field.Residual scale": "Scala dei residui",
    "analysis.robust_curve.field.Initial parameters": "Parametri iniziali",
    "analysis.robust_curve.field.Maximum evaluations": "Valutazioni massime",
    "analysis.robust_curve.field.Low weight threshold": "Soglia di peso basso",
    "analysis.robust_curve.field.Compare ordinary fit": "Confronta con il fit ordinario",
    "analysis.robust_curve.field.Graph display": "Visualizzazione del grafico",
    "analysis.robust_curve.choice.cauchy": "Cauchy", "analysis.robust_curve.choice.huber": "Huber",
    "analysis.robust_curve.choice.soft_l1": "Soft L1", "analysis.robust_curve.choice.fixed": "Fissa",
    "analysis.robust_curve.choice.pilot_mad": "MAD pilota", "analysis.robust_curve.choice.curve": "Curva",
    "analysis.robust_curve.choice.residuals": "Residui", "analysis.robust_curve.choice.weights": "Pesi",
    "analysis.robust_curve.hint.scale": "Fissa usa una sola scala dei residui per tutto il fit. MAD pilota adatta "
                                        "prima i minimi quadrati ordinari e ricava la scala dalla deviazione "
                                        "assoluta mediana dei suoi residui.",
    "analysis.robust_curve.hint.output": "I pesi di influenza sono diagnostica, non un test di outlier: ogni punto "
                                         "resta nel fit e nel grafico. Un punto con X estremo può comunque "
                                         "trascinare la curva.",
    "analysis.robust_curve.initial.catalog": "Valori iniziali del catalogo",
    "analysis.robust_curve.initial.custom": "Personalizzati: {values}", "analysis.robust_curve.initial.edit": "Modifica…",
    "analysis.robust_curve.editor.title": "Parametri iniziali", "analysis.robust_curve.editor.model": "Modello: {model}",
    "analysis.robust_curve.editor.note": "I valori del catalogo sono proposti dai dati del primo fit. Ripristina "
                                         "torna al catalogo; Applica memorizza tutti i valori mostrati.",
    "analysis.robust_curve.editor.parameter": "Parametro", "analysis.robust_curve.editor.start": "Valore iniziale",
    "analysis.robust_curve.editor.catalog": "Catalogo", "analysis.robust_curve.editor.limits": "Limiti",
    "analysis.robust_curve.editor.reset": "Ripristina", "analysis.robust_curve.editor.apply": "Applica",
    "analysis.robust_curve.editor.cancel": "Annulla",
    "analysis.robust_curve.error.choose": "Scegli una colonna per {field}.",
    "analysis.robust_curve.error.select": "Seleziona almeno una colonna per {field}.",
    "analysis.robust_curve.error.exists": 'Scegli una colonna esistente per {field}: "{column}" non è nel foglio.',
    "analysis.robust_curve.error.unique": "I nomi delle colonne del foglio devono essere univoci.",
    "analysis.robust_curve.error.y_empty": "Scegli almeno una colonna Y.",
    "analysis.robust_curve.error.y_duplicate": 'Le colonne Y devono essere distinte: "{column}" è scelta più volte.',
    "analysis.robust_curve.error.x_in_y": 'X e le colonne Y devono essere diverse: "{column}" è entrambe.',
    "analysis.robust_curve.error.group_role": 'Il gruppo deve essere diverso da X e dalle colonne Y: "{column}" è '
                                              "già usata.",
    "analysis.robust_curve.error.model": "Modello: scegli un modello supportato del catalogo.",
    "analysis.robust_curve.error.loss": "Perdita: scegli Cauchy, Huber o Soft L1.",
    "analysis.robust_curve.error.scale_method": "Metodo di scala: scegli Fissa o MAD pilota.",
    "analysis.robust_curve.error.scale": "La scala dei residui deve essere un numero finito maggiore di 0.",
    "analysis.robust_curve.error.evaluations": "Le valutazioni massime devono essere un numero intero da {low} a "
                                               "{high}.",
    "analysis.robust_curve.error.threshold": "La soglia di peso basso deve essere un numero finito maggiore di 0 e "
                                             "minore di 1.",
    "analysis.robust_curve.error.compare": "Il confronto con il fit ordinario deve essere attivo o disattivo.",
    "analysis.robust_curve.error.display": "Visualizzazione del grafico: scegli Curva, Residui o Pesi.",
    "analysis.robust_curve.error.initial_type": "I parametri iniziali devono elencare nomi e valori dei parametri; "
                                                "lasciali vuoti per usare i valori del catalogo.",
    "analysis.robust_curve.error.initial_missing": "I parametri iniziali devono indicare ogni parametro del "
                                                   "modello; mancano: {names}.",
    "analysis.robust_curve.error.initial_unknown": "I parametri iniziali nominano parametri sconosciuti per questo "
                                                   "modello: {names}.",
    "analysis.robust_curve.error.initial_number": "Il parametro iniziale {name} deve essere un numero finito.",
    "analysis.robust_curve.error.initial_bounds": "Il parametro iniziale {name} = {value} è fuori dai suoi limiti "
                                                  "({low} … {high}).",
    "analysis.robust_curve.error.complex": 'La colonna "{column}" contiene valori complessi.',
    "analysis.robust_curve.error.text": 'La colonna "{column}" contiene valori non numerici (il primo alla riga '
                                        "origine {row}).",
    "analysis.robust_curve.error.infinite": 'La colonna "{column}" contiene valori infiniti (il primo alla riga '
                                            "origine {row}).",
    "analysis.robust_curve.error.no_pairs": "Nessuna coppia X e Y completa.",
    "analysis.robust_curve.error.no_pairs_column": 'La colonna "{column}" non ha coppie X e Y complete.',
    "analysis.robust_curve.error.too_many_pairs": "L’analisi supporta fino a {limit} coppie complete; ne risultano "
                                                  "{count}.",
    "analysis.robust_curve.error.too_many_fits": "L’analisi supporta fino a {limit} fit (colonne Y × gruppi); ne "
                                                 "risultano {count}.",
    "analysis.robust_curve.error.too_many_parameters": "{model} ha più di {limit} parametri.",
    "analysis.robust_curve.error.too_few": "{series}: {count} coppie complete non bastano per stimare {parameters} "
                                           "parametri; servono più coppie che parametri.",
    "analysis.robust_curve.error.distinct": "{series}: {count} valori X distinti non bastano per stimare "
                                            "{parameters} parametri.",
    "analysis.robust_curve.error.positive": "{model} richiede valori X positivi; {series} ha X = {x} alla riga "
                                            "origine {row}.",
    "analysis.robust_curve.error.nonnegative": "{model} richiede valori X non negativi; {series} ha X = {x} alla "
                                               "riga origine {row}.",
    "analysis.robust_curve.error.catalog_start": "I valori iniziali del catalogo non si possono calcolare da questi "
                                                 "dati ({series}); inserisci i valori iniziali.",
    "analysis.robust_curve.error.undefined_start": "Il modello non è definito ai valori iniziali per {series} in "
                                                   "X = {x} (riga origine {row}). Cambia i valori iniziali.",
    "analysis.robust_curve.error.pilot_converge": "{series}: il fit ordinario pilota non converge entro {limit} "
                                                  "valutazioni.",
    "analysis.robust_curve.error.pilot_identifiable": "{series}: il fit ordinario pilota non è identificabile da "
                                                      "questi dati.",
    "analysis.robust_curve.error.pilot_estimate": "{series}: il fit ordinario pilota non si può stimare in modo "
                                                  "affidabile.",
    "analysis.robust_curve.error.pilot_scale": "{series}: la scala dei residui del pilota non è finita.",
    "analysis.robust_curve.error.robust_estimate": "{series}: il fit robusto non si può stimare in modo affidabile.",
    "analysis.robust_curve.error.converge": "{series}: l’ottimizzatore non converge entro {limit} valutazioni. "
                                            "Aumenta le valutazioni massime o cambia i valori iniziali.",
    "analysis.robust_curve.error.identifiable": "{series}: il modello non è identificabile da questi dati (i "
                                                "parametri non si possono stimare separatamente). Scegli un modello "
                                                "più semplice.",
    "analysis.robust_curve.error.overflow": "{series}: la perdita supera l’intervallo numerico; controlla la scala "
                                            "dei residui e le unità.",
    "analysis.robust_curve.error.number": "{field} deve essere un numero.",
    "analysis.robust_curve.error.whole": "{field} deve essere un numero intero.",
    "analysis.robust_curve.error.finite": "{field} deve essere finito.",
    "analysis.robust_curve.error.range": "{field} supera l’intervallo intero supportato.",
})

# Heat map 0.72 colors and legends: editor texts and the engine messages (matched by their English text, see
# translate_message). Recipes keep the English field names, choices and level texts.
_EN.update({
    "graph.inspector.heat_hint": "A heat map is a single color mesh. Its colors, gradient and legend are set in "
                                 "the heat-map settings.",
    "graph.inspector.heat_colors": "Colors and legend…",
    "heat.cat.title": "Category colors", "heat.cat.level": "Category", "heat.cat.color": "Color",
    "heat.cat.edit": "Edit category colors…", "heat.cat.reset": "Use palette colors",
    "heat.cat.note": "Colors follow the category text: upper and lower case and leading zeros are different "
                     "categories. Leave a color blank to use the palette color. Colors of categories that are not "
                     "in the data now are kept for when they return.",
    "heat.cat.empty": "No categories to list.",
    "heat.cat.more": "Only the first {count} categories are listed.",
    "heat.cat.summary": "{custom} of {total} categories have a chosen color.",
    "heat.cat.choose": "Choose the X, Y and value columns to list the categories.",
    "heat.cat.invalid": "{level}: choose a valid color name or hexadecimal color.",
    "heat.note.colors": "Gradients use the color limits above. The palette and its scale apply only to Palette.",
    "heat.note.legend": "Leave the interval blank for automatic ticks. The first tick applies only with an interval.",
    "heat.legend_number.format": "Color legend number format",
    "heat.legend_number.decimals": "Color legend decimals",
    "heat.legend_number.choice.Automatic": "Automatic",
    "heat.legend_number.choice.Fixed": "Fixed",
    "heat.legend_number.choice.Scientific": "Scientific",
    "heat.legend_number.error.decimals": "{field} must be a whole number from 0 to 8.",
    "heat.cell_label.number_format": "Cell label number format",
    "heat.cell_label.decimals": "Cell label decimals",
    "heat.cell_label.font_size": "Cell label font size",
    "heat.cell_label.color_mode": "Cell label color mode",
    "heat.cell_label.color": "Cell label color",
    "heat.cell_label.prefix": "Cell label prefix",
    "heat.cell_label.suffix": "Cell label suffix",
    "heat.cell_label.choice.Automatic": "Automatic",
    "heat.cell_label.choice.Fixed": "Fixed",
    "heat.cell_label.choice.Scientific": "Scientific",
    "heat.cell_label.choice.Auto contrast": "Auto contrast",
    "heat.cell_label.choice.Custom": "Custom",
    "heat.cell_label.error.decimals": "{field} must be a whole number from 0 to 8.",
    "heat.cell_label.error.font_size": "{field} must be blank or a number from 6 to 36.",
    "heat.cell_label.error.affix_text": "{field} must be text.",
    "heat.cell_label.error.affix_length": "{field} must be at most 80 characters.",
    "heat.error.color": "Choose a valid color name or hexadecimal color.",
    "heat.error.level_color": "Choose a valid color for the category {level}.",
    "heat.error.choice": "Choose a valid {field}.",
    "heat.error.finite": "{field} must be a finite number.",
    "heat.error.unit": "{field} must be a number from 0 to 1.",
    "heat.error.flag": "{field} must be on or off.",
    "heat.error.between": "{field} must be between 0 and 1.",
    "heat.error.mapping": "Category colors must be a mapping from each level to a color.",
    "heat.error.count": "Use at most {count} category colors.",
    "heat.error.name": "Each category name must be text of 1 to 1000 characters.",
    "heat.error.positive": "{field} must be greater than zero.",
    "heat.error.start": "{field} must lie between the color limits.",
    "heat.error.ticks": "{field} would draw {count} ticks; use at most {limit}.",
    "heat.error.text": "{field} must be text.",
    "heat.error.limits": "Choose finite color limits with the maximum greater than the minimum.",
    "heat.error.midpoint": "The midpoint must be strictly between the color limits.",
    "heat.error.number": "{field} must be a number.",
    "heat.error.finite_only": "{field} must be finite.",
    "heat.layout.tab": "Layout",
    "heat.layout.row_gap_mode": "Row gap mode",
    "heat.layout.row_gap_size": "Row gap size",
    "heat.layout.row_gaps_after": "Row gaps after",
    "heat.layout.column_gap_mode": "Column gap mode",
    "heat.layout.column_gap_size": "Column gap size",
    "heat.layout.column_gaps_after": "Column gaps after",
    "heat.layout.show_row_labels": "Show row labels",
    "heat.layout.row_label_frequency": "Row label frequency",
    "heat.layout.row_label_every": "Row label every",
    "heat.layout.row_label_side": "Row label side",
    "heat.layout.row_label_font_size": "Row label font size",
    "heat.layout.show_column_labels": "Show column labels",
    "heat.layout.column_label_frequency": "Column label frequency",
    "heat.layout.column_label_every": "Column label every",
    "heat.layout.column_label_rotation": "Column label rotation",
    "heat.layout.column_label_side": "Column label side",
    "heat.layout.column_label_font_size": "Column label font size",
    "heat.layout.choice.None": "None",
    "heat.layout.choice.Every boundary": "Every boundary",
    "heat.layout.choice.Selected boundaries": "Selected boundaries",
    "heat.layout.choice.Automatic": "Automatic",
    "heat.layout.choice.Every Nth": "Every Nth",
    "heat.layout.choice.Legacy": "Legacy",
    "heat.layout.choice.Horizontal": "Horizontal",
    "heat.layout.choice.Diagonal": "Diagonal",
    "heat.layout.choice.Vertical": "Vertical",
    "heat.layout.choice.Left": "Left",
    "heat.layout.choice.Right": "Right",
    "heat.layout.choice.Bottom": "Bottom",
    "heat.layout.choice.Top": "Top",
    "heat.layout.note.gaps": "Gap sizes are in cell units (0 to 2). Positions start at 1 after Transpose and Reverse, separated by commas (for example: 2, 4).",
    "heat.layout.note.labels": "Blank font size keeps the default axis font. Automatic keeps about 25 labels; Every Nth shows every Nth label.",
    "heat.layout.error.gap_size": "{field} must be a number from 0 to 2.",
    "heat.layout.error.min_items": "{field} requires at least 2 items on the axis.",
    "heat.layout.error.boundaries_syntax": "{field} must list whole positions separated by commas.",
    "heat.layout.error.boundaries_duplicate": "{field} cannot repeat the same boundary position.",
    "heat.layout.error.boundaries_range": "{field} must use positions from 1 to {max}.",
    "heat.layout.error.label_every": "{field} must be a whole number from 1 to 10000.",
    "heat.layout.error.font_size": "{field} must be blank or a number from 6 to 36.",
})
_IT.update({
    "graph.inspector.heat_hint": "Una mappa di calore è un’unica griglia di colori. Colori, gradiente e legenda si "
                                 "impostano nelle impostazioni della mappa.",
    "graph.inspector.heat_colors": "Colori e legenda…",
    "heat.cat.title": "Colori delle categorie", "heat.cat.level": "Categoria", "heat.cat.color": "Colore",
    "heat.cat.edit": "Modifica i colori delle categorie…", "heat.cat.reset": "Usa i colori della tavolozza",
    "heat.cat.note": "I colori seguono il testo della categoria: maiuscole, minuscole e zeri iniziali distinguono "
                     "categorie diverse. Lascia vuoto il colore per usare quello della tavolozza. I colori delle "
                     "categorie che ora non sono nei dati restano salvati per quando tornano.",
    "heat.cat.empty": "Nessuna categoria da elencare.",
    "heat.cat.more": "Sono elencate solo le prime {count} categorie.",
    "heat.cat.summary": "{custom} categorie su {total} hanno un colore scelto.",
    "heat.cat.choose": "Scegli le colonne X, Y e dei valori per elencare le categorie.",
    "heat.cat.invalid": "{level}: scegli un nome di colore o un colore esadecimale valido.",
    "heat.note.colors": "I gradienti usano i limiti dei colori qui sopra. La tavolozza e la sua scala valgono solo "
                        "per Tavolozza.",
    "heat.note.legend": "Lascia vuoto l’intervallo per i tick automatici. Il primo tick vale solo con un intervallo.",
    "heat.legend_number.format": "Formato numerico della legenda",
    "heat.legend_number.decimals": "Decimali della legenda",
    "heat.legend_number.choice.Automatic": "Automatico",
    "heat.legend_number.choice.Fixed": "Decimali fissi",
    "heat.legend_number.choice.Scientific": "Scientifico",
    "heat.legend_number.error.decimals": "{field} deve essere un numero intero da 0 a 8.",
    "heat.cell_label.number_format": "Formato numerico etichette",
    "heat.cell_label.decimals": "Decimali etichette",
    "heat.cell_label.font_size": "Dimensione font etichette",
    "heat.cell_label.color_mode": "Modalità colore etichette",
    "heat.cell_label.color": "Colore etichette",
    "heat.cell_label.prefix": "Prefisso etichette",
    "heat.cell_label.suffix": "Suffisso etichette",
    "heat.cell_label.choice.Automatic": "Automatico",
    "heat.cell_label.choice.Fixed": "Decimali fissi",
    "heat.cell_label.choice.Scientific": "Scientifico",
    "heat.cell_label.choice.Auto contrast": "Contrasto automatico",
    "heat.cell_label.choice.Custom": "Personalizzato",
    "heat.cell_label.error.decimals": "{field} deve essere un numero intero da 0 a 8.",
    "heat.cell_label.error.font_size": "{field} deve essere vuoto o un numero da 6 a 36.",
    "heat.cell_label.error.affix_text": "{field} deve essere un testo.",
    "heat.cell_label.error.affix_length": "{field} può contenere al massimo 80 caratteri.",
    "heat.error.color": "Scegli un nome di colore o un colore esadecimale valido.",
    "heat.error.level_color": "Scegli un colore valido per la categoria {level}.",
    "heat.error.choice": "Scegli un valore valido per {field}.",
    "heat.error.finite": "{field} deve essere un numero finito.",
    "heat.error.unit": "{field} deve essere un numero da 0 a 1.",
    "heat.error.flag": "{field} deve essere attivo o disattivo.",
    "heat.error.between": "{field} deve essere compreso tra 0 e 1.",
    "heat.error.mapping": "I colori delle categorie devono associare un colore a ogni livello.",
    "heat.error.count": "Usa al massimo {count} colori di categoria.",
    "heat.error.name": "Il nome di ogni categoria deve essere un testo di 1–1000 caratteri.",
    "heat.error.positive": "{field} deve essere maggiore di zero.",
    "heat.error.start": "{field} deve stare tra i limiti dei colori.",
    "heat.error.ticks": "{field} disegnerebbe {count} tick; usane al massimo {limit}.",
    "heat.error.text": "{field} deve essere un testo.",
    "heat.error.limits": "Scegli limiti dei colori finiti con il massimo maggiore del minimo.",
    "heat.error.midpoint": "Il punto centrale deve stare strettamente tra i limiti dei colori.",
    "heat.error.number": "{field} deve essere un numero.",
    "heat.error.finite_only": "{field} deve essere finito.",
    "heat.layout.tab": "Layout",
    "heat.layout.row_gap_mode": "Modalità separazione righe",
    "heat.layout.row_gap_size": "Ampiezza separazione righe",
    "heat.layout.row_gaps_after": "Separazioni righe dopo",
    "heat.layout.column_gap_mode": "Modalità separazione colonne",
    "heat.layout.column_gap_size": "Ampiezza separazione colonne",
    "heat.layout.column_gaps_after": "Separazioni colonne dopo",
    "heat.layout.show_row_labels": "Mostra etichette righe",
    "heat.layout.row_label_frequency": "Frequenza etichette righe",
    "heat.layout.row_label_every": "Passo etichette righe",
    "heat.layout.row_label_side": "Lato etichette righe",
    "heat.layout.row_label_font_size": "Dimensione font etichette righe",
    "heat.layout.show_column_labels": "Mostra etichette colonne",
    "heat.layout.column_label_frequency": "Frequenza etichette colonne",
    "heat.layout.column_label_every": "Passo etichette colonne",
    "heat.layout.column_label_rotation": "Rotazione etichette colonne",
    "heat.layout.column_label_side": "Lato etichette colonne",
    "heat.layout.column_label_font_size": "Dimensione font etichette colonne",
    "heat.layout.choice.None": "Nessuno",
    "heat.layout.choice.Every boundary": "Ogni separazione",
    "heat.layout.choice.Selected boundaries": "Selezionate",
    "heat.layout.choice.Automatic": "Automatica",
    "heat.layout.choice.Every Nth": "Ogni N",
    "heat.layout.choice.Legacy": "Predefinita (40°)",
    "heat.layout.choice.Horizontal": "Orizzontale",
    "heat.layout.choice.Diagonal": "Diagonale",
    "heat.layout.choice.Vertical": "Verticale",
    "heat.layout.choice.Left": "Sinistra",
    "heat.layout.choice.Right": "Destra",
    "heat.layout.choice.Bottom": "Sotto",
    "heat.layout.choice.Top": "Sopra",
    "heat.layout.note.gaps": "Le ampiezze delle separazioni sono in unità cella (da 0 a 2). Le posizioni partono da 1 dopo Trasponi e Inverti, separate da virgola (esempio: 2, 4).",
    "heat.layout.note.labels": "Lasciando vuota la dimensione del font resta il font predefinito dell’asse. Automatica mostra circa 25 etichette; Ogni N mostra ogni N-esima etichetta.",
    "heat.layout.error.gap_size": "{field} deve essere un numero da 0 a 2.",
    "heat.layout.error.min_items": "{field} richiede almeno 2 elementi sull’asse.",
    "heat.layout.error.boundaries_syntax": "{field} deve elencare posizioni intere separate da virgola.",
    "heat.layout.error.boundaries_duplicate": "{field} non può ripetere la stessa posizione.",
    "heat.layout.error.boundaries_range": "{field} deve usare posizioni da 1 a {max}.",
    "heat.layout.error.label_every": "{field} deve essere un numero intero da 1 a 10000.",
    "heat.layout.error.font_size": "{field} deve essere vuoto o un numero da 6 a 36.",
})

_EN.update({
    "analysis.linear.estimates.forward": "Y confidence interval at X",
    "analysis.linear.estimates.inverse": "X confidence interval at Y",
    "analysis.linear.estimates.x": "X value",
    "analysis.linear.estimates.y": "Y value",
    "analysis.linear.estimates.level": "Confidence level (%)",
    "analysis.linear.estimates.finite": "Enter a finite numeric value for {axis}.",
    "analysis.linear.estimates.range": "The requested estimate or confidence limit exceeds the supported numeric range.",
})
_IT.update({
    "analysis.linear.estimates.forward": "IC della media Y per X",
    "analysis.linear.estimates.inverse": "IC di X per Y",
    "analysis.linear.estimates.x": "Valore X",
    "analysis.linear.estimates.y": "Valore Y",
    "analysis.linear.estimates.level": "Livello di confidenza (%)",
    "analysis.linear.estimates.finite": "Inserisci un valore numerico finito per {axis}.",
    "analysis.linear.estimates.range": "La stima o il limite di confidenza richiesto supera l'intervallo numerico supportato.",
})

# Multiple regression (Linear family): fixed Gaussian observation weights, their dialog fields and their errors.
_MLR_WEIGHT_EN = {
    "analysis.mlr.mode": "Gaussian weighting", "analysis.mlr.exponent": "Weight exponent K",
    "analysis.mlr.sd": "Gaussian SD column", "analysis.mlr.weight": "Gaussian weight column",
    "analysis.mlr.future": "Weighted prediction intervals",
    "analysis.mlr.profile_weight": "Weight",
    "analysis.mlr.profile_weight_error": "The weight needs a finite number greater than 0, in the units of the "
                                         "training weights.",
    "analysis.mlr.choice.unweighted": "Unweighted", "analysis.mlr.choice.sd": "Inverse variance (SD column)",
    "analysis.mlr.choice.weight": "Weight column",
    "analysis.mlr.note.unweighted": "Every row counts equally: ordinary least squares, as before.",
    "analysis.mlr.note.abs_y": "Fixed weights 1/|Y| from the observed response: weighted least squares, no "
                               "iterations. A Y of zero is not allowed.",
    "analysis.mlr.note.y_squared": "Fixed weights 1/Y² from the observed response: weighted least squares, no "
                                   "iterations. A Y of zero is not allowed.",
    "analysis.mlr.note.power": "Fixed weights 1/|Y|^K from the observed response. K = 0 gives equal weights; any other "
                               "K does not allow a Y of zero.",
    "analysis.mlr.note.sd": "Fixed weights 1/SD² from the SD column. Rows without an SD leave the fit; an SD that is "
                            "present must be a finite number above 0.",
    "analysis.mlr.note.weight": "Fixed weights from the column. Rows without a weight leave the fit; a weight that is "
                                "present must be a finite number above 0.",
    "mlr.error.mode": "Choose Unweighted, 1/abs(Y), 1/Y², 1/abs(Y)^K, Inverse variance (SD column) or Weight column.",
    "mlr.error.exponent": "Weight exponent K must be a finite number.",
    "mlr.error.flag": "{name} must be yes or no.",
    "mlr.error.choose": "Choose a column for {field}.",
    "mlr.error.exists": "Choose an existing column for {field}.",
    "mlr.error.distinct": "{field} must be a column distinct from the response and the predictors.",
    "mlr.error.complex": 'Column "{column}" contains complex data.',
    "mlr.error.sd": 'Column "{column}" needs finite SD values greater than 0 (source row {row}: {value}).',
    "mlr.error.weights": 'Column "{column}" needs finite weights greater than 0 (source row {row}: {value}).',
    "mlr.error.zero": "The {choice} weighting cannot be used with a Y value of zero (source row {row}).",
    "mlr.error.range": "The {choice} weights are outside the numeric range.",
    "mlr.error.ratio": "The ratio between the largest and the smallest weight is outside the numeric range: a weight "
                       "would be zero relative to the largest one.",
    "mlr.error.profile_weight": 'Profile "{label}" needs a finite weight greater than 0 in the units of the training '
                                "weights.",
    "mlr.error.profile_range": "A profile weight puts the future observation variance outside the numeric range.",
    "mlr.error.profile_scale": "The raw weight scale of the training data is outside the numeric range, so profile "
                               "weights in raw units cannot be compared with it.",
    "mlr.error.rank": "The model is rank deficient after weighting. Remove redundant predictors or check the weights.",
}
_MLR_WEIGHT_IT = {
    "analysis.mlr.mode": "Pesatura gaussiana", "analysis.mlr.exponent": "Esponente del peso K",
    "analysis.mlr.sd": "Colonna SD gaussiana", "analysis.mlr.weight": "Colonna dei pesi gaussiana",
    "analysis.mlr.future": "Intervalli di predizione pesati",
    "analysis.mlr.profile_weight": "Peso",
    "analysis.mlr.profile_weight_error": "Il peso deve essere un numero finito maggiore di 0, nelle unità dei pesi "
                                         "di stima.",
    "analysis.mlr.choice.unweighted": "Senza pesi", "analysis.mlr.choice.sd": "Varianza inversa (colonna SD)",
    "analysis.mlr.choice.weight": "Colonna dei pesi",
    "analysis.mlr.note.unweighted": "Ogni riga conta allo stesso modo: minimi quadrati ordinari, come prima.",
    "analysis.mlr.note.abs_y": "Pesi fissi 1/|Y| dalla risposta osservata: minimi quadrati pesati, senza "
                               "iterazioni. Non è ammesso Y uguale a zero.",
    "analysis.mlr.note.y_squared": "Pesi fissi 1/Y² dalla risposta osservata: minimi quadrati pesati, senza "
                                   "iterazioni. Non è ammesso Y uguale a zero.",
    "analysis.mlr.note.power": "Pesi fissi 1/|Y|^K dalla risposta osservata. Con K = 0 i pesi sono uguali; con ogni "
                               "altro K non è ammesso Y uguale a zero.",
    "analysis.mlr.note.sd": "Pesi fissi 1/SD² dalla colonna SD. Le righe senza SD escono dal fit; una SD presente deve "
                            "essere un numero finito maggiore di 0.",
    "analysis.mlr.note.weight": "Pesi fissi dalla colonna. Le righe senza peso escono dal fit; un peso presente deve "
                                "essere un numero finito maggiore di 0.",
    "mlr.error.mode": "Scegli Senza pesi, 1/abs(Y), 1/Y², 1/abs(Y)^K, Varianza inversa (colonna SD) o Colonna dei pesi.",
    "mlr.error.exponent": "L'esponente del peso K deve essere un numero finito.",
    "mlr.error.flag": "{name} deve essere sì o no.",
    "mlr.error.choose": "Scegli una colonna per {field}.",
    "mlr.error.exists": "Scegli una colonna esistente per {field}.",
    "mlr.error.distinct": "{field} deve essere una colonna diversa dalla risposta e dai predittori.",
    "mlr.error.complex": 'La colonna "{column}" contiene numeri complessi.',
    "mlr.error.sd": 'La colonna "{column}" richiede valori SD finiti maggiori di 0 (riga sorgente {row}: {value}).',
    "mlr.error.weights": 'La colonna "{column}" richiede pesi finiti maggiori di 0 (riga sorgente {row}: {value}).',
    "mlr.error.zero": "La pesatura {choice} non è utilizzabile con un valore Y uguale a zero (riga sorgente {row}).",
    "mlr.error.range": "I pesi {choice} sono fuori dall'intervallo numerico.",
    "mlr.error.ratio": "Il rapporto fra il peso maggiore e il minore è fuori dall'intervallo numerico: un peso "
                       "sarebbe zero rispetto al maggiore.",
    "mlr.error.profile_weight": 'Il profilo "{label}" richiede un peso finito maggiore di 0 nelle unità dei pesi di '
                                "stima.",
    "mlr.error.profile_range": "Il peso di un profilo porta la varianza della futura osservazione fuori "
                               "dall'intervallo numerico.",
    "mlr.error.profile_scale": "La scala dei pesi grezzi dei dati di stima è fuori dall'intervallo numerico: i pesi "
                               "dei profili in unità grezze non possono essere confrontati con essa.",
    "mlr.error.rank": "Il modello è a rango deficiente dopo la pesatura. Rimuovi i predittori ridondanti o controlla "
                      "i pesi.",
}
_EN.update(_MLR_WEIGHT_EN)
_IT.update(_MLR_WEIGHT_IT)

# Inverse intervals on a nonlinear standard curve. Error texts match the engine strings.
_EN.update({
    "calib.inverse_nonlinear.note": (
        "Pointwise asymptotic approximation from the fitted curve and its covariance. "
        "Not a likelihood profile, a simultaneous band or a bootstrap, and not an extrapolation."),
    "calib.inverse_nonlinear.association": (
        "Inverse intervals are not available for One-phase association. Choose None."),
    "calib.inverse_nonlinear.queries": "Inverse intervals accept at most 256 unknown responses.",
    "calib.inverse_nonlinear.level": "Choose a confidence level strictly between 0 and 100.",
    "calib.inverse_nonlinear.uncertainty": "Select None, Mean response or Prediction.",
    "calib.inverse_nonlinear.unknown": "Choose a column of unknown response values.",
    "calib.inverse_nonlinear.replicates": (
        "Choose a column of replicate counts, or leave the field empty for k = 1."),
    "calib.inverse_nonlinear.replicates_distinct": (
        "Choose a replicate count column distinct from X, Y and the unknown values."),
    "calib.inverse_nonlinear.replicates_row": (
        'Column "{column}" needs a whole number of replicates between 1 and {maximum} on row {row}.'),
    "calib.inverse_nonlinear.field.uncertainty": "Uncertainty",
    "calib.inverse_nonlinear.field.level": "Confidence level (%)",
    "calib.inverse_nonlinear.field.replicates": "Replicate count column",
    "calib.inverse_nonlinear.field.responses": "Unknown responses",
    "calib.inverse_nonlinear.field.model": "Model",
    "calib.inverse_nonlinear.field.model_log10": "Model (log10 X)",
    "calib.inverse_nonlinear.field.model_concentration": "Model (concentration X)",
    "calib.inverse_nonlinear.field.curve": "Curve",
    "calib.inverse_nonlinear.field.direction": "Direction",
})
_IT.update({
    "calib.inverse_nonlinear.note": (
        "Approssimazione asintotica puntuale dalla curva stimata e dalla sua covarianza. "
        "Non è un profilo di verosimiglianza, una banda simultanea o un bootstrap, e non è un'estrapolazione."),
    "calib.inverse_nonlinear.association": (
        "Gli intervalli inversi non sono disponibili per One-phase association. Scegli None."),
    "calib.inverse_nonlinear.queries": "Gli intervalli inversi accettano al massimo 256 risposte incognite.",
    "calib.inverse_nonlinear.level": "Scegli un livello di confidenza strettamente compreso tra 0 e 100.",
    "calib.inverse_nonlinear.uncertainty": "Scegli None, Mean response o Prediction.",
    "calib.inverse_nonlinear.unknown": "Scegli una colonna di risposte incognite.",
    "calib.inverse_nonlinear.replicates": (
        "Scegli una colonna con il numero di repliche, oppure lascia il campo vuoto per k = 1."),
    "calib.inverse_nonlinear.replicates_distinct": (
        "Scegli una colonna del numero di repliche diversa da X, Y e dai valori incogniti."),
    "calib.inverse_nonlinear.replicates_row": (
        'La colonna "{column}" richiede un numero intero di repliche tra 1 e {maximum} alla riga {row}.'),
    "calib.inverse_nonlinear.field.uncertainty": "Incertezza",
    "calib.inverse_nonlinear.field.level": "Livello di confidenza (%)",
    "calib.inverse_nonlinear.field.replicates": "Colonna del numero di repliche",
    "calib.inverse_nonlinear.field.responses": "Risposte incognite",
    "calib.inverse_nonlinear.field.model": "Modello",
    "calib.inverse_nonlinear.field.model_log10": "Modello (log10 X)",
    "calib.inverse_nonlinear.field.model_concentration": "Modello (concentrazione X)",
    "calib.inverse_nonlinear.field.curve": "Curva",
    "calib.inverse_nonlinear.field.direction": "Direzione",
})

CATALOGS = {"en": _EN, "it": _IT}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_active = DEFAULT_LANGUAGE


def canonical(code):
    """Return a supported language code, or English for anything unknown."""
    return code if isinstance(code, str) and code in CATALOGS else DEFAULT_LANGUAGE


def placeholders(text):
    return set(_PLACEHOLDER.findall(text))


def translate(locale, key, **values):
    """Look up key in locale, falling back to English and then to the key itself.

    Named placeholders are replaced in a single pass, so braces or accents inside a value
    (a project called "Misurazioni {A}") are inserted literally and never formatted again.
    """
    catalog = CATALOGS[canonical(locale)]
    template = catalog.get(key, _EN.get(key, key))
    if not values:
        return template
    return _PLACEHOLDER.sub(lambda match: str(values[match.group(1)]) if match.group(1) in values
                            else match.group(0), template)


def set_language(code):
    global _active
    _active = canonical(code)
    return _active


def active_language():
    return _active


def tr(key, **values):
    """Translate for the language chosen at startup."""
    return translate(_active, key, **values)


_MESSAGE_PATTERNS = {}


def _message_patterns(prefix):
    if prefix not in _MESSAGE_PATTERNS:
        patterns = []
        for key, text in _EN.items():
            if key.startswith(prefix):
                # split() alternates literal text and placeholder names.
                parts = _PLACEHOLDER.split(text)
                regex = "".join(re.escape(part) if index % 2 == 0 else f"(?P<{part}>.+?)"
                                for index, part in enumerate(parts))
                patterns.append((key, re.compile(regex + r"\Z", re.DOTALL)))
        _MESSAGE_PATTERNS[prefix] = patterns
    return _MESSAGE_PATTERNS[prefix]


def translate_message(text, prefix="graph.error.", convert=None):
    """Show an English message raised by an engine module in the active language.

    Engine modules keep raising English text. A message that matches a catalog entry under ``prefix``
    is translated with its placeholder values copied literally; any other message is returned unchanged.
    ``convert`` maps a placeholder name to a function applied to that value (for field names that are
    fixed identifiers, never for worksheet text).
    """
    text = str(text)
    if _active == DEFAULT_LANGUAGE:
        return text
    for key, pattern in _message_patterns(prefix):
        match = pattern.match(text)
        if match:
            values = match.groupdict()
            for name, function in (convert or {}).items():
                if name in values:
                    values[name] = function(values[name])
            return tr(key, **values)
    return text


# Existing English labels stay the dispatch keys of menus and ribbon; this maps them to catalog keys.
_UI_PREFIXES = ("menu.", "command.", "ribbon.", "bar.", "nav.")
KEY_BY_LABEL = {}
for _key, _text in _EN.items():
    if _key.startswith(_UI_PREFIXES):
        KEY_BY_LABEL.setdefault(_text, _key)


def ui(label):
    """Display text for an English interface label; unknown labels are shown unchanged."""
    key = KEY_BY_LABEL.get(label)
    return tr(key) if key else label


def config_dir(environ=None, platform=None):
    # Keep legacy preference locations when the product is renamed to Trama.
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        base = environ.get("APPDATA")
        return Path(base) / "TramaStat" if base else Path.home() / "AppData" / "Roaming" / "TramaStat"
    base = environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "tramastat"


def config_path(environ=None, platform=None):
    return config_dir(environ, platform) / PREFERENCES_FILE


def load_language(path):
    """Read the preferred language; anything missing, unreadable or unknown means English."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return DEFAULT_LANGUAGE
    if not isinstance(data, dict):
        return DEFAULT_LANGUAGE
    return canonical(data.get("language"))


def save_language(path, locale):
    """Write the preference atomically, keeping other settings already in the file."""
    if not isinstance(locale, str) or locale not in CATALOGS:
        raise ValueError(f"Unsupported language: {locale!r}")
    path = Path(path)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        current = {}
    data = current if isinstance(current, dict) else {}
    data["language"] = locale
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".preferences-", suffix=".tmp", dir=path.parent)
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
    return path


# Multifactor ANOVA residual diagnostics. Canonical recipe values stay English.
_ANOVA_DIAG_EN = {
    "anova.diag.tab": "Diagnostics",
    "anova.diag.field.diagnostics": "ANOVA residual diagnostics",
    "anova.diag.field.assumptions": "ANOVA assumption tests",
    "anova.diag.field.alpha": "ANOVA diagnostic alpha",
    "anova.diag.field.graph": "ANOVA diagnostic graph",
    "anova.diag.field.qq_line": "ANOVA Q–Q reference line",
    "anova.diag.graph.none": "None",
    "anova.diag.graph.residuals": "Residuals vs fitted",
    "anova.diag.graph.homo": "Homoscedasticity",
    "anova.diag.graph.qq": "Normal Q–Q",
    "anova.diag.error.yes_no": "Choose yes or no.",
    "anova.diag.error.graph": "Choose a diagnostic graph.",
    "anova.diag.error.graph_requires": "Turn on ANOVA residual diagnostics before choosing a diagnostic graph.",
    "anova.diag.error.alpha_number": "Alpha must be a number between 0 and 1.",
    "anova.diag.error.alpha_range": "Alpha must be a finite number greater than 0 and less than 1.",
    "anova.diag.error.budget": "A diagnostic graph accepts at most 60,000 points.",
}
_ANOVA_DIAG_IT = {
    "anova.diag.tab": "Diagnostica",
    "anova.diag.field.diagnostics": "Diagnostica dei residui ANOVA",
    "anova.diag.field.assumptions": "Test delle assunzioni ANOVA",
    "anova.diag.field.alpha": "Alfa diagnostico ANOVA",
    "anova.diag.field.graph": "Grafico diagnostico ANOVA",
    "anova.diag.field.qq_line": "Retta di riferimento Q–Q ANOVA",
    "anova.diag.graph.none": "Nessuno",
    "anova.diag.graph.residuals": "Residui contro valori stimati",
    "anova.diag.graph.homo": "Omoschedasticità",
    "anova.diag.graph.qq": "Q–Q normale",
    "anova.diag.error.yes_no": "Scegli sì o no.",
    "anova.diag.error.graph": "Scegli un grafico diagnostico.",
    "anova.diag.error.graph_requires": "Attiva la diagnostica dei residui ANOVA prima di scegliere un grafico diagnostico.",
    "anova.diag.error.alpha_number": "Alfa deve essere un numero compreso tra 0 e 1.",
    "anova.diag.error.alpha_range": "Alfa deve essere un numero finito maggiore di 0 e minore di 1.",
    "anova.diag.error.budget": "Un grafico diagnostico accetta al massimo 60,000 punti.",
}
_EN.update(_ANOVA_DIAG_EN)
_IT.update(_ANOVA_DIAG_IT)

# One-way variance homogeneity. Saved option keys stay the English names.
_VARIANCE_ASSUMPTIONS_EN = {
    "variance.assumptions.tab": "Diagnostics/Assumptions",
    "variance.assumptions.brown": "Brown–Forsythe variance test",
    "variance.assumptions.bartlett": "Bartlett variance test",
    "variance.assumptions.alpha": "Variance test alpha",
    "variance.assumptions.note": "Brown–Forsythe here is Levene’s test centered on each group median. "
                                 "It checks homogeneity of variance. It is not the Brown–Forsythe F* test of means. "
                                 "The result does not change Method to Welch. Bartlett’s test is sensitive to non-normal data.",
    "variance.assumptions.error.bool": "Choose yes or no.",
    "variance.assumptions.error.alpha_number": "Alpha must be a number between 0 and 1.",
    "variance.assumptions.error.alpha_range": "Alpha must be a finite number greater than 0 and less than 1.",
    "variance.assumptions.reason.few": "Group {groups} has fewer than 2 complete observations.",
    "variance.assumptions.reason.few_many": "Groups {groups} have fewer than 2 complete observations.",
    "variance.assumptions.reason.zero": "Group {groups} has zero variance.",
    "variance.assumptions.reason.zero_many": "Groups {groups} have zero variance.",
    "variance.assumptions.reason.constant": "Brown–Forsythe is undefined because the absolute deviations are constant within every group.",
}
_VARIANCE_ASSUMPTIONS_IT = {
    "variance.assumptions.tab": "Diagnostica/Assunzioni",
    "variance.assumptions.brown": "Test di Brown–Forsythe sulle varianze",
    "variance.assumptions.bartlett": "Test di Bartlett sulle varianze",
    "variance.assumptions.alpha": "Alfa del test delle varianze",
    "variance.assumptions.note": "Brown–Forsythe qui è il test di Levene centrato sulla mediana di ogni gruppo. "
                                 "Controlla l’omogeneità delle varianze. Non è il test F* di Brown–Forsythe sulle medie. "
                                 "Il risultato non cambia il metodo in Welch. Il test di Bartlett è sensibile a dati non normali.",
    "variance.assumptions.error.bool": "Scegli sì o no.",
    "variance.assumptions.error.alpha_number": "Alfa deve essere un numero compreso tra 0 e 1.",
    "variance.assumptions.error.alpha_range": "Alfa deve essere un numero finito maggiore di 0 e minore di 1.",
    "variance.assumptions.reason.few": "Il gruppo {groups} ha meno di 2 osservazioni complete.",
    "variance.assumptions.reason.few_many": "I gruppi {groups} hanno meno di 2 osservazioni complete.",
    "variance.assumptions.reason.zero": "Il gruppo {groups} ha varianza zero.",
    "variance.assumptions.reason.zero_many": "I gruppi {groups} hanno varianza zero.",
    "variance.assumptions.reason.constant": "Brown–Forsythe non è definito perché le deviazioni assolute sono costanti dentro ogni gruppo.",
}
_EN.update(_VARIANCE_ASSUMPTIONS_EN)
_IT.update(_VARIANCE_ASSUMPTIONS_IT)

# Normalize to references. Recipes keep the English field names; these strings are the engine messages.
_REFERENCE_EN = {
    "reference.field.zero_rows": "Zero rows, numbered from 1",
    "reference.field.one_rows": "One rows, numbered from 1",
    "reference.note.rows": "Row numbers start at 1 and follow the table from top to bottom. Example: 1,3-5,8.",
    "reference.note.row_means": "Each series is the row mean of its replicates. One pair of references defines that series, and the result is a single column.",
    "reference.note.each": "The zero and one references come from the row means and are applied to every replicate.",
    "reference.note.uncertainty": "Zero and one references are fixed observed values. Their uncertainty is not propagated into the normalized results.",
    "reference.error.choice": "Choose a {field} option.",
    "reference.error.yes_no": "{field} must be yes or no.",
    "reference.error.number": "{field} must be a number.",
    "reference.error.finite": "{field} must be finite.",
    "reference.error.column": "Choose a column for {field}.",
    "reference.error.missing_column": 'Column "{name}" is not in the table.',
    "reference.error.complex": 'Column "{name}" contains complex data.',
    "reference.error.text": 'Column "{name}" contains text or infinite values.',
    "reference.error.precision": 'Column "{name}" contains integers outside the supported precision.',
    "reference.error.used": '"{name}" is already used as {role}.',
    "reference.error.size": "The table exceeds the size limit.",
    "reference.error.series": "Select at most 24 series.",
    "reference.error.rows_empty": "Enter at least one row, numbered from 1.",
    "reference.error.rows_syntax": "Use whole row numbers and increasing ranges, such as 1,3-5.",
    "reference.error.rows_range": "Row numbers must run from 1 through the last row of the table.",
    "reference.error.rows_cap": "Select at most 100000 rows.",
    "reference.error.rows_values": "The selected rows have no values.",
    "reference.error.columns": "Choose columns with at least one value.",
    "reference.error.equal": "The zero and one references are equal.",
    "reference.error.reversed": "The one reference is below the zero reference. Allow reversed references to keep this order.",
    "reference.error.blank": "Blank reference values would remove every value that defines a sum or a mean.",
    "reference.error.range": "A normalized value is outside the numeric range.",
    "reference.error.sign": "Error values must be zero or greater.",
    "reference.error.lower": "The lower limit must be at or below the mean.",
    "reference.error.upper": "The upper limit must be at or above the mean.",
    "reference.error.n": "N must be a whole number of at least 1.",
    "reference.error.select": "Select at least one column for {field}.",
    "reference.error.anchor_range": "{field} is outside the supported numeric range.",
    "reference.stale_result": "Last successful result: the current data could not be recalculated. Recalculate successfully before exporting or using these results as data. {error}",
    "reference.stale_export": "Recalculate all layout panels successfully before exporting; a panel retains an earlier result.",
}
_REFERENCE_IT = {
    "reference.field.zero_rows": "Righe dello zero, numerate da 1",
    "reference.field.one_rows": "Righe dell’uno, numerate da 1",
    "reference.note.rows": "I numeri di riga partono da 1 e seguono la tabella dall’alto verso il basso. Esempio: 1,3-5,8.",
    "reference.note.row_means": "Ogni serie è la media di riga delle sue repliche. Una coppia di riferimenti definisce quella serie e il risultato è una sola colonna.",
    "reference.note.each": "I riferimenti zero e uno sono quelli delle medie di riga e si applicano a ogni replica.",
    "reference.note.uncertainty": "I riferimenti zero e uno sono valori osservati fissi. La loro incertezza non è propagata nei risultati normalizzati.",
    "reference.error.choice": "Scegli un’opzione per {field}.",
    "reference.error.yes_no": "{field} deve essere sì o no.",
    "reference.error.number": "{field} deve essere un numero.",
    "reference.error.finite": "{field} deve essere un numero finito.",
    "reference.error.column": "Scegli una colonna per {field}.",
    "reference.error.missing_column": 'La colonna "{name}" non è nella tabella.',
    "reference.error.complex": 'La colonna "{name}" contiene dati complessi.',
    "reference.error.text": 'La colonna "{name}" contiene testo o valori infiniti.',
    "reference.error.precision": 'La colonna "{name}" contiene interi fuori dalla precisione supportata.',
    "reference.error.used": '"{name}" è già usato come {role}.',
    "reference.error.size": "La tabella supera il limite di dimensione.",
    "reference.error.series": "Seleziona al massimo 24 serie.",
    "reference.error.rows_empty": "Indica almeno una riga, con numerazione da 1.",
    "reference.error.rows_syntax": "Usa numeri di riga interi e intervalli crescenti, per esempio 1,3-5.",
    "reference.error.rows_range": "I numeri di riga devono andare da 1 fino all’ultima riga della tabella.",
    "reference.error.rows_cap": "Seleziona al massimo 100000 righe.",
    "reference.error.rows_values": "Le righe scelte non hanno valori.",
    "reference.error.columns": "Scegli colonne con almeno un valore.",
    "reference.error.equal": "I riferimenti zero e uno sono uguali.",
    "reference.error.reversed": "Il riferimento uno è sotto il riferimento zero. Consenti riferimenti invertiti per mantenere questo ordine.",
    "reference.error.blank": "Nascondere i valori di riferimento toglierebbe tutti i valori che definiscono una somma o una media.",
    "reference.error.range": "Un valore normalizzato è fuori dall’intervallo numerico.",
    "reference.error.sign": "I valori di errore devono essere zero o maggiori.",
    "reference.error.lower": "Il limite inferiore deve essere minore o uguale alla media.",
    "reference.error.upper": "Il limite superiore deve essere maggiore o uguale alla media.",
    "reference.error.n": "N deve essere un numero intero di almeno 1.",
    "reference.error.select": "Seleziona almeno una colonna per {field}.",
    "reference.error.anchor_range": "{field} supera l’intervallo numerico supportato.",
    "reference.stale_result": "Ultimo risultato riuscito: non è stato possibile ricalcolare i dati attuali. Completa il ricalcolo prima di esportare o usare questi risultati come dati. {error}",
    "reference.stale_export": "Completa il ricalcolo di tutti i pannelli prima di esportare: un pannello conserva un risultato precedente.",
}
_EN.update(_REFERENCE_EN)
_IT.update(_REFERENCE_IT)

# Detailed correlation, control correlations and independent Pearson comparisons.
# Result sheets keep these English terms; the dialog translates notes and errors.
_CORR_EN = {
    "corr.details.note.single": "Confidence intervals are always two-sided at the chosen level, including when the test is one-sided. Extended exact Spearman supports up to 17 complete pairs within resource limits. Saved recipes keep their selected budget.",
    "corr.details.note.control": "Intervals are pointwise, not simultaneous, even when p values are adjusted. A response that is constant or too short stays in the table and does not remove the others.",
    "corr.details.note.independent": "The groups must be experimentally independent; Trama does not check that. The comparison interval is a Fisher z difference, not an interval for the difference of the coefficients. The graph shows each coefficient on the scale from −1 to 1.",
    "corr.details.error.storage": "The exact dense storage budget is exceeded. Choose Automatic or a smaller analysis.",
    "corr.details.error.family": "The exact family work budget is exceeded. Choose Automatic or a smaller analysis.",
    "corr.details.error.choice": "Choose a valid {field}.",
    "corr.details.error.level": "Confidence level (%) must be a finite number strictly between 0 and 100.",
    "corr.details.error.column": "Choose a column for {field}.",
    "corr.details.error.missing_column": 'Column "{name}" is not in the table.',
    "corr.details.error.text": 'Column "{name}" contains text or infinite values.',
    "corr.details.error.complex": 'Column "{name}" contains complex data.',
    "corr.details.error.precision": 'Column "{name}" contains integers outside the supported precision.',
    "corr.details.error.distinct": "Select different columns for X and Y.",
    "corr.details.error.pairs": "At least three complete pairs are required; {n} were found.",
    "corr.details.error.constant_x": "X has no variation in the complete pairs.",
    "corr.details.error.constant_y": "Y has no variation in the complete pairs.",
    "corr.details.error.exact": "Exact Spearman p values support at most {limit} complete pairs; {n} were found.",
    "corr.details.error.variables": "Choose 1 to 24 distinct response columns, all different from X.",
    "corr.details.error.none": "No selected response has at least three complete pairs and variation in both variables.",
    "corr.details.error.flag": "{field} must be yes or no.",
    "corr.details.error.group_role": "Choose a grouping column that is not X or Y.",
    "corr.details.error.groups": "Exactly two non-missing groups are required; {n} were found.",
    "corr.details.error.group_pairs": "Group {name} needs at least four complete pairs; {n} were found.",
    "corr.details.error.group_constant": "Group {name} has no variation in X or Y.",
}
_CORR_IT = {
    "corr.details.note.single": "Gli intervalli di confidenza sono sempre bilaterali al livello scelto, anche se il test è unilaterale. Spearman esatto esteso accetta fino a 17 coppie complete entro i limiti di risorse. Le ricette salvate mantengono il limite scelto.",
    "corr.details.note.control": "Gli intervalli sono puntuali, non simultanei, anche quando i valori p sono corretti. Una risposta costante o troppo corta resta in tabella e non elimina le altre.",
    "corr.details.note.independent": "I gruppi devono essere indipendenti sul piano sperimentale; Trama non lo verifica. L’intervallo del confronto è una differenza di z di Fisher, non un intervallo per la differenza dei coefficienti. Il grafico mostra ogni coefficiente sulla scala da −1 a 1.",
    "corr.details.error.storage": "Il limite di memoria per il calcolo esatto è superato. Scegli Automatico o un’analisi più piccola.",
    "corr.details.error.family": "Il limite di lavoro della famiglia esatta è superato. Scegli Automatico o un’analisi più piccola.",
    "corr.details.error.choice": "Scegli un valore valido per {field}.",
    "corr.details.error.level": "Il livello di confidenza (%) deve essere un numero finito strettamente compreso tra 0 e 100.",
    "corr.details.error.column": "Scegli una colonna per {field}.",
    "corr.details.error.missing_column": 'La colonna "{name}" non è nella tabella.',
    "corr.details.error.text": 'La colonna "{name}" contiene testo o valori infiniti.',
    "corr.details.error.complex": 'La colonna "{name}" contiene dati complessi.',
    "corr.details.error.precision": 'La colonna "{name}" contiene interi fuori dalla precisione supportata.',
    "corr.details.error.distinct": "Seleziona colonne diverse per X e Y.",
    "corr.details.error.pairs": "Servono almeno tre coppie complete; ne risultano {n}.",
    "corr.details.error.constant_x": "X non varia nelle coppie complete.",
    "corr.details.error.constant_y": "Y non varia nelle coppie complete.",
    "corr.details.error.exact": "I valori p esatti di Spearman accettano al massimo {limit} coppie complete; ne risultano {n}.",
    "corr.details.error.variables": "Scegli da 1 a 24 colonne di risposta distinte, tutte diverse da X.",
    "corr.details.error.none": "Nessuna risposta selezionata ha almeno tre coppie complete e variazione in entrambe le variabili.",
    "corr.details.error.flag": "{field} deve essere sì o no.",
    "corr.details.error.group_role": "Scegli una colonna di gruppo che non sia X né Y.",
    "corr.details.error.groups": "Servono esattamente due gruppi non mancanti; ne risultano {n}.",
    "corr.details.error.group_pairs": "Il gruppo {name} richiede almeno quattro coppie complete; ne risultano {n}.",
    "corr.details.error.group_constant": "Il gruppo {name} non ha variazione in X o in Y.",
}
_CORR_EN.update({
    "corr.details.error.storage": "The exact dense storage budget is exceeded. Choose Automatic or a smaller analysis.",
    "corr.details.error.work": "The exact family work budget is exceeded. Choose Automatic or a smaller analysis.",
    "corr.details.error.extended_n": "n = {n} exceeds the exact budget of 17 pairs. Choose Automatic or a smaller analysis.",
})
_CORR_IT.update({
    "corr.details.error.storage": "Le risorse di memoria previste per il calcolo esatto sono insufficienti. Scegli Automatico o riduci l’analisi.",
    "corr.details.error.work": "Il limite di lavoro per i confronti esatti è superato. Scegli Automatico o riduci l’analisi.",
    "corr.details.error.extended_n": "Le {n} coppie superano il limite di 17 per il calcolo esatto. Scegli Automatico o riduci l’analisi.",
})
_EN.update(_CORR_EN)
_IT.update(_CORR_IT)

_EN["normality.lognormal.note"] = "Lognormal tests require positive observations and test their logarithms. Relative weights compare only the normal and lognormal fits; they are not p values or probabilities that a model is true."
_IT["normality.lognormal.note"] = "I test lognormali richiedono osservazioni positive e ne analizzano i logaritmi. I pesi relativi confrontano solo i due modelli; non sono valori p né probabilità che un modello sia vero."

# Lognormal one-way ANOVA. Recipes keep the English field names and choice values.
_EN.update({
    "anova.lognormal.field.distribution": "Distribution",
    "anova.lognormal.field.direction": "Ratio direction",
    "anova.lognormal.choice.normal": "Normal",
    "anova.lognormal.choice.lognormal": "Lognormal",
    "anova.lognormal.choice.first_second": "First / Second",
    "anova.lognormal.choice.second_first": "Second / First",
    "anova.lognormal.note": "Lognormal fits one common offset to the natural logarithms of the observations that are actually used. "
                            "Geometric means and ratios are on the original scale. A linear trend is not available for Lognormal.",
    "anova.lognormal.error.distribution": "Choose Normal or Lognormal.",
    "anova.lognormal.error.repeated": "Repeated measures ANOVA does not support a lognormal distribution.",
    "anova.lognormal.error.posthoc": "Choose a post-hoc test offered for one-way ANOVA.",
    "anova.lognormal.error.direction": "Choose First / Second or Second / First.",
    "anova.lognormal.error.trend": "A lognormal linear trend is not available. Turn Linear trend off or choose Normal.",
    "anova.lognormal.error.positive": "Used observations in {response} must be finite and strictly positive.",
    "anova.lognormal.error.level": "Confidence level (%) must be finite and strictly between 0 and 100.",
})
_IT.update({
    "anova.lognormal.field.distribution": "Distribuzione",
    "anova.lognormal.field.direction": "Direzione del rapporto",
    "anova.lognormal.choice.normal": "Normale",
    "anova.lognormal.choice.lognormal": "Lognormale",
    "anova.lognormal.choice.first_second": "Primo / Secondo",
    "anova.lognormal.choice.second_first": "Secondo / Primo",
    "anova.lognormal.note": "Lognormale applica un unico offset ai logaritmi naturali delle osservazioni effettivamente usate. "
                            "Medie geometriche e rapporti restano sulla scala originale. Il trend lineare non è disponibile per Lognormale.",
    "anova.lognormal.error.distribution": "Scegli Normale o Lognormale.",
    "anova.lognormal.error.repeated": "L’ANOVA per misure ripetute non supporta una distribuzione lognormale.",
    "anova.lognormal.error.posthoc": "Scegli un test post-hoc previsto per l’ANOVA a una via.",
    "anova.lognormal.error.direction": "Scegli Primo / Secondo o Secondo / Primo.",
    "anova.lognormal.error.trend": "Il trend lineare lognormale non è disponibile. Disattiva Trend lineare oppure scegli Normale.",
    "anova.lognormal.error.positive": "Le osservazioni usate in {response} devono essere finite e strettamente positive.",
    "anova.lognormal.error.level": "Il livello di confidenza (%) deve essere un numero finito strettamente compreso tra 0 e 100.",
})

# Common dialog captions and analysis selectors are translated only at explicit
# rendering boundaries. No widget hooks touch user titles, columns or data.
from .interface_catalog import CAPTIONS as _INTERFACE_CAPTIONS, MESSAGES as _INTERFACE_MESSAGES

for _key, (_english, _italian) in _INTERFACE_MESSAGES.items():
    _EN[_key], _IT[_key] = _english, _italian

for _english, _italian in _INTERFACE_CAPTIONS.items():
    _key = "interface." + _english
    _EN[_key], _IT[_key] = _english, _italian
    KEY_BY_LABEL.setdefault(_english, _key)

# Reuse the established terminology for specialist fields and fixed choices.
# These labels are only requested by UI-owned controls, never inferred from data.
for _key, _english in _EN.items():
    if ".error." not in _key and not placeholders(_english):
        KEY_BY_LABEL.setdefault(_english, _key)
# The one-way field is new. English on screen must stay exactly this string.
KEY_BY_LABEL.setdefault("Ratio direction", "anova.lognormal.field.direction")


def fixed_choice_keys(values):
    """Catalog keys for a control's fixed canonical choices; unknown values stay literal.

    Call only for application-defined choices, never column/series/group selectors.
    ChoiceBinding keeps these English values in recipes and variable traces.
    """
    return {value: KEY_BY_LABEL[value] for value in values if value in KEY_BY_LABEL}

# Interface themes are local preferences, never translated recipe values.
_EN.update({
    "theme.settings": "Settings", "theme.title": "Theme", "theme.command": "Theme…",
    "theme.standard": "Standard theme", "theme.modern": "Modern theme",
    "theme.standard.description": "Compact ribbon and the familiar Trama interface.",
    "theme.modern.description": "A clean command bar, brighter panels and softly coloured table headings.",
    "theme.note": "The theme applies at the next start. Your open projects stay unchanged.",
    "theme.saved": "Theme saved. It applies at the next start.", "theme.more": "More",
})
_IT.update({
    "theme.settings": "Impostazioni", "theme.title": "Tema", "theme.command": "Tema…",
    "theme.standard": "Tema standard", "theme.modern": "Tema Moderno",
    "theme.standard.description": "Barra compatta e interfaccia abituale di Trama.",
    "theme.modern.description": "Comandi più puliti, pannelli chiari e intestazioni dai colori delicati.",
    "theme.note": "Il tema si applica al prossimo avvio. I progetti aperti rimangono invariati.",
    "theme.saved": "Tema salvato. Si applicherà al prossimo avvio.", "theme.more": "Altro",
})

_EN["theme.project"] = "PROJECT"
_IT["theme.project"] = "PROGETTO"

_EN.update({
 "modern.preview":"Graph preview", "modern.format":"Format", "modern.open_graph":"Open graph",
 "modern.table":"Table", "modern.table_type":"Type", "modern.table_size":"{rows} rows · {columns} columns",
 "modern.no_graph":"Create a linked graph to preview it alongside your data.",
 "modern.create_graph":"Create graph…", "modern.calculating":"Calculation in progress…",
 "modern.not_calculated":"Calculate the linked analysis to display its graph.", "modern.calculate":"Calculate",
 "modern.preview_unavailable":"Open the graph sheet to view this figure.",
 "modern.preview_failed":"The graph preview is unavailable: {error}",
})
_IT.update({
 "modern.preview":"Anteprima del grafico", "modern.format":"Formato", "modern.open_graph":"Apri grafico",
 "modern.table":"Tabella", "modern.table_type":"Tipo", "modern.table_size":"{rows} righe · {columns} colonne",
 "modern.no_graph":"Crea un grafico collegato per visualizzarlo accanto ai dati.",
 "modern.create_graph":"Crea grafico…", "modern.calculating":"Calcolo in corso…",
 "modern.not_calculated":"Calcola l’analisi collegata per visualizzare il grafico.", "modern.calculate":"Calcola",
 "modern.preview_unavailable":"Apri il foglio del grafico per visualizzare questa figura.",
 "modern.preview_failed":"Anteprima del grafico non disponibile: {error}",
})

# Parameter inference is distinct from curve bands; recipe values stay canonical.
_EN.update({
    "custom.profile.hint": "Profile intervals refit the other free coefficients while respecting fixed values and limits. Supplied relative SDs stay fixed. You can cancel; unavailable endpoints carry a reason.",
    "custom.field.Parameter intervals": "Parameter intervals",
    "custom.error.profile_parameters": "Profile intervals support at most {count} free parameters per fit.",
    "custom.error.profile_points": "Profile intervals support at most {count} complete observations per fit.",
    "parameter_ci.tab": "Confidence intervals",
    "parameter_ci.method": "Parameter intervals",
    "parameter_ci.level": "Parameter confidence level (%)",
    "parameter_ci.wald": "Symmetric (Wald)",
    "parameter_ci.profile": "Profile likelihood",
    "parameter_ci.hint": "Parameter intervals describe coefficient uncertainty, not a curve band. Weighted profiles keep the confirmed observation scales fixed. IRLS intervals are conditional on final frozen weights. You can cancel the calculation; unresolved limits carry a reason.",
    "parameter_ci.error.method": "Choose Symmetric (Wald) or Profile likelihood.",
    "parameter_ci.error.level": "Choose a finite parameter confidence level strictly between 0 and 100.",
    "parameter_ci.error.weighting": "Parameter profile intervals currently require Unweighted regression.",
})
_IT.update({
    "custom.profile.hint": "I profili ristimano gli altri coefficienti liberi rispettando valori fissi e vincoli. Le SD relative inserite restano fisse. Puoi annullare; i limiti non determinati riportano il motivo.",
    "custom.field.Parameter intervals": "Intervalli dei parametri",
    "custom.error.profile_parameters": "I profili supportano al massimo {count} coefficienti liberi per fit.",
    "custom.error.profile_points": "I profili supportano al massimo {count} osservazioni complete per fit.",
    "parameter_ci.tab": "Intervalli di confidenza",
    "parameter_ci.method": "Intervalli dei parametri",
    "parameter_ci.level": "Livello di confidenza dei parametri (%)",
    "parameter_ci.wald": "Simmetrici (Wald)",
    "parameter_ci.profile": "Profilo di verosimiglianza",
    "parameter_ci.hint": "Gli intervalli descrivono l’incertezza dei coefficienti, non una banda intorno alla curva. I profili pesati mantengono fisse le scale del fit confermato. Con IRLS gli intervalli sono condizionati ai pesi finali congelati. Puoi annullare il calcolo; i limiti non determinati riportano il motivo.",
    "parameter_ci.error.method": "Scegli Simmetrici (Wald) o Profilo di verosimiglianza.",
    "parameter_ci.error.level": "Scegli un livello di confidenza finito, strettamente compreso tra 0 e 100.",
    "parameter_ci.error.weighting": "Gli intervalli con profilo di verosimiglianza richiedono per ora una regressione non pesata.",
})
KEY_BY_LABEL[_EN["parameter_ci.level"]] = "parameter_ci.level"

_EN.update({
    "gfit.profile.hint": "Parameter profiles refit all series jointly, counting each shared coefficient once. The confidence level on this page applies to parameters; response bands use their separate level. Bounds and unavailable limits are reported explicitly. You can cancel the calculation.",
    "gfit.error.profile_parameters": "Global profile intervals support at most {count} free coordinates.",
    "gfit.error.profile_rows": "Global profile intervals support at most {count} complete observations in total.",
})
_IT.update({
    "gfit.profile.hint": "I profili ricalcolano tutte le serie insieme, contando una sola volta ogni coefficiente condiviso. Il livello di questa pagina riguarda i parametri; le bande della risposta hanno un livello separato. Vincoli e limiti non determinati sono indicati esplicitamente. Puoi annullare il calcolo.",
    "gfit.error.profile_parameters": "I profili globali supportano al massimo {count} coordinate libere.",
    "gfit.error.profile_rows": "I profili globali supportano al massimo {count} osservazioni complete complessive.",
})

_EN.update({
    "parameter_ci.error.weighting_choice": "Choose a supported regression weighting.",
    "parameter_ci.error.sd_column": "Choose a separate column of positive relative standard deviations.",
    "parameter_ci.error.sd_values": "Choose positive finite SDs for every complete observation.",
})
_IT.update({
    "parameter_ci.error.weighting_choice": "Scegli un metodo di pesatura supportato.",
    "parameter_ci.error.sd_column": "Scegli una colonna distinta di deviazioni standard relative positive.",
    "parameter_ci.error.sd_values": "Scegli SD positive e finite per ogni osservazione completa.",
})

# False-discovery messages stay English in the engine. The active language is applied here.
_EN.update({
    "fdr.error.p_count": "Select between 1 and 24 distinct p columns.",
    "fdr.error.family_count": "Select at most 4 distinct family columns.",
    "fdr.error.overlap": "A p column cannot also be a family column.",
    "fdr.error.missing": "Column {column} is not in the table.",
    "fdr.error.duplicate": "Column {column} occurs more than once in the table.",
    "fdr.error.reserved": "Family column {column} uses a reserved result name.",
    "fdr.error.scope": "Choose Each column separately or Pool selected columns.",
    "fdr.error.method": "Choose Benjamini–Hochberg, Benjamini–Yekutieli, or Two-stage Benjamini–Krieger–Yekutieli.",
    "fdr.error.level": "Enter a finite number strictly between 0 and 100.",
    "fdr.error.plot": "Choose whether to show the diagnostic plot.",
    "fdr.error.p": "Column {column} contains a value that is not a finite p in [0, 1].",
    "fdr.error.cells": "Use at most 200000 p values.",
    "fdr.error.families": "Use at most 200 nonempty families.",
    "fdr.error.plot_families": "A diagnostic plot shows at most 12 families.",
    "fdr.note": (
        "BH and two-stage BKY control the false discovery rate only under their dependence conditions. "
        "BY is more conservative. Trama does not test independence. Adjusted values depend on the requested FDR; "
        "they are not level-free q-values. The decision rejects every rank through the last one that satisfies "
        "p <= alpha × rank / m."
    ),
    "fdr.legend.threshold": "{method} at {level}%",
    "fdr.legend.discovery": "Discovery",
    "fdr.legend.not": "Not a discovery",
    "fdr.axis.rank": "Rank",
    "fdr.axis.p": "p",
    "fdr.figure.title": "{method}, FDR {level}%",
})
_IT.update({
    "fdr.error.p_count": "Seleziona da 1 a 24 colonne dei valori p, tutte diverse.",
    "fdr.error.family_count": "Seleziona al massimo 4 colonne della famiglia, tutte diverse.",
    "fdr.error.overlap": "Una colonna dei valori p non può essere anche una colonna della famiglia.",
    "fdr.error.missing": "La colonna {column} non è nella tabella.",
    "fdr.error.duplicate": "La colonna {column} compare più di una volta nella tabella.",
    "fdr.error.reserved": "La colonna della famiglia {column} usa un nome riservato ai risultati.",
    "fdr.error.scope": "Scegli Ogni colonna separatamente oppure Accorpa le colonne selezionate.",
    "fdr.error.method": "Scegli Benjamini–Hochberg, Benjamini–Yekutieli o Benjamini–Krieger–Yekutieli a due stadi.",
    "fdr.error.level": "Inserisci un numero finito strettamente compreso tra 0 e 100.",
    "fdr.error.plot": "Scegli se mostrare il grafico diagnostico.",
    "fdr.error.p": "La colonna {column} contiene un valore che non è un p finito in [0, 1].",
    "fdr.error.cells": "Usa al massimo 200000 valori p.",
    "fdr.error.families": "Usa al massimo 200 famiglie non vuote.",
    "fdr.error.plot_families": "Un grafico diagnostico mostra al massimo 12 famiglie.",
    "fdr.note": (
        "BH e BKY a due stadi controllano il tasso di false scoperte solo alle condizioni di dipendenza dichiarate. "
        "BY è più conservativo. Trama non verifica l’indipendenza. I valori aggiustati dipendono dall’FDR richiesto; "
        "non sono q-value indipendenti dal livello. La decisione rifiuta ogni rango fino all’ultimo che soddisfa "
        "p <= alpha × rango / m."
    ),
    "fdr.legend.threshold": "Soglia {method} al {level}%",
    "fdr.legend.discovery": "Scoperta",
    "fdr.legend.not": "Non è una scoperta",
    "fdr.axis.rank": "Rango",
    "fdr.axis.p": "p",
    "fdr.figure.title": "{method}, FDR {level}%",
})
