"""Opt in before creating Tk windows, so fonts and geometry see native DPI."""
import ctypes
import sys


def configure_native_dpi():
    if sys.platform != "win32":
        return "not-windows"
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        process = user32.SetProcessDpiAwarenessContext
        process.argtypes = [ctypes.c_void_p]
        process.restype = ctypes.c_bool
        if process(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
        # An executable manifest or an embedding host may have set the process
        # context already. Set the GUI thread before its first Tk window.
        thread = user32.SetThreadDpiAwarenessContext
        thread.argtypes = [ctypes.c_void_p]
        thread.restype = ctypes.c_void_p
        if thread(ctypes.c_void_p(-4)):
            return "thread-per-monitor-v2"
    except AttributeError:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        process = shcore.SetProcessDpiAwareness
        process.argtypes = [ctypes.c_int]
        process.restype = ctypes.c_long
        if process(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    return "existing-context"


def window_dpi(window):
    """Read native HWND DPI/context, without changing it, for acceptance logs."""
    if sys.platform != "win32":
        return {}
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        dpi = user32.GetDpiForWindow
        dpi.argtypes, dpi.restype = [ctypes.c_void_p], ctypes.c_uint
        context = user32.GetWindowDpiAwarenessContext
        context.argtypes, context.restype = [ctypes.c_void_p], ctypes.c_void_p
        awareness = user32.GetAwarenessFromDpiAwarenessContext
        awareness.argtypes, awareness.restype = [ctypes.c_void_p], ctypes.c_int
        hwnd = int(window.wm_frame(), 0)
        return {"window_dpi": int(dpi(hwnd)), "awareness": int(awareness(context(hwnd)))}
    except AttributeError:
        return {}
