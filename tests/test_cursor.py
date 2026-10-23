import ctypes
import sys
import unittest
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import patch

from screen_recorder.recorder.cursor import CURSORINFO, WindowsCursorOverlay
from screen_recorder.recorder.screen import ScreenRecorder
from screen_recorder.utils.config import AppConfig, RecordingRegion


@unittest.skipUnless(sys.platform == "win32", "Requires Windows GDI")
class CursorOverlayTests(unittest.TestCase):
    def setUp(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        self.user32.LoadCursorW.restype = wintypes.HANDLE

    def render(self, region, position, cursor_id=32512, flags=1):
        frame = bytes([90, 120, 150, 255]) * region.width * region.height
        with WindowsCursorOverlay(region) as overlay:
            def get_cursor(pointer):
                info = ctypes.cast(pointer, ctypes.POINTER(CURSORINFO)).contents
                info.flags = flags
                info.hCursor = self.user32.LoadCursorW(None, cursor_id)
                self.assertTrue(info.hCursor)
                info.ptScreenPos = wintypes.POINT(*position)
                return 1

            with patch.object(overlay._user32, "GetCursorInfo", get_cursor):
                result = overlay.render(frame)
        return frame, result

    def test_arrow_and_text_cursor_change_pixels(self):
        for cursor_id in (32512, 32513):
            with self.subTest(cursor_id=cursor_id):
                frame, result = self.render(RecordingRegion(0, 0, 96, 96), (48, 48), cursor_id)
                self.assertEqual(len(frame), len(result))
                self.assertNotEqual(frame, result)
                # Unrelated pixels and image orientation must remain intact.
                self.assertEqual(frame[:96 * 4], result[:96 * 4])

    def test_capture_origin_including_negative_monitor_coordinates(self):
        _, expected = self.render(RecordingRegion(0, 0, 96, 96), (48, 48), 32513)
        for left, top in ((200, 100), (-1200, -300)):
            with self.subTest(left=left, top=top):
                _, result = self.render(
                    RecordingRegion(left, top, 96, 96), (left + 48, top + 48), 32513
                )
                self.assertEqual(expected, result)

    def test_edges_clip_cursor_instead_of_moving_its_hotspot(self):
        _, large = self.render(RecordingRegion(-32, -32, 160, 160), (0, 0), 32513)
        _, small = self.render(RecordingRegion(0, 0, 96, 96), (0, 0), 32513)
        expected = b"".join(
            large[((row + 32) * 160 + 32) * 4:((row + 32) * 160 + 128) * 4]
            for row in range(96)
        )
        self.assertEqual(expected, small)

    def test_hidden_suppressed_and_outside_cursor_leave_frame_unchanged(self):
        for position, flags in (((48, 48), 0), ((48, 48), 2), ((-500, -500), 1)):
            with self.subTest(position=position, flags=flags):
                frame, result = self.render(RecordingRegion(0, 0, 96, 96), position, flags=flags)
                self.assertEqual(frame, result)

    def test_repeated_frames_release_gdi_handles(self):
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self.user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.user32.GetGuiResources.restype = wintypes.DWORD
        process = kernel32.GetCurrentProcess()
        self.render(RecordingRegion(0, 0, 96, 96), (48, 48))
        before = self.user32.GetGuiResources(process, 0)
        for _ in range(100):
            self.render(RecordingRegion(0, 0, 96, 96), (48, 48))
        self.assertLessEqual(self.user32.GetGuiResources(process, 0), before + 2)

    def test_capture_sends_composited_frame_and_closes_overlay(self):
        config = AppConfig.default()
        config.region = RecordingRegion(0, 0, 8, 8)
        frames = []
        with patch("screen_recorder.recorder.screen.mss.mss") as capture, patch(
            "screen_recorder.recorder.screen.WindowsCursorOverlay"
        ) as cursor:
            capture.return_value.__enter__.return_value.grab.return_value = SimpleNamespace(bgra=b"raw")
            cursor.return_value.__enter__.return_value.render.return_value = b"with-cursor"
            ScreenRecorder(config, frames.append).record_until_stopped(lambda: bool(frames))
            self.assertEqual(frames, [b"with-cursor"])
            cursor.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
