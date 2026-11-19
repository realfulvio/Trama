from base64 import b64encode
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from zlib import compress

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.workbench import analyse
from test_prism_binary_editable import _group
from test_prism_binary_graphs import _record


def binding_template(equation=b"Y=Bmax*X/(Kd+X)\r\n\0", source=8, fit_type=5, *, transform=None):
    index = bytearray(10064)
    pack_into("<I", index, 40, 1)
    pack_into("<I", index, 44, 1)
    pack_into("<i", index, 60, 8)
    pack_into("<i", index, 2060, 4)
    scatchard = b""
    if transform is not None:
        pack_into("<I", index, 44, 2)
        pack_into("<i", index, 2064, 6)
        heading = b"Transform: Pharmacology and biochemistry transforms: " + transform
        scatchard = _group(0x8039, pack("<H", 6), (
            _record(9, b"Bound and free\0")
            + _record(0xA, (bytes(24) + heading).ljust(300, b"\0"))
            + _record(0x3A, pack("<8H", 3, 255, 1, 1, 191, 0, 1, 0))
            + _record(0x3B, pack("<2i", 1, source))
            + _record(0x3C, pack("<11i", 10, 3, *([-1] * 9)))
            + _record(0x3D, pack("<7H", 1, 1, 0, 65535, 65535, 65535, 65535))
        ))
    formula = _record(0x49, equation)
    parameters = pack("<4i4B6i", 1, 0, 2, 0, 35, 16, 0, 9, 1, 1, 1, 1, -1, -1)
    return b"PCFFGRA4" + _group(0x8001, bytes(12), (
        _group(0x8002, index)
        + _group(0x8039, pack("<H", 4), (
            _record(9, b"Saturation fit\0")
            + _record(0xA, (bytes(24) + b"One site binding (hyperbola)Least squares fit").ljust(300, b"\0"))
            + _record(0x3A, pack("<8H", 0, fit_type, 0, 1, 255, 1, 65535, 0))
            + _record(0x3B, pack("<2i", 1, source))
            + _record(0x3D, pack("<7H", 1, 1, 0, 65535, 65535, 65535, 65535))
            + _group(0x8047, parameters, _group(0x8048, bytes(114), formula))
        )) + scatchard
    ))


def write_project(path, template):
    payload = b64encode(compress(template)).decode()
    path.write_text(
        '<GraphPadPrismFile xmlns:dt="urn:schemas-microsoft-com:datatypes">'
        '<Table ID="Table8" XFormat="numbers" YFormat="replicates" Replicates="1" TableType="XY">'
        '<Title>Binding</Title><XColumn><Title>Concentration</Title>'
        '<Subcolumn><d>1</d><d>2</d><d>6</d><d>10</d><d>18</d></Subcolumn>'
        '</XColumn><YColumn><Title>Signal</Title>'
        '<Subcolumn><d>15</d><d>24</d><d>40</d><d>46.1538461538462</d><d>51.4285714285714</d></Subcolumn>'
        '</YColumn></Table><Template dt:dt="bin.base64">' + payload + '</Template></GraphPadPrismFile>',
        encoding="utf-8",
    )


class PrismXmlBindingTests(unittest.TestCase):
    def test_indexed_fit_uses_the_real_source_through_round_trip_and_edit(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "saturation.pzt"
            write_project(path, binding_template())
            self.assertFalse(Dataset(load_tables(path)["Binding"]).analyses)
            dataset = Dataset(load_tables(path, restore_prism=True)["Binding"])
            (method, options), = dataset.analyses
            self.assertEqual(method, "Nonlinear regression")
            self.assertEqual(options["Model"], "One-site specific binding")
            fitted = analyse(method, dataset.frame(mask_excluded=True), options)
            bmax, kd = fitted.tables["Parameters: All"]["Estimate"]
            self.assertAlmostEqual(bmax, 60)
            self.assertAlmostEqual(kd, 3)
            dataset.raw["Signal"] *= 2
            saved = path.with_suffix(".alab")
            save_project(saved, {"Binding": dataset})
            restored = load_project(saved)["Binding"]
            (method, options), = restored.analyses
            bmax, kd = analyse(method, restored.frame(mask_excluded=True), options).tables["Parameters: All"]["Estimate"]
            self.assertAlmostEqual(bmax, 120)
            self.assertAlmostEqual(kd, 3)

    def test_unverified_equation_analysis_kind_or_source_keeps_only_the_data(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "refused.pzt"
            for template in (binding_template(equation=b"Y=Bmax*X\r\n\0"),
                             binding_template(source=9), binding_template(fit_type=6)):
                write_project(path, template)
                dataset = Dataset(load_tables(path, restore_prism=True)["Binding"])
                self.assertEqual(dataset.raw.shape, (5, 2))
                self.assertFalse(dataset.analyses)

    def test_scatchard_uses_live_bound_and_free_values_after_reopening(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "binding.pzt"
            write_project(path, binding_template(transform=b"Scatchard"))
            dataset = Dataset(load_tables(path, restore_prism=True)["Binding"])
            self.assertEqual([method for method, _ in dataset.analyses],
                             ["Nonlinear regression", "Scatchard transformation"])
            method, options = dataset.analyses[1]
            result = analyse(method, dataset.frame(mask_excluded=True), options).tables["Scatchard"]
            self.assertEqual(result["Bound"].tolist()[:3], [15.0, 24.0, 40.0])
            self.assertEqual(result["Bound / free"].tolist()[:2], [15.0, 12.0])
            dataset.raw.loc[0, "Signal"] = 12.0
            dataset.raw.loc[1, "Concentration"] = 0.0
            dataset.excluded.add((2, 1))
            saved = path.with_suffix(".alab")
            save_project(saved, {"Binding": dataset})
            reopened = load_project(saved)["Binding"]
            method, options = reopened.analyses[1]
            result = analyse(method, reopened.frame(mask_excluded=True), options).tables["Scatchard"]
            self.assertEqual(len(result), 5)
            self.assertEqual(result["Bound / free"].iloc[0], 12.0)
            self.assertTrue(result["Bound / free"].iloc[1:3].isna().all())

    def test_other_saved_transform_does_not_create_a_scatchard_recipe(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "unknown-transform.pzt"
            write_project(path, binding_template(transform=b"Other transform"))
            dataset = Dataset(load_tables(path, restore_prism=True)["Binding"])
            self.assertEqual([method for method, _ in dataset.analyses], ["Nonlinear regression"])
