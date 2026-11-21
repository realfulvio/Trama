"""Reproducible analysis report (analisi/report_bundle.py): writing, verification and failure paths.

The checks read the ZIP with ``zipfile``, ``json`` and ``html.parser`` on their own, so they do not
trust the verifier of the module they test.
"""
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from analisi import report_bundle as rb

TITLE = "Control $ <A> & β"
NOTE = "Confronto <script>test</script> tra curve\nseconda riga"
METADATA = {"trama_version": "0.95.0", "created_utc": "2026-11-19T12:00:00Z", "language": "it"}
CSV = "Dose,Risposta\n0,1\n1,3\n2,4\n3,8\n4,9\n".encode()
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><title>β &amp; $</title>'
       '<path d="M0 0 L10 10"/></svg>').encode()


def sections(count=2):
    base = [{"label": "Risposta $ <B>", "kind": "table", "method": "Linear regression",
             "options": {"X": "Dose", "Y": "Risposta", "Weights": None, "Level": 0.95, "List": [1, "a"]},
             "payload": CSV},
            {"label": "Curva β", "kind": "figure", "method": "Linear regression",
             "options": {"X": "Dose", "Y": "Risposta"}, "payload": SVG}]
    return [dict(base[i % 2]) for i in range(count)]


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.parts, self.links = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.links += [value for name, value in attrs if name in {"href", "src"}]

    def handle_data(self, data):
        self.parts.append(data)


class ReportBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name="report.zip", items=None, **options):
        path = self.root / name
        options.setdefault("metadata", METADATA)
        options.setdefault("note", NOTE)
        rb.export_bundle(path, TITLE, sections() if items is None else items, **options)
        return path

    def listing(self):
        return sorted(path.name for path in self.root.iterdir())

    # -- contents --------------------------------------------------------------------------------
    def test_members_manifest_and_checksums_read_independently(self):
        path = self.write()
        with zipfile.ZipFile(path) as bundle:
            names = bundle.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(set(names), {"index.html", "manifest.json", "tables/001.csv", "figures/002.svg"})
            manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["format"], "trama-analysis-report")
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["project_title"], TITLE)
            self.assertEqual(manifest["metadata"], METADATA)
            self.assertEqual([s["file"] for s in manifest["sections"]], ["tables/001.csv", "figures/002.svg"])
            self.assertEqual(manifest["sections"][0]["options"]["Weights"], None)
            self.assertEqual([f["path"] for f in manifest["files"]],
                             ["figures/002.svg", "index.html", "tables/001.csv"])
            for record in manifest["files"]:
                content = bundle.read(record["path"])
                self.assertEqual(record["size"], len(content))
                self.assertEqual(record["sha256"], sha256(content).hexdigest())
            self.assertEqual(bundle.read("tables/001.csv"), CSV)
            self.assertEqual(bundle.read("figures/002.svg"), SVG)
            for info in bundle.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
        self.assertEqual(rb.verify_bundle(path), manifest)
        self.assertNotIn(str(self.root), path.read_bytes().decode("latin-1"))

    def test_index_is_offline_and_shows_markup_literally(self):
        path = self.write()
        with zipfile.ZipFile(path) as bundle:
            page = bundle.read("index.html").decode("utf-8")
        parser = Text()
        parser.feed(page)
        text = "".join(parser.parts)
        self.assertNotIn("script", parser.tags)
        self.assertIn(TITLE, text)
        self.assertIn(NOTE, text)
        self.assertIn("Risposta $ <B>", text)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("http://", page.replace('xmlns="http://www.w3.org', ""))
        self.assertNotIn("https://", page)
        self.assertNotIn("@import", page)
        self.assertTrue({"tables/001.csv", "figures/002.svg", "#s001", "#s002"} <= set(parser.links))
        self.assertIn('<html lang="it">', page)
        self.assertIn("Tabella completa (CSV)", text)

    def test_english_report_and_long_table_preview(self):
        rows = "x\n" + "".join(f"{i}\n" for i in range(40))
        items = [{"label": "Long", "kind": "table", "method": "M", "options": {}, "payload": rows.encode()}]
        path = self.write(items=items, metadata={**METADATA, "language": "en"})
        with zipfile.ZipFile(path) as bundle:
            page = bundle.read("index.html").decode("utf-8")
        self.assertIn("Preview of the first 25 rows.", page)
        self.assertIn("<td>24</td>", page)
        self.assertNotIn("<td>25</td>", page)

    def test_project_copy_is_optional_and_byte_identical(self):
        self.assertNotIn("project.alab", zipfile.ZipFile(self.write()).namelist())
        project = b'{"version": 2, "tables": []}'
        path = self.write("with.zip", project_bytes=project)
        with zipfile.ZipFile(path) as bundle:
            self.assertEqual(bundle.read("project.alab"), project)
            self.assertIn("project.alab", bundle.read("index.html").decode())
        self.assertIn("project.alab", [f["path"] for f in rb.verify_bundle(path)["files"]])

    def test_same_input_gives_the_same_zip_bytes(self):
        first, second = self.write("a.zip"), self.write("b.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_section_files_follow_position_not_title(self):
        items = sections(4)
        items[2]["label"] = items[0]["label"]  # Same label twice: the files still differ.
        manifest = rb.verify_bundle(self.write(items=items))
        self.assertEqual([s["file"] for s in manifest["sections"]],
                         ["tables/001.csv", "figures/002.svg", "tables/003.csv", "figures/004.svg"])

    # -- refused input ---------------------------------------------------------------------------
    def test_invalid_requests_are_refused_before_writing(self):
        bad = [
            dict(items=[]),
            dict(items=sections(rb.MAX_SECTIONS + 1)),
            dict(items=[{**sections()[0], "kind": "image"}]),
            dict(items=[{**sections()[0], "label": "  "}]),
            dict(items=[{**sections()[0], "options": {"x": float("nan")}}]),
            dict(items=[{**sections()[0], "options": {"x": object()}}]),
            dict(items=[{**sections()[0], "options": {1: "x"}}]),
            dict(items=[{**sections()[0], "payload": "text"}]),
            dict(items=[{**sections()[0], "payload": b"\xff\xfe"}]),
            dict(items=[{**sections()[1], "payload": b"<html/>"}]),
            dict(items=[{**sections()[1], "payload": b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'}]),
            dict(metadata={**METADATA, "host": "pc"}),
            dict(metadata={**METADATA, "created_utc": "yesterday"}),
            dict(metadata={**METADATA, "language": "fr"}),
            dict(project_bytes="not bytes"),
        ]
        for case in bad:
            with self.subTest(case=str(case)[:80]), self.assertRaises(ValueError):
                self.write(**case)
        with self.assertRaises(ValueError):
            rb.export_bundle(self.root / "report.txt", TITLE, sections(), metadata=METADATA)
        with self.assertRaises(ValueError):
            rb.export_bundle(self.root / "x.zip", "", sections(), metadata=METADATA)
        self.assertEqual(self.listing(), [])

    def test_budget_is_checked_before_building_the_members(self):
        with mock.patch.object(rb, "MAX_TOTAL_BYTES", len(CSV) + len(SVG) - 1), \
                mock.patch.object(rb, "render_index", side_effect=AssertionError("built index")), \
                self.assertRaisesRegex(ValueError, "exceed"):
            self.write()
        with mock.patch.object(rb, "MAX_TOTAL_BYTES", len(CSV) + len(SVG) + 10), \
                self.assertRaisesRegex(ValueError, "exceed"):
            self.write(project_bytes=b"x" * 20)
        self.assertEqual(self.listing(), [])

    # -- cancellation and failures ---------------------------------------------------------------
    def test_cancel_at_start_and_before_commit_keeps_previous_bytes(self):
        path = self.write()
        original = path.read_bytes()
        before = self.listing()
        with self.assertRaises(rb.ReportCancelled):
            self.write(cancel=lambda: True, note="other")
        calls = []

        def late():
            calls.append(1)
            return len(calls) >= 7  # Start, after validation, four members, then the check before the commit.
        with self.assertRaises(rb.ReportCancelled):
            self.write(cancel=late, note="other")
        self.assertEqual(len(calls), 7)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.listing(), before)

    def test_failed_replace_and_failed_write_keep_previous_bytes(self):
        path = self.write()
        original, before = path.read_bytes(), self.listing()
        with mock.patch.object(rb.os, "replace", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            self.write(note="other")
        with mock.patch.object(rb.zipfile.ZipFile, "writestr", side_effect=OSError("I/O error")), \
                self.assertRaises(OSError):
            self.write(note="other")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.listing(), before)

    def test_unwritable_folder_raises_os_error(self):
        with self.assertRaises(OSError):
            rb.export_bundle(self.root / "missing" / "r.zip", TITLE, sections(), metadata=METADATA)

    # -- verification ----------------------------------------------------------------------------
    def rewrite(self, source, name, *, replace=None, extra=(), drop=(), manifest=None):
        target = self.root / name
        with zipfile.ZipFile(source) as before, zipfile.ZipFile(target, "w") as after:
            for member in before.namelist():
                if member in drop:
                    continue
                content = before.read(member)
                if member == "manifest.json" and manifest is not None:
                    content = manifest(json.loads(content))
                    content = content if isinstance(content, bytes) else json.dumps(content).encode()
                after.writestr(member, replace.get(member, content) if replace else content)
            for member, content in extra:
                after.writestr(member, content)
        return target

    def test_verify_refuses_damaged_or_unexpected_archives(self):
        valid = self.write()
        cases = {
            "changed member": dict(replace={"tables/001.csv": b"Dose,Risposta\n0,2\n"}),
            "same size change": dict(replace={"tables/001.csv": CSV.replace(b"9", b"8")}),
            "extra member": dict(extra=[("extra.txt", b"x")]),
            "outside root": dict(extra=[("../outside.txt", b"x")]),
            "absolute": dict(extra=[("/etc/passwd", b"x")]),
            "backslash": dict(extra=[("tables\\x.csv", b"x")]),
            "duplicate": dict(extra=[("index.html", b"x")]),
            "missing member": dict(drop=["figures/002.svg"]),
            "no manifest": dict(drop=["manifest.json"]),
            "schema": dict(manifest=lambda m: {**m, "schema_version": 2}),
            "format": dict(manifest=lambda m: {**m, "format": "other"}),
            "extra field": dict(manifest=lambda m: {**m, "host": "pc"}),
            "nan": dict(manifest=lambda m: json.dumps(m).replace('"Level": 0.95', '"Level": NaN').encode()),
            "unsorted": dict(manifest=lambda m: {**m, "files": list(reversed(m["files"]))}),
            "renamed file": dict(manifest=lambda m: {**m, "sections": [{**m["sections"][0],
                                                                          "file": "tables/009.csv"},
                                                                         m["sections"][1]]}),
            "declared size": dict(manifest=lambda m: {**m, "files": [{**f, "size": f["size"] + 1}
                                                                       for f in m["files"]]}),
            "not json": dict(manifest=lambda m: b"{not json"),
        }
        for index, (name, change) in enumerate(cases.items()):
            with self.subTest(name), self.assertRaises(ValueError):
                rb.verify_bundle(self.rewrite(valid, f"bad-{index}.zip", **change))
        (self.root / "junk.zip").write_bytes(b"not a zip")
        with self.assertRaises(ValueError):
            rb.verify_bundle(self.root / "junk.zip")

    def test_verify_refuses_declared_sizes_over_budget_without_reading(self):
        valid = self.write()
        with mock.patch.object(rb, "MAX_TOTAL_BYTES", 100), \
                mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("read")), \
                self.assertRaisesRegex(ValueError, "budget"):
            rb.verify_bundle(valid)

    def test_project_bytes_and_payload_are_not_altered(self):
        project = os.urandom(512)
        path = self.write(project_bytes=project)
        with zipfile.ZipFile(path) as bundle:
            self.assertEqual(bundle.read("project.alab"), project)


if __name__ == "__main__":
    unittest.main()
