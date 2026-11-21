"""Animated startup before the scientific stack loads; only stdlib and Tk.

The loading thread imports definitions, never creates Tk widgets. All window
creation, animation and application initialization stay on the main thread.
"""
import ctypes
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox


def _language():
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', Path.home()/'AppData/Roaming'))/'TramaStat'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'tramastat'
    try:
        with (base/'preferences.json').open(encoding='utf-8') as stream:
            content = stream.read(65537)
        if len(content) > 65536:
            return 'en'
        data = json.loads(content)
        return 'it' if isinstance(data, dict) and data.get('language') == 'it' else 'en'
    except (OSError, ValueError, UnicodeError):
        return 'en'


def _native_dpi():
    # This runs before importing analisi (whose public exports load NumPy).
    # The packaged executable already declares per-monitor awareness.
    if sys.platform == 'win32':
        try:
            ctypes.WinDLL('user32', use_last_error=True).SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass


class StartupScreen(tk.Toplevel):
    """A stationary branded panel with a smoothly rotating indeterminate ring."""
    def __init__(self, root, *, language='en'):
        super().__init__(root)
        self.title('Trama — Caricamento' if language == 'it' else 'Trama — Loading')
        self._closed = False
        self._job = None
        self._started = time.monotonic()
        self.withdraw()
        self.overrideredirect(True)
        self.configure(background='#dce8e7')
        scale = max(.75, min(3., root.winfo_fpixels('1i')/96))
        width = min(round(460*scale), self.winfo_screenwidth()-40)
        height = min(round(276*scale), self.winfo_screenheight()-40)
        self.geometry(f'{width}x{height}+{(self.winfo_screenwidth()-width)//2}+{(self.winfo_screenheight()-height)//2}')
        self.canvas = tk.Canvas(self, background='white', highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill='both', expand=True, padx=1, pady=1)
        try:
            logo = tk.PhotoImage(master=self, file=str(Path(__file__).resolve().parent/'assets/brand/trama-wordmark-light.png'))
            self.logo = logo.subsample(max(1, math.ceil(logo.width()/(width*.78))))
            self.canvas.create_image(width/2, height*.31, image=self.logo)
        except tk.TclError:
            self.canvas.create_text(width/2, height*.31, text='Trama', fill='#102d3a',
                                    font=('Segoe UI', 32, 'bold'))
        radius = 14*scale
        self._cx, self._cy, self._radius = width/2, height*.64, radius
        box = (self._cx-radius, self._cy-radius, self._cx+radius, self._cy+radius)
        self.canvas.create_oval(*box, outline='#e2efec', width=3*scale)
        self.arc = self.canvas.create_arc(*box, start=0, extent=95, style='arc', outline='#087e78', width=3*scale)
        self.message = tk.Label(self.canvas, text='Caricamento in corso…' if language == 'it' else 'Loading…',
                                background='white', foreground='#486075', font=('Segoe UI', 10))
        self.canvas.create_window(width/2, height*.83, window=self.message)
        self.deiconify()
        self.lift()
        self._tick()

    def _tick(self):
        if not self._closed:
            angle = -((time.monotonic()-self._started)*280)%360
            self.canvas.itemconfigure(self.arc, start=angle)
            self._job = self.after(30, self._tick)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._job is not None:
                self.after_cancel(self._job)
            self.destroy()
        except tk.TclError:
            pass  # The main window may already have been closed by its user.


def _load_app():
    # A literal import also lets PyInstaller collect the module automatically.
    import tramastat
    return tramastat


def launch():
    """Paint immediately; import in the background; hand off once, on main."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Trama startup must run on the main thread.')
    _native_dpi()
    language = _language()
    root = tk.Tk(); root.withdraw()
    screen = StartupScreen(root, language=language)
    loaded = Queue(maxsize=1)
    result = []
    def load():
        try:
            loaded.put((True, _load_app()))
        except BaseException as error:
            loaded.put((False, error))
    def poll():
        try:
            result.append(loaded.get_nowait())
        except Empty:
            root.after(20, poll)
            return
        root.quit()
    def dismiss():
        screen.close(); root.quit()
    screen.protocol('WM_DELETE_WINDOW', dismiss)
    thread = threading.Thread(target=load, name='Trama-startup', daemon=True)
    root.after(0, thread.start)
    root.after(20, poll)
    try:
        root.mainloop()
        if not result:
            return 0  # Closed during startup, before any project was opened.
        ok, app = result[0]
        if not ok:
            raise app
        app.main(root=root, on_ready=screen.close, standard_only=True)
        return 0
    except BaseException as error:
        screen.close()
        title = 'Avvio non riuscito' if language == 'it' else 'Unable to start'
        text = ('Trama non è riuscito ad avviarsi.' if language == 'it' else 'Trama could not start.')
        messagebox.showerror(title, f'{text}\n\n{type(error).__name__}: {error}', parent=root)
        return 1
    finally:
        screen.close()
        try:
            root.destroy()
        except tk.TclError:
            pass
