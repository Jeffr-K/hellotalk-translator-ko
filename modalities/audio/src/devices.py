from __future__ import annotations

import json
from typing import Any

import sounddevice as sd


def input_devices() -> list[dict[str, Any]]:
    default_input = sd.default.device[0]
    devices: list[dict[str, Any]] = []
    for index, raw_device in enumerate(sd.query_devices()):
        device = dict(raw_device)
        if int(device["max_input_channels"]) <= 0:
            continue
        devices.append(
            {
                "id": index,
                "name": str(device["name"]),
                "input_channels": int(device["max_input_channels"]),
                "default_sample_rate": int(device["default_samplerate"]),
                "host_api": int(device["hostapi"]),
                "is_default_input": index == default_input,
            }
        )
    return devices


def main() -> None:
    print(json.dumps(input_devices(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
