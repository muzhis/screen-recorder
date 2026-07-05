from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from screen_recorder.utils.config import AppConfig


class FFmpegVideoEncoder:
    def __init__(self, config: AppConfig):
        self.config = config
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        ffmpeg = find_ffmpeg(self.config)
        region = self.config.region
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            f"{region.width}x{region.height}",
            "-r",
            str(self.config.fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            str(self.config.temp_video_path),
        ]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **_windows_no_window_kwargs(),
        )

    def write_frame(self, frame: bytes) -> None:
        if not self._process or not self._process.stdin:
            return
        try:
            self._process.stdin.write(frame)
        except BrokenPipeError as exc:
            raise RuntimeError("ffmpeg 视频编码进程已退出。") from exc

    def stop(self) -> None:
        if not self._process:
            return
        if self._process.stdin:
            self._process.stdin.close()
        _, stderr = self._process.communicate()
        if self._process.returncode not in (0, None):
            message = stderr.decode("utf-8", errors="ignore") if stderr else ""
            raise RuntimeError(f"ffmpeg 视频编码失败：{message}")
        self._process = None


def mux_video_and_audio(config: AppConfig) -> None:
    ffmpeg = find_ffmpeg(config)
    inputs: list[str] = ["-i", str(config.temp_video_path)]
    audio_paths = [path for path in (config.mic_wav_path, config.system_wav_path) if path.exists()]

    for path in audio_paths:
        inputs.extend(["-i", str(path)])

    command = [ffmpeg, "-y", "-loglevel", "error", *inputs]
    if len(audio_paths) == 0:
        command.extend(["-c:v", "copy", str(config.output_path)])
    elif len(audio_paths) == 1:
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(config.output_path),
            ]
        )
    else:
        command.extend(
            [
                "-filter_complex",
                "amix=inputs=2:duration=longest:dropout_transition=0[aout]",
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(config.output_path),
            ]
        )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        **_windows_no_window_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 合成失败：{result.stderr}")


def find_ffmpeg(config: AppConfig) -> str:
    candidates = [
        config.ffmpeg_path,
        Path(sys.executable).resolve().parent / "ffmpeg.exe",
        Path.cwd() / "ffmpeg.exe",
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / "screen_recorder" / "resources" / "ffmpeg.exe")
        candidates.insert(0, Path(sys._MEIPASS) / "ffmpeg.exe")

    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 1024:
            return str(candidate)

    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        return path_ffmpeg

    raise FileNotFoundError(
        "没有找到 ffmpeg。请执行 `conda install -c conda-forge ffmpeg -y`，"
        "或把 ffmpeg.exe 放到 screen_recorder/resources/ffmpeg.exe。"
    )


def _windows_no_window_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}
