"""Smoke-driver boundary between Matplotlib device pixels and Windows logical input."""
import math
import os
import time


def screen_position(origin,height,rendered,ratio):
    if not math.isfinite(ratio) or ratio<=0:raise ValueError('Invalid canvas device pixel ratio.')
    x,y=rendered
    return round(origin[0]+x/ratio),round(origin[1]+height-y/ratio)


def focus_pointer_window(root,widget,pump):
    """Activate only our own visible test window before sending native drawing input.

    Windows can refuse programmatic foreground activation for a scheduled background task.
    In that case perform an ordinary OS click on a hit-tested title bar owned by this process.
    """
    from ctypes import byref,windll,POINTER
    from ctypes.wintypes import DWORD,POINT,RECT,HWND
    user=windll.user32
    user.WindowFromPoint.argtypes=[POINT];user.WindowFromPoint.restype=HWND
    user.GetForegroundWindow.restype=HWND
    user.GetWindowThreadProcessId.argtypes=[HWND,POINTER(DWORD)]
    user.SetForegroundWindow.argtypes=[HWND]
    handle=int(root.wm_frame(),0)
    def owner(handle):
        pid=DWORD();user.GetWindowThreadProcessId(handle,byref(pid));return pid.value
    root.deiconify();root.lift();root.focus_force();widget.focus_force();root.update()
    user.SetForegroundWindow(handle);pump(.1)
    if owner(user.GetForegroundWindow())!=os.getpid():
        topmost=root.attributes('-topmost');saved=POINT();user.GetCursorPos(byref(saved))
        try:
            root.attributes('-topmost',True);root.update()
            bounds=RECT();user.GetWindowRect(HWND(handle),byref(bounds))
            ratio=user.GetDpiForWindow(HWND(handle))/96
            point=POINT(round(bounds.left+100*ratio),round(bounds.top+20*ratio))
            if owner(user.WindowFromPoint(point))!=os.getpid():
                raise AssertionError('The pointer activation point is not owned by the test app.')
            user.SetCursorPos(point.x,point.y)
            user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0);pump(.2)
        finally:
            user.mouse_event(4,0,0,0,0)
            user.SetCursorPos(saved.x,saved.y);root.attributes('-topmost',topmost)
    widget.focus_force();pump(.1)
    pid=owner(user.GetForegroundWindow())
    if pid!=os.getpid():raise AssertionError('The native pointer test app is not in the foreground.')
    return pid
