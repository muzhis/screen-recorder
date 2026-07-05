from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RecordingRegion:
    left: int
    top: int
    width: int
    height: int


@dataclass
class AppConfig:
    region: RecordingRegion
    fps: int
    audio_samplerate: int
    output_path: Path
    temp_dir: Path
    mic_device: int | None = None
    system_audio_device: int | None = None
    mic_volume: int = 100
    system_audio_volume: int = 100
    record_mic: bool = True
    record_system_audio: bool = True

    @classmethod
    def default(cls) -> "AppConfig":
        root = Path.cwd()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(
            region=RecordingRegion(left=100, top=100, width=1280, height=720),
            fps=30,
            audio_samplerate=48000,
            output_path=root / "recordings" / f"recording_{timestamp}.mp4",
            temp_dir=root / ".recording_tmp",
        )

    @property
    def root_dir(self) -> Path:
        return Path.cwd()

    @property
    def ffmpeg_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "resources" / "ffmpeg.exe"

    @property
    def temp_video_path(self) -> Path:
        return self.temp_dir / "video.mp4"

    @property
    def mic_wav_path(self) -> Path:
        return self.temp_dir / "mic.wav"

    @property
    def system_wav_path(self) -> Path:
        return self.temp_dir / "system.wav"

    def prepare_paths(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.root_dir / ".recording_tmp" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.temp_video_path, self.mic_wav_path, self.system_wav_path):
            if path.exists():
                path.unlink()
