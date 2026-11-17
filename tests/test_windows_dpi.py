"""Startup must opt in before Tk; the portable declares the same DPI context."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from analisi import windows_dpi

ROOT = Path(__file__).resolve().parents[1]


class WindowsDpiTests(unittest.TestCase):
    def test_main_opts_in_before_first_window(self):
        tree = ast.parse((ROOT/"tramastat.py").read_text(encoding="utf-8"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
        opt = next((n.lineno for n in calls if isinstance(n.func, ast.Name) and n.func.id == "configure_native_dpi"), None)
        tk = next(n.lineno for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "Tk")
        self.assertIsNotNone(opt)
        self.assertLess(opt, tk)

    def test_manifest_requests_native_per_monitor_without_admin(self):
        root = ET.parse(ROOT/"assets/trama.manifest").getroot()
        values = {n.tag.split("}")[-1]: n for n in root.iter()}
        self.assertIn("PerMonitorV2", values["dpiAwareness"].text)
        self.assertEqual(values["requestedExecutionLevel"].get("level"), "asInvoker")

    def test_non_windows_has_no_native_side_effect(self):
        with patch.object(windows_dpi.sys, "platform", "linux"), patch.object(windows_dpi.ctypes, "WinDLL", create=True) as load:
            self.assertEqual(windows_dpi.configure_native_dpi(), "not-windows")
            load.assert_not_called()

    def test_manifest_or_host_context_falls_back_to_gui_thread(self):
        process, thread = Mock(return_value=False), Mock(return_value=123)
        lib = SimpleNamespace(SetProcessDpiAwarenessContext=process, SetThreadDpiAwarenessContext=thread)
        with patch.object(windows_dpi.sys, "platform", "win32"), patch.object(windows_dpi.ctypes, "WinDLL", return_value=lib, create=True):
            self.assertEqual(windows_dpi.configure_native_dpi(), "thread-per-monitor-v2")
        process.assert_called_once()
        thread.assert_called_once()
