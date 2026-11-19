"""Recovery copies on disk (``trama_qt/recovery_store.py``): no Qt, no display.

Covers the commit order (a crash between payload and reference), checksums, out-of-order and stale writers,
partial discards, a full disk simulated by the write function, limits, the TTL sweep, leases with reused PIDs,
claims by two windows, slow and concurrent writers synchronised with a barrier, and the preferences.
"""
from hashlib import sha256
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from trama_qt import recovery_store as rs
from trama_qt.recovery_store import (Leases, RecoveryBusy, RecoveryDamaged, RecoveryLimitError, RecoveryStore,
                                     durable_write)

KEY_A, KEY_B, KEY_C = "a" * 32, "b" * 32, "c" * 32
OWNER_1, OWNER_2 = "1" * 32, "2" * 32
FIXTURES = Path(__file__).resolve().parent / "data" / "qt_recovery"


def alab(value):
    return json.dumps({"version": 2, "tables": [{"title": "T", "rows": [[value]]}], "layouts": []}).encode()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "profile" / "recovery"

    def tearDown(self):
        self.folder.cleanup()

    def store(self, **options):
        return RecoveryStore(self.root, **options)

    def files(self):
        return sorted(path.name for path in self.root.iterdir()) if self.root.exists() else []

    def test_fixtures_round_trip_with_metadata(self):
        saved = (FIXTURES / "misure-salvate.alab").read_bytes()
        store = self.store(owner=OWNER_1, clock=lambda: 1700000000.5)
        record = store.write_snapshot(KEY_A, 3, saved, title="Calibrazione $ <β>", source="C:/dati/misure.alab",
                                      source_stamp=[10, 20])
        self.assertEqual(record["sha256"], sha256(saved).hexdigest())
        again = self.store().list_snapshots()
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["owner"], OWNER_1)
        self.assertEqual(again[0]["written"], 1700000000.5)
        self.assertEqual(again[0]["source_stamp"], [10, 20])
        self.assertEqual(self.store().read_snapshot(KEY_A), saved)
        # Neither the title nor the source becomes a file name.
        self.assertEqual(self.files(), [f"{KEY_A}.3.alab", f"{KEY_A}.json"])

    def test_crash_between_payload_and_reference_keeps_previous(self):
        store = self.store()
        store.write_snapshot(KEY_A, 1, alab(1), title="P")
        calls = []

        def fail_on_reference(path, data):
            calls.append(path)
            if len(calls) == 2:  # The payload went through; the reference write dies.
                raise OSError(errno.EIO, "power cut")
            durable_write(path, data)

        broken = self.store(write_bytes=fail_on_reference)
        with self.assertRaises(OSError):
            broken.write_snapshot(KEY_A, 2, alab(2), title="P")
        self.assertEqual(self.store().read_snapshot(KEY_A), alab(1))
        self.assertEqual(self.files(), [f"{KEY_A}.1.alab", f"{KEY_A}.json"])  # No temporary or orphan left.

    def test_crash_left_orphan_payload_is_not_recoverable_and_swept(self):
        store = self.store()
        store.write_snapshot(KEY_A, 1, alab(1), title="P")
        orphan = self.root / f"{KEY_A}.2.alab"  # As left by a process killed between the two steps.
        orphan.write_bytes(alab(2))
        temporary = self.root / f".tmp-{OWNER_2}-x"
        temporary.write_bytes(b"{half")
        self.assertEqual(store.read_snapshot(KEY_A), alab(1))
        self.assertEqual(store.sweep(alive=lambda owner: True, now=os.stat(orphan).st_mtime + 10), [])
        removed = store.sweep(alive=lambda owner: False, now=os.stat(orphan).st_mtime + 60)
        self.assertEqual(removed, [temporary.name])  # Its writer is gone; the orphan payload waits for the TTL.
        removed = store.sweep(alive=lambda owner: False, now=os.stat(orphan).st_mtime + rs.TEMP_TTL + 1)
        self.assertEqual(removed, [orphan.name])
        self.assertEqual(store.read_snapshot(KEY_A), alab(1))  # The valid copy is never swept.

    def test_temporary_of_live_writer_survives_until_ttl(self):
        store = self.store(owner=OWNER_1)
        self.root.mkdir(parents=True)
        mine = self.root / f".tmp-{OWNER_1}-x"
        other = self.root / f".tmp-{OWNER_2}-y"
        for path in (mine, other):
            path.write_bytes(b"{")
        now = os.stat(mine).st_mtime + 120
        self.assertEqual(store.sweep(alive=lambda owner: owner == OWNER_2, now=now), [])
        self.assertEqual(sorted(store.sweep(alive=lambda owner: True, now=now + rs.TEMP_TTL)),
                         sorted([mine.name, other.name]))

    def test_altered_checksum_or_size_is_isolated(self):
        store = self.store()
        store.write_snapshot(KEY_A, 1, alab(1), title="A")
        store.write_snapshot(KEY_B, 1, alab(2), title="B")
        reference = self.root / f"{KEY_A}.json"
        record = json.loads(reference.read_text(encoding="utf-8"))
        record["sha256"] = "0" * 64
        reference.write_text(json.dumps(record), encoding="utf-8")
        snapshots, problems = store.scan()
        self.assertEqual([item["session_key"] for item in snapshots], [KEY_B])
        self.assertEqual([item["session_key"] for item in problems], [KEY_A])
        with self.assertRaises(RecoveryDamaged):
            store.read_snapshot(KEY_A)
        (self.root / f"{KEY_B}.1.alab").write_bytes(alab(2) + b" ")
        self.assertEqual(store.list_snapshots(), [])
        self.assertIn("size", store.problems()[1]["reason"])
        # A good copy of the same project replaces the damaged one.
        store.write_snapshot(KEY_A, 2, alab(3), title="A")
        self.assertEqual(store.read_snapshot(KEY_A), alab(3))

    def test_damaged_reference_and_missing_payload(self):
        store = self.store()
        store.write_snapshot(KEY_A, 1, alab(1), title="A")
        store.write_snapshot(KEY_B, 1, alab(2), title="B")
        store.write_snapshot(KEY_C, 1, alab(3), title="C")
        (self.root / f"{KEY_A}.json").write_text("{not json", encoding="utf-8")
        (self.root / f"{KEY_B}.1.alab").unlink()
        snapshots, problems = store.scan()
        self.assertEqual([item["session_key"] for item in snapshots], [KEY_C])
        self.assertEqual({item["session_key"] for item in problems}, {KEY_A, KEY_B})
        store.discard(KEY_A)
        store.discard(KEY_B)
        self.assertEqual(store.problems(), [])
        self.assertEqual(self.files(), [f"{KEY_C}.1.alab", f"{KEY_C}.json"])

    def test_out_of_order_and_malformed_writes_keep_last_valid(self):
        store = self.store()
        store.write_snapshot(KEY_A, 5, alab(5), title="A")
        for generation in (5, 4, 1):
            with self.assertRaises(ValueError):
                store.write_snapshot(KEY_A, generation, alab(generation), title="A")
        for call in (lambda: store.write_snapshot(KEY_A, True, alab(9), title="A"),
                     lambda: store.write_snapshot(KEY_A, 6, "text", title="A"),
                     lambda: store.write_snapshot(KEY_A, 6, b"PK\x03\x04", title="A"),
                     lambda: store.write_snapshot(KEY_A, 6, alab(6), title=""),
                     lambda: store.write_snapshot(KEY_A, 6, alab(6), title="A", source=Path("x")),
                     lambda: store.write_snapshot("A" * 32, 6, alab(6), title="A")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(store.read_snapshot(KEY_A), alab(5))
        self.assertEqual(store.record(KEY_A)["generation"], 5)

    def test_limited_discard_and_stale_writer_after_save(self):
        store = self.store()
        store.write_snapshot(KEY_A, 1, alab(1), title="A")
        store.write_snapshot(KEY_A, 2, alab(2), title="A")
        store.discard(KEY_A, through_generation=1)  # A save that covered generation 1 only.
        self.assertEqual(store.read_snapshot(KEY_A), alab(2))
        store.discard(KEY_A, through_generation=3)  # A save that covered everything up to 3.
        with self.assertRaises(FileNotFoundError):
            store.read_snapshot(KEY_A)
        with self.assertRaises(ValueError):  # A serialisation of generation 3 arriving late.
            store.write_snapshot(KEY_A, 3, alab(3), title="A")
        store.write_snapshot(KEY_A, 4, alab(4), title="A")  # Changes after the save are protected again.
        self.assertEqual(store.read_snapshot(KEY_A), alab(4))
        store.discard(KEY_A)
        store.discard(KEY_A)  # Idempotent.
        with self.assertRaises(ValueError):  # Discarded entirely: nothing brings it back.
            store.write_snapshot(KEY_A, 9, alab(9), title="A")
        self.assertEqual(self.files(), [])

    def test_disk_full_and_read_only_folder_keep_previous(self):
        store = self.store()
        store.write_snapshot(KEY_A, 1, alab(1), title="A")

        def full(_path, _data):
            raise OSError(errno.ENOSPC, "No space left on device")

        with self.assertRaises(OSError) as raised:
            self.store(write_bytes=full).write_snapshot(KEY_A, 2, alab(2), title="A")
        self.assertEqual(raised.exception.errno, errno.ENOSPC)
        self.assertEqual(store.read_snapshot(KEY_A), alab(1))
        self.assertEqual(self.files(), [f"{KEY_A}.1.alab", f"{KEY_A}.json"])
        if os.name == "posix" and os.geteuid() != 0:
            os.chmod(self.root, 0o500)
            try:
                with self.assertRaises(OSError):
                    store.write_snapshot(KEY_A, 2, alab(2), title="A")
            finally:
                os.chmod(self.root, 0o700)
            self.assertEqual(store.read_snapshot(KEY_A), alab(1))

    def test_limits_refuse_without_deleting(self):
        store = self.store()
        with mock.patch.object(rs, "MAX_COPIES", 2):
            store.write_snapshot(KEY_A, 1, alab(1), title="A")
            store.write_snapshot(KEY_B, 1, alab(2), title="B")
            with self.assertRaises(RecoveryLimitError) as raised:
                store.write_snapshot(KEY_C, 1, alab(3), title="C")
            self.assertEqual(raised.exception.reason, "copies")
            store.write_snapshot(KEY_A, 2, alab(4), title="A")  # Replacing an existing copy is still allowed.
        with mock.patch.object(rs, "MAX_TOTAL_BYTES", 900):
            with self.assertRaises(RecoveryLimitError) as raised:
                store.write_snapshot(KEY_C, 1, b"{" + b" " * 800 + b"}", title="C")
            self.assertEqual(raised.exception.reason, "total")
        with mock.patch.object(rs, "MAX_SNAPSHOT_BYTES", 10):
            with self.assertRaises(RecoveryLimitError) as raised:
                store.write_snapshot(KEY_C, 1, alab(3), title="C")
            self.assertEqual(raised.exception.reason, "snapshot")
        self.assertEqual(len(store.list_snapshots()), 2)
        self.assertEqual(store.usage()["copies"], 2)

    def test_profile_boundary(self):
        store = self.store()
        outside = Path(self.folder.name) / "original.alab"
        outside.write_bytes(alab(0))
        before = sorted(Path(self.folder.name).rglob("*"))
        store.write_snapshot(KEY_A, 1, alab(1), title="../../escape", source=str(outside))
        after = sorted(Path(self.folder.name).rglob("*"))
        self.assertTrue(all(path in before or self.root in path.parents or path == self.root.parent
                            or path == self.root for path in after))
        self.assertEqual(outside.read_bytes(), alab(0))
        for bad in ("../" + "a" * 29, "a" * 31, "a" * 33):
            with self.assertRaises(ValueError):
                store.read_snapshot(bad)
            with self.assertRaises(ValueError):
                store.discard(bad)

    def test_slow_concurrent_writers_keep_order(self):
        """Two threads write generations 1 and 2 of one key while the disk is slow: whichever commits last, the
        store ends with generation 2 and never goes back to 1."""
        store = self.store()
        barrier = threading.Barrier(2)
        gate = threading.Event()

        def slow(path, data):
            if path.name.startswith(".tmp-") and b'"rows": [[1]]' in data:
                gate.wait(5)  # Generation 1 is stuck on the disk until generation 2 has been committed.
            durable_write(path, data)

        slow_store = self.store(write_bytes=slow)
        outcomes = {}

        def writer(generation):
            barrier.wait(5)
            try:
                slow_store.write_snapshot(KEY_A, generation, alab(generation), title="A")
                outcomes[generation] = "ok"
            except ValueError:
                outcomes[generation] = "stale"
            finally:
                gate.set()

        threads = [threading.Thread(target=writer, args=(generation,)) for generation in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(store.read_snapshot(KEY_A), alab(2))
        self.assertEqual(store.record(KEY_A)["generation"], 2)
        self.assertIn(outcomes.get(1), {"ok", "stale"})
        self.assertEqual(outcomes.get(2), "ok")

    def test_claim_is_exclusive(self):
        RecoveryStore(self.root, owner=OWNER_1).write_snapshot(KEY_A, 1, alab(1), title="A")
        first = RecoveryStore(self.root, owner=OWNER_2)
        second = RecoveryStore(self.root, owner="3" * 32)
        self.assertEqual(first.claim(KEY_A, expected_owner=OWNER_1)["owner"], OWNER_2)
        with self.assertRaises(RecoveryBusy):
            second.claim(KEY_A, expected_owner=OWNER_1)
        (self.root / f"{KEY_A}.lock").write_text("x")
        with self.assertRaises(RecoveryBusy):
            second.claim(KEY_A, expected_owner=OWNER_2)
        old = os.stat(self.root / f"{KEY_A}.lock").st_mtime - rs.LOCK_TTL - 5
        os.utime(self.root / f"{KEY_A}.lock", (old, old))
        self.assertEqual(second.claim(KEY_A, expected_owner=OWNER_2)["owner"], "3" * 32)
        self.assertEqual(second.read_snapshot(KEY_A), alab(1))
        self.assertFalse((self.root / f"{KEY_A}.lock").exists())

    def test_usage_and_order(self):
        clock = iter([10.0, 30.0, 20.0])
        store = self.store(clock=lambda: next(clock))
        store.write_snapshot(KEY_A, 1, alab(1), title="Same")
        store.write_snapshot(KEY_B, 1, alab(2), title="Same")
        store.write_snapshot(KEY_C, 1, alab(3), title="Same")
        self.assertEqual([item["session_key"] for item in store.list_snapshots()], [KEY_B, KEY_C, KEY_A])
        self.assertEqual(store.usage()["copies"], 3)


class SnapshotBytesTests(unittest.TestCase):
    def test_snapshot_bytes_equal_save(self):
        """Recovery copies are serialised in batches; the bytes are those Save writes."""
        import pandas as pd
        from trama_qt.project import Project
        project = Project()
        project.load(FIXTURES / "misure-salvate.alab")
        frame = pd.DataFrame({"Testo": ["a\u0000b", "β \"quoted\"", None, "x" * 3] * 150,
                              "Numero": pd.array([1.5, None, -2.0, 1e300] * 150, dtype="Float64")})
        project.add_tables({"Misto $ <β>": frame, "Vuoto": frame.iloc[:0]})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "saved.alab"
            snapshot = project.snapshot()
            project.save(path)
            for batch in (1, 7, 256, 10_000):
                self.assertEqual(snapshot.to_bytes(batch), path.read_bytes())


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.now = [1000.0]

    def tearDown(self):
        self.folder.cleanup()

    def leases(self):
        return Leases(self.root, clock=lambda: self.now[0])

    def test_heartbeat_and_release(self):
        leases = self.leases()
        owner = Leases.new_owner()
        self.assertFalse(leases.alive(owner))
        leases.hold(owner)
        self.assertTrue(leases.alive(owner))
        self.now[0] += rs.LEASE_TTL - 1
        self.assertTrue(leases.alive(owner))
        self.now[0] += 2
        self.assertFalse(leases.alive(owner))  # Not renewed: the window is gone.
        leases.hold(owner)
        self.assertTrue(leases.alive(owner))
        leases.release(owner)
        self.assertFalse(leases.alive(owner))
        self.assertFalse(leases.alive(None))
        self.assertFalse(leases.alive("../x"))

    def test_dead_pid_and_reused_pid(self):
        leases = self.leases()
        owner = Leases.new_owner()
        leases.hold(owner)
        path = leases.folder / f"{owner}.lease"
        lease = json.loads(path.read_text())
        lease["pid"] = 2 ** 22 + 12345  # No such process on this computer: the window crashed.
        path.write_text(json.dumps(lease))
        with mock.patch.object(rs, "process_running", return_value=False):
            self.assertFalse(leases.alive(owner))
        # The PID now belongs to another program: the heartbeat decides once it is old enough.
        with mock.patch.object(rs, "process_running", return_value=True):
            self.assertTrue(leases.alive(owner))
            self.now[0] += rs.LEASE_TTL + 1
            self.assertFalse(leases.alive(owner))
        leases.sweep()
        self.assertFalse(path.exists())

    def test_other_host_trusts_heartbeat(self):
        leases = self.leases()
        owner = Leases.new_owner()
        leases.hold(owner)
        path = leases.folder / f"{owner}.lease"
        lease = json.loads(path.read_text())
        lease["host"], lease["pid"] = "another-pc", 1
        path.write_text(json.dumps(lease))
        with mock.patch.object(rs, "process_running", return_value=False):
            self.assertTrue(leases.alive(owner))

    def test_process_running_self(self):
        self.assertTrue(rs.process_running(os.getpid()))
        self.assertFalse(rs.process_running(0))


class SettingsTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tramastat" / "preferences.json"
            self.assertEqual(rs.load_settings(path), (True, 30))
            path.parent.mkdir()
            path.write_text(json.dumps({"language": "it"}), encoding="utf-8")
            rs.save_settings(path, False, 120)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data, {"language": "it", "recovery": {"enabled": False, "interval": 120}})
            self.assertEqual(rs.load_settings(path), (False, 120))
            with self.assertRaises(ValueError):
                rs.save_settings(path, True, 45)
            path.write_text(json.dumps({"recovery": {"interval": 45}}), encoding="utf-8")
            self.assertEqual(rs.load_settings(path), (True, 30))

    def test_original_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "p.alab"
            self.assertEqual(rs.original_state(None, None), "none")
            self.assertEqual(rs.original_state(str(path), [1, 2]), "missing")
            path.write_bytes(b"{}")
            stamp = rs.source_stamp(path)
            self.assertEqual(rs.original_state(str(path), stamp), "unchanged")
            self.assertEqual(rs.original_state(str(path), None), "unknown")
            path.write_bytes(b"{1}")
            self.assertEqual(rs.original_state(str(path), stamp), "changed")


if __name__ == "__main__":
    unittest.main()
