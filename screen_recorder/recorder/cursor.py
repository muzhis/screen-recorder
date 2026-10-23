from __future__ import annotations

import ctypes
from ctypes import wintypes

from screen_recorder.utils.config import RecordingRegion


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", wintypes.POINT),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]


class WindowsCursorOverlay:
    """Composite the native cursor onto a BGRA frame on the capture thread."""

    def __init__(self, region: RecordingRegion):
        self.region = region
        self._size = region.width * region.height * 4
        self._dc = None
        self._bitmap = None
        self._old_bitmap = None
        self._bits = ctypes.c_void_p()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._bind_functions()

        try:
            self._dc = self._gdi32.CreateCompatibleDC(None)
            if not self._dc:
                raise ctypes.WinError(ctypes.get_last_error())
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = region.width
            # Match mss: top-down, uncompressed, four bytes per pixel.
            info.bmiHeader.biHeight = -region.height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            self._bitmap = self._gdi32.CreateDIBSection(
                self._dc, ctypes.byref(info), 0, ctypes.byref(self._bits), None, 0
            )
            if not self._bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            self._old_bitmap = self._gdi32.SelectObject(self._dc, self._bitmap)
            if not self._old_bitmap or self._old_bitmap == ctypes.c_void_p(-1).value:
                self._old_bitmap = None
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close()
            raise

    def _bind_functions(self) -> None:
        signatures = [
            (self._user32, "GetCursorInfo", [ctypes.POINTER(CURSORINFO)], wintypes.BOOL),
            (self._user32, "CopyIcon", [wintypes.HANDLE], wintypes.HANDLE),
            (self._user32, "GetIconInfo", [wintypes.HANDLE, ctypes.POINTER(ICONINFO)], wintypes.BOOL),
            (self._user32, "DestroyIcon", [wintypes.HANDLE], wintypes.BOOL),
            (self._user32, "DrawIconEx", [wintypes.HDC, ctypes.c_int, ctypes.c_int,
             wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.UINT,
             wintypes.HBRUSH, wintypes.UINT], wintypes.BOOL),
            (self._gdi32, "CreateCompatibleDC", [wintypes.HDC], wintypes.HDC),
            (self._gdi32, "CreateDIBSection", [wintypes.HDC, ctypes.POINTER(BITMAPINFO),
             wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
             wintypes.DWORD], wintypes.HBITMAP),
            (self._gdi32, "SelectObject", [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
            (self._gdi32, "DeleteObject", [wintypes.HANDLE], wintypes.BOOL),
            (self._gdi32, "DeleteDC", [wintypes.HDC], wintypes.BOOL),
            (self._gdi32, "GdiFlush", [], wintypes.BOOL),
        ]
        for library, name, args, result in signatures:
            function = getattr(library, name)
            function.argtypes = args
            function.restype = result

    def render(self, frame: bytes) -> bytes:
        if not self._dc:
            raise RuntimeError("Cursor overlay is closed.")
        if len(frame) != self._size:
            raise ValueError("BGRA frame dimensions do not match the capture region.")
        cursor = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
        if not self._user32.GetCursorInfo(ctypes.byref(cursor)) or cursor.flags != 1:
            return frame

        # Own the handle while drawing, in case the desktop cursor changes.
        icon = self._user32.CopyIcon(cursor.hCursor)
        if not icon:
            return frame
        info = ICONINFO()
        try:
            if not self._user32.GetIconInfo(icon, ctypes.byref(info)):
                return frame
            x = cursor.ptScreenPos.x - self.region.left - info.xHotspot
            y = cursor.ptScreenPos.y - self.region.top - info.yHotspot
            ctypes.memmove(self._bits, frame, self._size)
            # GDI clips to the region and handles alpha and monochrome XOR cursors.
            if not self._user32.DrawIconEx(self._dc, x, y, icon, 0, 0, 0, None, 3):
                raise ctypes.WinError(ctypes.get_last_error())
            self._gdi32.GdiFlush()
            return ctypes.string_at(self._bits, self._size)
        finally:
            for bitmap in (info.hbmMask, info.hbmColor):
                if bitmap:
                    self._gdi32.DeleteObject(bitmap)
            self._user32.DestroyIcon(icon)

    def close(self) -> None:
        if self._old_bitmap:
            self._gdi32.SelectObject(self._dc, self._old_bitmap)
            self._old_bitmap = None
        if self._bitmap:
            self._gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        if self._dc:
            self._gdi32.DeleteDC(self._dc)
            self._dc = None

    def __enter__(self) -> "WindowsCursorOverlay":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
