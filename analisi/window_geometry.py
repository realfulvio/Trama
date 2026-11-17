"""Keep native decorated dialogs inside their monitor's usable work area."""
import sys


def clamp_rect(rect, work):
    """Return the closest visible origin without resizing an outer rectangle."""
    left, top, right, bottom = rect
    x0, y0, x1, y1 = work
    return (max(x0, min(left, x1 - (right - left))),
            max(y0, min(top, y1 - (bottom - top))))


def keep_native_window_on_screen(window):
    """Handle Windows frame/work-area coordinates; return False for Tk fallback."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    hwnd = int(window.wm_frame(), 0)
    rect = wintypes.RECT()
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    monitor = user32.MonitorFromWindow(hwnd, 2)  # Nearest monitor, including secondary displays.
    if not monitor or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    work = info.rcWork
    x, y = clamp_rect((rect.left, rect.top, rect.right, rect.bottom),
                      (work.left, work.top, work.right, work.bottom))
    if (x, y) == (rect.left, rect.top):
        return True
    # Preserve size, Z order and activation; native coordinates support negative monitors.
    return bool(user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x15))
