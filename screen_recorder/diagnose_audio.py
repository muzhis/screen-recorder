from __future__ import annotations

import sounddevice as sd
import pyaudiowpatch as pyaudio


def main() -> int:
    print("Default devices:", sd.default.device)
    print("\nHost APIs:")
    for index, api in enumerate(sd.query_hostapis()):
        print(f"[{index}] {api['name']}")

    print("\nDevices:")
    for index, device in enumerate(sd.query_devices()):
        hostapi = sd.query_hostapis()[device["hostapi"]]["name"]
        print(
            f"[{index}] {device['name']} | api={hostapi} | "
            f"in={device['max_input_channels']} | out={device['max_output_channels']} | "
            f"rate={int(device['default_samplerate'])}"
        )

    print("\nWASAPI loopback devices:")
    pa = pyaudio.PyAudio()
    try:
        default_loopback = pa.get_default_wasapi_loopback()
        print(
            "default:",
            f"[{default_loopback['index']}]",
            default_loopback["name"],
        )
        for device in pa.get_loopback_device_info_generator():
            print(
                f"[{device['index']}] {device['name']} | "
                f"in={device['maxInputChannels']} | "
                f"rate={int(device['defaultSampleRate'])}"
            )
    finally:
        pa.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
