"""Send one embedded figure to a new document in a local Windows Office application."""
from contextlib import contextmanager, suppress
import ctypes
import sys

from .strings import qt

ON_WINDOWS = sys.platform == "win32"


class OfficeError(RuntimeError):
    pass


def fit_picture(image_size, available_size):
    """Fit width and height in points without changing the image's proportions."""
    width, height = image_size
    available_width, available_height = available_size
    scale = min(available_width / width, available_height / height)
    return width * scale, height * scale


def _word(application, path, title, size):
    document = application.Documents.Add()
    try:
        setup = document.PageSetup
        width = setup.PageWidth - setup.LeftMargin - setup.RightMargin
        height = setup.PageHeight - setup.TopMargin - setup.BottomMargin - 18  # Space for the inline paragraph.
        picture = document.InlineShapes.AddPicture(str(path), False, True, document.Range(0, 0))
        picture.LockAspectRatio = 0
        picture.Width, picture.Height = fit_picture(size, (width, height))
        picture.LockAspectRatio = -1
        picture.AlternativeText = title
        picture.Range.ParagraphFormat.Alignment = 1  # wdAlignParagraphCenter
        application.Visible = True
        document.Activate()
    except Exception:
        with suppress(Exception):
            document.Close(0)  # wdDoNotSaveChanges
        raise


def _powerpoint(application, path, title, size):
    presentation = application.Presentations.Add(-1)  # msoTrue: open a visible presentation window.
    try:
        setup = presentation.PageSetup
        slide_width, slide_height = setup.SlideWidth, setup.SlideHeight
        width, height = fit_picture(size, (slide_width - 48, slide_height - 48))
        slide = presentation.Slides.Add(1, 12)  # ppLayoutBlank
        left, top = (slide_width - width) / 2, (slide_height - height) / 2
        picture = slide.Shapes.AddPicture(str(path), 0, -1, left, top, width, height)
        picture.LockAspectRatio = -1
        picture.AlternativeText = title
    except Exception:
        with suppress(Exception):
            presentation.Saved = -1
            presentation.Close()
        raise


_DESTINATIONS = {"Word": _word, "PowerPoint": _powerpoint}


@contextmanager
def _office_apartment():
    """Balance this command's COM reference without closing the GUI thread's apartment."""
    ole = ctypes.WinDLL("ole32")
    initialize = ole.CoInitializeEx
    initialize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    initialize.restype = ctypes.c_long
    status = initialize(None, 2)  # COINIT_APARTMENTTHREADED
    initialized = status in (0, 1)  # Both S_OK and S_FALSE acquire a reference.
    if not initialized and status & 0xFFFFFFFF != 0x80010106:  # RPC_E_CHANGED_MODE: already initialized.
        raise OfficeError(qt("qt.office_com_initialization", code=f"0x{status & 0xFFFFFFFF:08X}"))
    try:
        yield
    finally:
        if initialized:
            ole.CoUninitialize.restype = None
            ole.CoUninitialize()


def send_picture(app_name, path, title, size):
    """Start the desktop application on demand and leave the new unsaved document open."""
    insert = _DESTINATIONS[app_name]
    if not ON_WINDOWS:
        raise OfficeError(qt("qt.office_windows", app=app_name))
    try:
        from pywintypes import com_error
        from win32com.client.dynamic import Dispatch
    except (ImportError, OSError) as error:
        raise OfficeError(qt("qt.office_automation_missing")) from error

    with _office_apartment():
        try:
            application = Dispatch(f"{app_name}.Application")
        except com_error as error:
            raise OfficeError(qt("qt.office_unavailable", app=app_name)) from error
        try:
            insert(application, path, title, size)
        except com_error as error:
            raise OfficeError(qt("qt.office_insert_failed", app=app_name, error=error.strerror)) from error
        finally:
            del application
