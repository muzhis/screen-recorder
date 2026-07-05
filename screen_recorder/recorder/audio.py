from __future__ import annotations

import queue
import threading
import wave
import audioop
from dataclasses import dataclass
from pathlib import Path

import sounddevice as sd
try:
    import pyaudiowpatch as pyaudio
except ImportError:  # pragma: no cover - Windows-only optional backend
    pyaudio = None

from screen_recorder.utils.config import AppConfig


@dataclass
class AudioSource:
    label: str
    path: Path
    device: int | None
    channels: int
    samplerate: int
    is_loopback: bool = False
    volume: float = 1.0


@dataclass
class AudioDeviceOption:
    index: int
    name: str
    hostapi: str
    channels: int

    @property
    def label(self) -> str:
        return f"{self.name} [{self.hostapi}]"


class _WaveRecorder:
    def __init__(self, source: AudioSource):
        self.source = source
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._wave: wave.Wave_write | None = None
        self._stream: sd.RawInputStream | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            self.source.path.parent.mkdir(parents=True, exist_ok=True)
            self._wave = wave.open(str(self.source.path), "wb")
            self._wave.setnchannels(self.source.channels)
            self._wave.setsampwidth(2)
            self._wave.setframerate(self.source.samplerate)

            self._thread = threading.Thread(target=self._write_loop, daemon=True)
            self._thread.start()

            stream_kwargs = {}
            if self.source.is_loopback:
                loopback_settings = make_wasapi_loopback_settings()
                if loopback_settings is not None:
                    stream_kwargs["extra_settings"] = loopback_settings

            self._stream = sd.RawInputStream(
                samplerate=self.source.samplerate,
                blocksize=1024,
                device=self.source.device,
                channels=self.source.channels,
                dtype="int16",
                callback=self._callback,
                **stream_kwargs,
            )
            self._stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._wave:
            self._wave.close()
            self._wave = None

    def _callback(self, indata, frames, time_info, status) -> None:
        self._queue.put(bytes(indata))

    def _write_loop(self) -> None:
        while True:
            chunk = self._queue.get()
            if chunk is None:
                break
            if self._wave:
                chunk = apply_pcm_volume(chunk, self.source.volume)
                self._wave.writeframes(chunk)


class _PyAudioLoopbackRecorder:
    def __init__(self, path: Path, device: int | None, volume: float):
        self.path = path
        self.device = device
        self.volume = volume
        self._pa = None
        self._stream = None
        self._wave: wave.Wave_write | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        if pyaudio is None:
            raise RuntimeError("PyAudioWPatch 未安装，无法录制系统声音。")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._pa = pyaudio.PyAudio()
        info = (
            self._pa.get_device_info_by_index(self.device)
            if self.device is not None
            else self._pa.get_default_wasapi_loopback()
        )
        channels = max(1, min(int(info.get("maxInputChannels", 2)), 2))
        samplerate = int(info.get("defaultSampleRate", 48000))

        self._wave = wave.open(str(self.path), "wb")
        self._wave.setnchannels(channels)
        self._wave.setsampwidth(self._pa.get_sample_size(pyaudio.paInt16))
        self._wave.setframerate(samplerate)

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=samplerate,
            input=True,
            input_device_index=int(info["index"]),
            frames_per_buffer=1024,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._wave:
            self._wave.close()
            self._wave = None
        if self._pa:
            self._pa.terminate()
            self._pa = None

    def _read_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                data = self._stream.read(1024, exception_on_overflow=False)
            except Exception:
                break
            if self._wave:
                data = apply_pcm_volume(data, self.volume)
                self._wave.writeframes(data)


class AudioRecorder:
    def __init__(self, config: AppConfig):
        self.config = config
        self._recorders: list[_WaveRecorder] = []

    def start(self) -> str:
        messages: list[str] = []

        if self.config.record_mic:
            mic_device = self.config.mic_device
            mic_channels = self._device_channels(mic_device, "input", default=1)
            mic_samplerate = self._device_samplerate(mic_device, default=self.config.audio_samplerate)
            mic_volume = max(0, self.config.mic_volume) / 100.0
            mic = AudioSource("麦克风", self.config.mic_wav_path, mic_device, mic_channels, mic_samplerate, volume=mic_volume)
            self._start_source(mic, messages)
        else:
            messages.append("麦克风未录入。")

        if not self.config.record_system_audio:
            messages.append("系统声音未录入。")
            return " ".join(messages)

        loopback_device = self.config.system_audio_device
        use_pyaudio_loopback = pyaudio is not None
        if loopback_device is None and use_pyaudio_loopback:
            loopback_device = find_wasapi_output_device()
        elif loopback_device is None:
            loopback_device = find_wasapi_loopback_input_device()

        if loopback_device is None:
            messages.append("未找到系统声音设备，将只录制麦克风。")
        elif use_pyaudio_loopback:
            self._start_system_loopback(loopback_device, messages)
        else:
            system_kind = "input"
            sys_channels = self._device_channels(loopback_device, system_kind, default=2)
            sys_samplerate = self._device_samplerate(loopback_device, default=self.config.audio_samplerate)
            system = AudioSource(
                "系统声音",
                self.config.system_wav_path,
                loopback_device,
                sys_channels,
                sys_samplerate,
                is_loopback=False,
                volume=max(0, self.config.system_audio_volume) / 100.0,
            )
            self._start_source(system, messages)

        return " ".join(messages) if messages else "音频采集已启动。"

    def stop(self) -> None:
        for recorder in self._recorders:
            recorder.stop()
        self._recorders.clear()

    def _start_source(self, source: AudioSource, messages: list[str]) -> None:
        try:
            recorder = _WaveRecorder(source)
            recorder.start()
            self._recorders.append(recorder)
            messages.append(f"{source.label}采集已启动。")
        except Exception as exc:
            recorder.stop()
            if source.path.exists():
                try:
                    source.path.unlink()
                except PermissionError:
                    pass
            messages.append(f"{source.label}采集失败：{exc}")

    def _start_system_loopback(self, device: int, messages: list[str]) -> None:
        volume = max(0, self.config.system_audio_volume) / 100.0
        recorder = _PyAudioLoopbackRecorder(self.config.system_wav_path, device, volume)
        try:
            recorder.start()
            self._recorders.append(recorder)
            messages.append("系统声音采集已启动。")
        except Exception as exc:
            recorder.stop()
            if self.config.system_wav_path.exists():
                try:
                    self.config.system_wav_path.unlink()
                except PermissionError:
                    pass
            messages.append(f"系统声音采集失败：{exc}")

    def _device_channels(self, device: int | None, kind: str, default: int) -> int:
        try:
            info = sd.query_devices(device, kind)
            key = "max_output_channels" if kind == "output" else "max_input_channels"
            return max(1, min(int(info.get(key, default)), 2))
        except Exception:
            return default

    def _device_samplerate(self, device: int | None, default: int) -> int:
        try:
            info = sd.query_devices(device)
            return int(info.get("default_samplerate") or default)
        except Exception:
            return default


def make_wasapi_loopback_settings():
    try:
        return sd.WasapiSettings(loopback=True)
    except (TypeError, AttributeError):
        return None


def apply_pcm_volume(data: bytes, volume: float) -> bytes:
    if volume == 1.0:
        return data
    if volume <= 0:
        return b"\x00" * len(data)
    return audioop.mul(data, 2, volume)


def list_input_devices() -> list[AudioDeviceOption]:
    return _list_devices(kind="input", hostapi_filter=None)


def list_wasapi_output_devices() -> list[AudioDeviceOption]:
    if pyaudio is not None:
        return list_pyaudio_loopback_devices()

    options = _list_devices(kind="output", hostapi_filter="WASAPI")
    preferred = _preferred_wasapi_output_index(options)
    return sorted(
        options,
        key=lambda option: (
            option.index != preferred,
            not _looks_like_speaker(option.name),
            option.name,
        ),
    )


def find_wasapi_output_device() -> int | None:
    if pyaudio is not None:
        try:
            pa = pyaudio.PyAudio()
            try:
                return int(pa.get_default_wasapi_loopback()["index"])
            finally:
                pa.terminate()
        except Exception:
            return None

    try:
        devices = sd.query_devices()
        default_pair = sd.default.device
        default_output = default_pair[1] if isinstance(default_pair, (list, tuple)) else None
    except Exception:
        return None

    wasapi_outputs = _list_devices(kind="output", hostapi_filter="WASAPI")
    if not wasapi_outputs:
        return None

    preferred = _preferred_wasapi_output_index(wasapi_outputs)
    if preferred is not None:
        return preferred

    speaker_keywords = ("speaker", "扬声器", "headphone", "耳机")
    for option in wasapi_outputs:
        if any(keyword in option.name.lower() for keyword in speaker_keywords):
            return option.index

    return wasapi_outputs[0].index


def find_wasapi_loopback_input_device() -> int | None:
    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception:
        return None

    wasapi_ids = {
        index
        for index, api in enumerate(hostapis)
        if "WASAPI" in str(api.get("name", "")).upper()
    }

    preferred_keywords = ("loopback", "立体声混音", "stereo mix", "what u hear")
    fallback: int | None = None
    for index, device in enumerate(devices):
        if device.get("hostapi") not in wasapi_ids:
            continue
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        name = str(device.get("name", "")).lower()
        if any(keyword in name for keyword in preferred_keywords):
            return index
        fallback = index
    return fallback


def _list_devices(kind: str, hostapi_filter: str | None) -> list[AudioDeviceOption]:
    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception:
        return []

    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    options: list[AudioDeviceOption] = []
    for index, device in enumerate(devices):
        hostapi = str(hostapis[device["hostapi"]]["name"])
        if hostapi_filter and hostapi_filter.upper() not in hostapi.upper():
            continue
        channels = int(device.get(channel_key, 0))
        if channels <= 0:
            continue
        options.append(
            AudioDeviceOption(
                index=index,
                name=str(device.get("name", f"Device {index}")),
                hostapi=hostapi,
                channels=channels,
            )
        )
    return sorted(options, key=lambda option: ("WDM-KS" in option.hostapi, option.hostapi, option.name))


def _base_device_name(name: str) -> str:
    return " ".join(name.lower().split())


def list_pyaudio_loopback_devices() -> list[AudioDeviceOption]:
    if pyaudio is None:
        return []
    pa = pyaudio.PyAudio()
    try:
        options = [
            AudioDeviceOption(
                index=int(device["index"]),
                name=str(device["name"]),
                hostapi="Windows WASAPI Loopback",
                channels=int(device.get("maxInputChannels", 2)),
            )
            for device in pa.get_loopback_device_info_generator()
        ]
        default_index = int(pa.get_default_wasapi_loopback()["index"])
        return sorted(options, key=lambda option: (option.index != default_index, option.name))
    finally:
        pa.terminate()


def _preferred_wasapi_output_index(options: list[AudioDeviceOption]) -> int | None:
    try:
        devices = sd.query_devices()
        default_pair = sd.default.device
        default_output = default_pair[1] if isinstance(default_pair, (list, tuple)) else None
    except Exception:
        return None

    if default_output is None or int(default_output) < 0:
        return None

    default_name = _base_device_name(str(devices[int(default_output)].get("name", "")))
    for option in options:
        if _base_device_name(option.name) == default_name:
            return option.index
    return None


def _looks_like_speaker(name: str) -> bool:
    lower_name = name.lower()
    return any(keyword in lower_name for keyword in ("speaker", "扬声器", "headphone", "耳机"))
