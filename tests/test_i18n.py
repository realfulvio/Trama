"""Italian/English interface catalog and the language preference (no GUI needed)."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analisi import i18n
from analisi.i18n import (CATALOGS, KEY_BY_LABEL, LANGUAGE_NAMES, config_path, load_language, placeholders,
                          save_language, translate)

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data" / "i18n"
UI_PREFIXES = ("menu.", "command.", "ribbon.", "bar.", "nav.")


def _app_method(name):
    tree = ast.parse((ROOT / "tramastat.py").read_text(encoding="utf-8"))
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App")
    return next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == name)


def menu_commands():
    """The literal ``commands`` table of App._build: {menu title: [English labels]}."""
    build = _app_method("_build")
    table = next(node.value for node in ast.walk(build) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "commands" for target in node.targets))
    return {title.value: [entry.elts[0].value for entry in entries.elts]
            for title, entries in zip(table.keys, table.values, strict=True)}


def ribbon_groups():
    ribbon = _app_method("build_ribbon")
    groups = next(node.value for node in ast.walk(ribbon) if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "groups" for target in node.targets))
    result = {}
    for group in groups.elts:
        title, *rows = group.elts
        result[title.value] = [button.elts[0].value for row in rows for button in row.elts]
    return result


class FixtureContract(unittest.TestCase):
    def test_package_fixture(self):
        fixture = json.loads((DATA / "language.json").read_text(encoding="utf-8"))
        keys = [row[0] for row in fixture["labels"]]
        self.assertEqual(len(keys), len(set(keys)))
        for key, english, italian in fixture["labels"]:
            self.assertEqual(translate("en", key), english, key)
            self.assertEqual(translate("it", key), italian, key)
            self.assertEqual(translate("unknown", key), english, key)
        status = fixture["status"]
        for code in ("en", "it"):
            self.assertEqual(translate(code, status["key"], **status["values"]), status[code])


class Translation(unittest.TestCase):
    def test_defaults_and_fallbacks(self):
        self.assertEqual(translate("it", "invalid.unknown.key"), "invalid.unknown.key")
        self.assertEqual(translate("en", "invalid.unknown.key", name="x"), "invalid.unknown.key")
        for code in (None, 4, "", "IT", "it_IT", "und", "fr"):
            self.assertEqual(translate(code, "menu.edit"), "Edit", code)
        with patch.dict(CATALOGS["it"], clear=False):
            del CATALOGS["it"]["menu.edit"]
            self.assertEqual(translate("it", "menu.edit"), "Edit")

    def test_values_are_inserted_literally(self):
        for name in ("Misurazioni {A} – città.alab", "{name}", "{0}", "%s {{x}}", "Tabella ü {count}"):
            self.assertEqual(translate("it", "status.saved", name=name), f"Salvato {name}.")
            self.assertEqual(translate("en", "status.opened", name=name), f"Opened {name}.")
        self.assertEqual(translate("en", "project.untitled", number=3), "Untitled 3")
        # A missing value leaves its placeholder visible instead of raising.
        self.assertEqual(translate("it", "status.saved"), "Salvato {name}.")
        self.assertEqual(translate("it", "status.saved", other="x"), "Salvato {name}.")

    def test_catalogs_are_complete_and_placeholders_match(self):
        english, italian = CATALOGS["en"], CATALOGS["it"]
        self.assertEqual(set(english), set(italian), "every interface key needs both languages")
        for key, text in english.items():
            self.assertTrue(text and italian[key], key)
            self.assertEqual(placeholders(text), placeholders(italian[key]), key)

    def test_same_english_label_means_same_italian_label(self):
        seen = {}
        for key, text in CATALOGS["en"].items():
            if key.startswith(UI_PREFIXES):
                seen.setdefault(text, set()).add(CATALOGS["it"][key])
        self.assertEqual({text: values for text, values in seen.items() if len(values) > 1}, {})

    def test_language_names_stay_bilingual(self):
        self.assertEqual(LANGUAGE_NAMES, {"en": "English", "it": "Italiano"})
        for code in ("en", "it"):
            title = translate(code, "language.title")
            self.assertIn("Language", title)
            self.assertIn("Lingua", title)

    def test_active_language(self):
        original = i18n.active_language()
        try:
            self.assertEqual(i18n.set_language("it"), "it")
            self.assertEqual(i18n.ui("Paste Special…"), "Incolla speciale…")
            self.assertEqual(i18n.ui("Not a known label"), "Not a known label")
            self.assertEqual(i18n.set_language("xx"), "en")
            self.assertEqual(i18n.ui("Paste Special…"), "Paste Special…")
        finally:
            i18n.set_language(original)


class MainWindowCoverage(unittest.TestCase):
    def test_menu_labels_are_translated_and_unique(self):
        commands = menu_commands()
        self.assertIn("Language…", commands["Edit"])
        self.assertIn("Paste Special…", commands["Edit"])
        for title, labels in commands.items():
            self.assertIn(title, KEY_BY_LABEL, title)
            self.assertEqual(len(labels), len(set(labels)), f"duplicate English entries in {title}")
            italian = [translate("it", KEY_BY_LABEL[label]) for label in labels if label in KEY_BY_LABEL]
            self.assertEqual(len(italian), len(labels), [label for label in labels if label not in KEY_BY_LABEL])
            self.assertEqual(len(italian), len(set(italian)), f"duplicate Italian entries in {title}")
        headers = [translate("it", KEY_BY_LABEL[title]) for title in commands]
        self.assertEqual(len(headers), len(set(headers)))

    def test_ribbon_labels_are_translated(self):
        for title, labels in ribbon_groups().items():
            for label in (title, *labels):
                self.assertIn(label, KEY_BY_LABEL, label)
                self.assertNotEqual(translate("it", KEY_BY_LABEL[label]), "", label)

    def test_menu_entries_of_the_058_changes_are_covered(self):
        for label, italian in (("Export with options…", "Esporta con opzioni…"),
                               ("Export multiple sheets to PDF…", "Esporta più fogli in PDF…"),
                               ("Transpose X and Y…", "Trasponi X e Y…"),
                               ("Compact Letter Display…", "Lettere compatte…")):
            self.assertEqual(translate("it", KEY_BY_LABEL[label]), italian)

    def test_navigator_and_bar_labels(self):
        for label in ("Family", "Search results", "Data + Results", "Data Tables", "Info", "Results", "Graphs",
                      "Layouts", "New Data Table…", "New Info Sheet…", "New Analysis…", "New Graph…",
                      "New Layout…", "Show or hide Navigator", "Sheet gallery", "Previous sheet", "Next sheet",
                      "Linked sheets", "Data tables", "Info sheets"):
            self.assertIn(label, KEY_BY_LABEL, label)

    def test_table_formats_bind_display_to_codes(self):
        from analisi.table_setup import GROUPED_FORMATS, TEMPLATES, XY_FORMATS, format_label

        original = i18n.active_language()
        try:
            i18n.set_language("it")
            self.assertEqual([format_label(template.kind) for template in TEMPLATES],
                             ["XY", "Colonne", "Raggruppata", "Contingenza", "Sopravvivenza", "Parti di un intero",
                              "Variabili multiple", "Annidata"])
            for code in (*XY_FORMATS, *GROUPED_FORMATS):
                self.assertNotEqual(format_label(code), code, code)
            i18n.set_language("en")
            self.assertEqual([format_label(template.kind) for template in TEMPLATES],
                             [template.name for template in TEMPLATES])
            for code in (*XY_FORMATS, *GROUPED_FORMATS):
                self.assertEqual(format_label(code), code)
        finally:
            i18n.set_language(original)
        # Canonical names and kinds stay English: they become table titles and .alab metadata.
        self.assertEqual(TEMPLATES[0].name, "XY")
        self.assertEqual(TEMPLATES[0].kind, "xy")


class Preferences(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "config" / "preferences.json"

    def tearDown(self):
        self.directory.cleanup()

    def test_missing_or_broken_files_mean_english(self):
        self.assertEqual(load_language(self.path), "en")
        self.path.parent.mkdir()
        for content in ("{", "null", "[]", '"it"', '{"language":4}', '{"language":null}', '{"language":"und"}',
                        '{"language":"IT"}', '{}', '{"language":["it"]}'):
            self.path.write_text(content, encoding="utf-8")
            self.assertEqual(load_language(self.path), "en", content)
        self.path.write_bytes(b"\xff\xfe\x00broken")
        self.assertEqual(load_language(self.path), "en")
        self.path.unlink()
        self.path.mkdir()  # a directory where the file should be cannot be read
        self.assertEqual(load_language(self.path), "en")

    def test_round_trip_creates_the_directory_and_writes_utf8(self):
        save_language(self.path, "it")
        self.assertEqual(load_language(self.path), "it")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"language": "it"})
        save_language(self.path, "en")
        self.assertEqual(load_language(self.path), "en")
        self.assertEqual(sorted(os.listdir(self.path.parent)), ["preferences.json"])

    def test_other_settings_are_kept(self):
        self.path.parent.mkdir()
        self.path.write_text('{"language": "en", "città": "Ünïcode"}', encoding="utf-8")
        save_language(self.path, "it")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"language": "it", "città": "Ünïcode"})

    def test_invalid_codes_are_rejected_without_touching_the_file(self):
        save_language(self.path, "it")
        before = self.path.read_bytes()
        for code in ("invalid", "", None, "IT", 3):
            with self.assertRaises(ValueError):
                save_language(self.path, code)
            self.assertEqual(self.path.read_bytes(), before)

    def test_failed_write_keeps_the_previous_preference(self):
        save_language(self.path, "it")
        before = self.path.read_bytes()
        with patch("analisi.i18n.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_language(self.path, "en")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(os.listdir(self.path.parent), ["preferences.json"], "temporary file left behind")
        with patch("analisi.i18n.json.dump", side_effect=OSError("write error")):
            with self.assertRaises(OSError):
                save_language(self.path, "en")
        self.assertEqual(load_language(self.path), "it")
        self.assertEqual(os.listdir(self.path.parent), ["preferences.json"])

    def test_config_locations(self):
        self.assertEqual(config_path({"APPDATA": r"C:\Users\x\AppData\Roaming"}, "win32"),
                         Path(r"C:\Users\x\AppData\Roaming") / "TramaStat" / "preferences.json")
        self.assertEqual(config_path({"XDG_CONFIG_HOME": "/tmp/cfg"}, "linux"),
                         Path("/tmp/cfg/tramastat/preferences.json"))
        self.assertEqual(config_path({}, "linux"), Path.home() / ".config" / "tramastat" / "preferences.json")
        executable = Path(__file__).resolve().parents[1]
        for path in (config_path({}, "linux"), config_path({"XDG_CONFIG_HOME": "/tmp/cfg"}, "linux")):
            self.assertNotIn(executable, path.parents)


if __name__ == "__main__":
    unittest.main()
