"""Figure style presets: schema, transfer rules and the local library (no Qt needed)."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unicodedata
import unittest
from unittest import mock

from trama_qt import graph_style_presets as gsp

# The oracle of the Stili-Figura-Qt-095 package (fixture/style-cases.json), kept here verbatim.
SOURCE = {"title": "Calibrazione $ A", "xlabel": "Dose", "accent": "#0B7A73", "font_family": "serif",
          "title_size": 18, "grid": True, "legend": "upper right", "xscale": "log",
          "axis": {"x": {"min": 1, "max": 10}}}
TARGET = {"title": "Calibrazione B", "xlabel": "Tempo", "accent": "#AA4433", "grid": False, "xscale": "linear",
          "axis": {"x": {"min": 0, "max": 20}}, "series": {"line:1:Seconda": {"color": "#AA4433"}}}
PRESET = {"version": 1, "name": "Pubblicazione",
          "style": {"accent": "#0B7A73", "font_family": "serif", "title_size": 18, "grid": True,
                    "legend": "upper right"}}
EXPECTED = {"title": "Calibrazione B", "xlabel": "Tempo", "accent": "#0B7A73", "grid": True, "xscale": "linear",
            "axis": {"x": {"min": 0, "max": 20}}, "series": {"line:1:Seconda": {"color": "#AA4433"}},
            "font_family": "serif", "title_size": 18, "legend": "upper right"}


def preset(name="Stile", **style):
    return {"version": 1, "name": name, "style": style or {"grid": True}}


class PresetSchemaTests(unittest.TestCase):
    def test_fixture_oracle(self):
        source, target = deepcopy(SOURCE), deepcopy(TARGET)
        made = gsp.extract_preset(" Pubblicazione ", source)
        self.assertEqual(made, PRESET)
        applied = gsp.apply_preset(target, made)
        self.assertEqual(applied, EXPECTED)
        applied["axis"]["x"]["min"] = 42
        made["style"]["accent"] = "red"
        self.assertEqual((source, target), (SOURCE, TARGET))
        self.assertEqual(gsp.apply_preset(target, PRESET)["axis"]["x"]["min"], 0)

    def test_every_transferable_field_and_nothing_else(self):
        full = {"accent": "#123456", "font_family": "monospace", "title_size": 20, "label_size": 12.5,
                "tick_size": 9, "legend_size": 8, "frame": "box", "grid": True, "grid_minor": False,
                "legend": "hidden"}
        kept = {"title": "T", "xlabel": "X", "ylabel": "Y", "xscale": "log", "yscale": "linear",
                "axis": {"y": {"min": 1, "max": 9}}, "series": {"line:1:A": {"color": "#000000"}},
                "groups": {}, "reference_lines": [{"axis": "y", "value": 3, "label": "ref"}],
                "legend_options": {"columns": 2}}
        made = gsp.extract_preset("Tutto", {**full, **kept})
        self.assertEqual(made["style"], full)
        self.assertEqual(list(made["style"]), list(gsp.TRANSFERABLE))
        target = deepcopy(kept)
        target["legend"] = "best"
        applied = gsp.apply_preset(target, made)
        for key, value in kept.items():
            self.assertEqual(applied[key], value, key)
        self.assertEqual(applied["legend"], "hidden")
        self.assertIsInstance(made["style"]["label_size"], float)
        self.assertIsInstance(made["style"]["tick_size"], int)
        self.assertIs(made["style"]["grid_minor"], False)

    def test_target_drawing_items_survive_exactly(self):
        shape = {"id": "0b7a7300-0000-4000-8000-000000000001", "kind": "rectangle", "units": "axes",
                 "points": [[0.1, 0.1], [0.4, 0.3]], "stroke": "#333333", "width": 1.5, "line_style": "dashed",
                 "fill": None, "alpha": 1.0, "layer": "above"}
        target = {"title": "Costo $ 5 e $ 7", "yscale": "log", "axis": {"y": {"min": 0.1, "max": 100}},
                  "shapes": [shape], "annotations": [], "legend_options": {"frame": False}}
        applied = gsp.apply_preset(target, preset(grid=True, legend="lower left"))
        self.assertEqual(applied["shapes"], [shape])
        self.assertEqual(applied["title"], "Costo $ 5 e $ 7")
        self.assertEqual(applied["yscale"], "log")
        self.assertEqual(applied["legend_options"], {"frame": False})
        self.assertIsNot(applied["shapes"][0], shape)

    def test_rgb_tuple_accent_becomes_json_list(self):
        made = gsp.extract_preset("RGB", {"accent": (0.1, 0.2, 0.3)})
        self.assertEqual(made["style"]["accent"], [0.1, 0.2, 0.3])
        self.assertEqual(json.loads(gsp.preset_bytes(made)), made)
        self.assertEqual(gsp.extract_preset("RGBA", {"accent": (0, 1, 0, 1)})["style"]["accent"], [0.0, 1.0, 0.0, 1.0])

    def test_names(self):
        self.assertEqual(gsp.extract_preset("  Rivista ✓ 日本 ", {"grid": True})["name"], "Rivista ✓ 日本")
        self.assertEqual(gsp.extract_preset("x" * 64, {"grid": True})["name"], "x" * 64)
        for bad in ("", "   ", "x" * 65, "riga\nnuova", "tab\tqui", None, 3):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                gsp.extract_preset(bad, {"grid": True})
        composed = unicodedata.normalize("NFC", "Città")
        decomposed = unicodedata.normalize("NFD", "CITTÀ")
        self.assertEqual(gsp.name_key(composed), gsp.name_key(decomposed))
        self.assertEqual(gsp.name_key("Straße"), gsp.name_key("STRASSE"))

    def test_invalid_presets_are_rejected_whole(self):
        invalid = [
            preset(grid=True) | {"version": 2},
            preset(grid=True) | {"version": "1"},
            preset(grid=True) | {"version": True},
            preset(grid=True) | {"version": 1.0},
            preset(" ", grid=True),
            preset(" Spazi", grid=True),
            {"version": 1, "name": "Titolo", "style": {"title": "Non trasferire"}},
            {"version": 1, "name": "Misto", "style": {"grid": True, "xscale": "log"}},
            {"version": 1, "name": "Vuoto", "style": {}},
            {"version": 1, "name": "Extra", "style": {"grid": True}, "author": "x"},
            {"version": 1, "name": "Manca"},
            {"version": 1, "name": "Lista", "style": [["grid", True]]},
            preset(title_size=200), preset(title_size=3), preset(title_size=True), preset(title_size="12"),
            preset(label_size=float("nan")), preset(tick_size=float("inf")),
            preset(font_family="fantasy"), preset(legend="nowhere"), preset(frame="double"),
            preset(grid="yes"), preset(grid_minor=1), preset(accent="not-a-colour"), preset(accent=[1, 2]),
            preset(accent=[True, False, True]), preset(accent=12),
            ["not", "a", "preset"], "Pubblicazione", None,
        ]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                gsp.apply_preset(TARGET, item)
        self.assertEqual(TARGET["grid"], False)

    def test_extract_needs_a_field_and_valid_values(self):
        with self.assertRaises(ValueError):
            gsp.extract_preset("Vuoto", {"title": "Solo titolo"})
        with self.assertRaises(ValueError):
            gsp.extract_preset("Vuoto", None)
        with self.assertRaises(ValueError):
            gsp.extract_preset("Rotto", {"title_size": 500})

    def test_combined_style_is_validated(self):
        with self.assertRaises(ValueError):
            gsp.apply_preset({"title": "x", "bogus": 1}, preset(grid=True))


class PresetFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_export_import_round_trip(self):
        path = self.folder / "pubblicazione.json"
        gsp.write_preset_file(path, PRESET)
        self.assertEqual(gsp.read_preset_file(path), PRESET)
        self.assertFalse([name for name in os.listdir(self.folder) if name.endswith(".tmp")])

    def test_import_rejects_truncated_large_and_libraries(self):
        text = json.dumps(PRESET)
        cases = {"truncated.json": text[:-7], "big.json": json.dumps(preset(grid=True)) + " " * gsp.MAX_PRESET_BYTES,
                 "library.json": json.dumps({"version": 1, "presets": [PRESET]}),
                 "nan.json": text.replace("18", "NaN"), "latin.json": None}
        for name, content in cases.items():
            path = self.folder / name
            if content is None:
                path.write_bytes(json.dumps(preset("Caffè", grid=True), ensure_ascii=False).encode("latin-1"))
            else:
                path.write_text(content, encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ValueError):
                gsp.read_preset_file(path)
        with self.assertRaises(ValueError):
            gsp.read_preset_file(self.folder / "missing.json")

    def test_library_path_is_next_to_preferences(self):
        from analisi.i18n import config_dir
        self.assertEqual(gsp.library_path(), config_dir() / "graph-style-presets.json")


class PresetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "prefs" / "graph-style-presets.json"
        self.library = gsp.PresetLibrary(self.path).load()

    def reread(self):
        return gsp.PresetLibrary(self.path).load()

    def test_missing_file_is_an_empty_library_and_reading_writes_nothing(self):
        self.assertEqual(self.library.presets, [])
        self.assertFalse(self.path.exists())

    def test_save_rename_delete(self):
        self.library.save(PRESET)
        self.assertEqual(self.reread().names(), ["Pubblicazione"])
        with self.assertRaises(FileExistsError) as caught:
            self.library.save(preset("PUBBLICAZIONE", grid=False))
        self.assertEqual(str(caught.exception), "Pubblicazione")
        self.assertEqual(self.reread().get("pubblicazione")["style"], PRESET["style"])
        self.library.save(preset("PUBBLICAZIONE", grid=False), replace=True)
        self.assertEqual(self.reread().names(), ["PUBBLICAZIONE"])
        self.library.save(preset("Poster", legend="best"))
        with self.assertRaises(FileExistsError):
            self.library.rename("Poster", "pubblicazione")
        self.library.rename("Poster", "Poster A0")
        self.library.rename("poster a0", "Poster a0")  # Only the case changes: same entry.
        self.assertEqual(self.reread().names(), ["PUBBLICAZIONE", "Poster a0"])
        self.library.rename("Poster a0", "Pubblicazione", replace=True)
        self.assertEqual(self.reread().names(), ["Pubblicazione"])
        self.assertEqual(self.reread().get("Pubblicazione")["style"], {"legend": "best"})
        self.library.delete("pubblicazione")
        self.assertEqual(self.reread().presets, [])
        with self.assertRaises(KeyError):
            self.library.delete("Pubblicazione")

    def test_at_most_100_presets(self):
        for number in range(gsp.MAX_PRESETS):
            self.library.presets.append(preset(f"Stile {number}", grid=bool(number % 2)))
        self.library._commit(self.library.presets)
        with self.assertRaises(ValueError):
            self.library.save(preset("Uno di troppo", grid=True))
        self.library.save(preset("stile 7", grid=True), replace=True)  # Replacing still works.
        self.assertEqual(len(self.reread().presets), gsp.MAX_PRESETS)

    def test_write_error_keeps_file_and_memory(self):
        self.library.save(PRESET)
        before = self.path.read_bytes()
        with mock.patch("trama_qt.graph_style_presets.os.replace", side_effect=PermissionError(13, "Denied")):
            with self.assertRaises(OSError):
                self.library.save(preset("Nuovo", grid=True))
            with self.assertRaises(OSError):
                self.library.delete("Pubblicazione")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.library.names(), ["Pubblicazione"])
        self.assertEqual([name for name in os.listdir(self.path.parent) if name.endswith(".tmp")], [])

    def test_damaged_library_is_reported_and_left_alone(self):
        damaged = {
            "truncated": '{"version": 1, "presets": [{"version": 1, "name": "A", "style": {"grid": tr',
            "bad preset": json.dumps({"version": 1, "presets": [preset(title_size=500)]}),
            "duplicate": json.dumps({"version": 1, "presets": [preset("A"), preset("a")]}),
            "unknown version": json.dumps({"version": 9, "presets": []}),
            "not a library": json.dumps([PRESET]),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for label, text in damaged.items():
            self.path.write_text(text, encoding="utf-8")
            library = gsp.PresetLibrary(self.path)
            with self.subTest(label=label), self.assertRaises(gsp.LibraryError) as caught:
                library.load()
            self.assertEqual(caught.exception.path, self.path)
            self.assertEqual(library.presets, [])
            with self.assertRaises(ValueError):
                library.save(PRESET)
            self.assertEqual(self.path.read_text(encoding="utf-8"), text)
        moved = library.set_aside()
        self.assertTrue(moved.name.startswith("graph-style-presets.damaged-"))
        self.assertEqual(moved.read_text(encoding="utf-8"), damaged["not a library"])
        self.assertFalse(self.path.exists())
        library.save(PRESET)
        self.assertEqual(self.reread().names(), ["Pubblicazione"])


if __name__ == "__main__":
    unittest.main()
