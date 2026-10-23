from __future__ import annotations

import sys
import time
from contextlib import nullcontext
from typing import Callable

import mss

from screen_recorder.recorder.cursor import WindowsCursorOverlay
from screen_recorder.utils.config import AppConfig


class ScreenRecorder:
    def __init__(self, config: AppConfig, frame_writer: Callable[[bytes], None]):
        self.config = config
        self.frame_writer = frame_writer
        self._stopped = False

    def record_until_stopped(self, should_stop: Callable[[], bool]) -> None:
        region = self.config.region
        monitor = {
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        }
        frame_interval = 1.0 / self.config.fps
        next_frame_at = time.perf_counter()

        with mss.mss(with_cursor=sys.platform != "win32") as sct, (
            WindowsCursorOverlay(region) if sys.platform == "win32" else nullcontext()
        ) as cursor:
            while not should_stop() and not self._stopped:
                image = sct.grab(monitor)
                frame = image.bgra
                if cursor is not None:
                    frame = cursor.render(frame)
                self.frame_writer(frame)

                next_frame_at += frame_interval
                sleep_for = next_frame_at - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_frame_at = time.perf_counter()

    def stop(self) -> None:
        self._stopped = True

