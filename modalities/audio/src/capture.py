from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

from frames import AudioFormat, AudioFrame
from metrics import CaptureMetrics


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    output: Path
    duration_seconds: float = 30.0
    device: int | str | None = None
    sample_rate: int | None = None
    channels: int = 1
    block_duration_ms: int = 100
    queue_seconds: int = 10

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if not 20 <= self.block_duration_ms <= 1000:
            raise ValueError("block_duration_ms must be between 20 and 1000")
        if self.queue_seconds <= 0:
            raise ValueError("queue_seconds must be positive")


class CaptureFailure(RuntimeError):
    pass


def _resolve_device(device: int | str | None) -> tuple[int | str | None, dict[str, Any]]:
    selected = sd.query_devices(device, "input")
    return device, dict(selected)


def capture(config: CaptureConfig) -> dict[str, Any]:
    device, device_info = _resolve_device(config.device)
    sample_rate = config.sample_rate or int(device_info["default_samplerate"])
    audio_format = AudioFormat(sample_rate=sample_rate, channels=config.channels)
    block_size = max(1, round(sample_rate * config.block_duration_ms / 1000))
    queue_blocks = max(2, round(config.queue_seconds * 1000 / config.block_duration_ms))
    frame_queue: queue.Queue[AudioFrame | None] = queue.Queue(maxsize=queue_blocks)
    stop_requested = threading.Event()
    overflow_detected = threading.Event()
    target_reached = threading.Event()
    writer_error: list[BaseException] = []
    metrics = CaptureMetrics()
    sequence = 0
    captured_frame_count = 0
    target_frame_count = round(config.duration_seconds * sample_rate)

    config.output.parent.mkdir(parents=True, exist_ok=True)

    def callback(
        indata: np.ndarray,
        frames: int,
        _time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        nonlocal captured_frame_count, sequence
        status_text = str(status) if status else None
        metrics.record_callback(frames, has_status=bool(status))
        frame = AudioFrame(
            sequence=sequence,
            captured_at_ns=time.monotonic_ns(),
            pcm=indata.copy(),
            callback_status=status_text,
        )
        sequence += 1
        try:
            frame_queue.put_nowait(frame)
            captured_frame_count += frames
            if captured_frame_count >= target_frame_count:
                target_reached.set()
        except queue.Full:
            metrics.record_queue_overflow()
            overflow_detected.set()
            stop_requested.set()
            raise sd.CallbackAbort from None

    def writer() -> None:
        expected_sequence = 0
        try:
            with wave.open(str(config.output), "wb") as wav_file:
                wav_file.setnchannels(audio_format.channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(audio_format.sample_rate)
                while True:
                    frame = frame_queue.get()
                    try:
                        if frame is None:
                            return
                        if frame.sequence != expected_sequence:
                            metrics.record_sequence_gap(frame.sequence - expected_sequence)
                        expected_sequence = frame.sequence + 1
                        wav_file.writeframesraw(frame.pcm.tobytes(order="C"))
                        metrics.record_written(frame.pcm)
                    finally:
                        frame_queue.task_done()
        except BaseException as exc:  # ensure the capture loop can report writer failures
            writer_error.append(exc)
            stop_requested.set()

    writer_thread = threading.Thread(target=writer, name="audio-wav-writer", daemon=True)
    writer_thread.start()
    capture_requested_monotonic_ns = time.monotonic_ns()
    started_wall_time = time.time()
    stream_opened_monotonic_ns: int | None = None

    try:
        with sd.InputStream(
            samplerate=audio_format.sample_rate,
            blocksize=block_size,
            device=device,
            channels=audio_format.channels,
            dtype="int16",
            callback=callback,
        ):
            stream_opened_monotonic_ns = time.monotonic_ns()
            deadline = time.monotonic() + config.duration_seconds + 5
            while not target_reached.is_set() and not stop_requested.wait(0.02):
                if time.monotonic() >= deadline:
                    raise CaptureFailure("audio input did not deliver the requested duration")
    finally:
        try:
            frame_queue.put(None, timeout=5)
        except queue.Full as exc:
            raise CaptureFailure("raw capture queue did not drain") from exc
        writer_thread.join(timeout=15)

    if writer_thread.is_alive():
        raise CaptureFailure("WAV writer did not stop within 15 seconds")
    if writer_error:
        raise CaptureFailure(f"WAV writer failed: {writer_error[0]}") from writer_error[0]
    if overflow_detected.is_set():
        raise CaptureFailure("raw capture queue overflowed; the WAV is incomplete")

    snapshot = metrics.snapshot()
    ended_monotonic_ns = time.monotonic_ns()
    recorded_duration_seconds = snapshot.frames_written / audio_format.sample_rate
    result: dict[str, Any] = {
        "output": str(config.output.resolve()),
        "started_wall_time_unix": started_wall_time,
        "capture_requested_monotonic_ns": capture_requested_monotonic_ns,
        "stream_opened_monotonic_ns": stream_opened_monotonic_ns,
        "ended_monotonic_ns": ended_monotonic_ns,
        "device_open_seconds": (
            (stream_opened_monotonic_ns - capture_requested_monotonic_ns) / 1_000_000_000
            if stream_opened_monotonic_ns is not None
            else None
        ),
        "requested_duration_seconds": config.duration_seconds,
        "recorded_duration_seconds": recorded_duration_seconds,
        "device": {
            "requested": config.device,
            "name": str(device_info["name"]),
            "max_input_channels": int(device_info["max_input_channels"]),
            "default_sample_rate": int(device_info["default_samplerate"]),
        },
        "audio_format": asdict(audio_format),
        "block_size": block_size,
        "block_duration_ms": config.block_duration_ms,
        "queue_capacity_blocks": queue_blocks,
        "metrics": snapshot.to_dict(),
    }
    metadata_path = config.output.with_suffix(config.output.suffix + ".json")
    metadata_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result["metadata"] = str(metadata_path.resolve())
    return result


def _device_arg(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture raw PCM audio to a WAV file")
    parser.add_argument("--output", type=Path, default=Path("recordings/input-poc.wav"))
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--device", type=_device_arg)
    parser.add_argument("--sample-rate", type=int)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--block-ms", type=int, default=100)
    parser.add_argument("--queue-seconds", type=int, default=10)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = CaptureConfig(
        output=args.output,
        duration_seconds=args.duration,
        device=args.device,
        sample_rate=args.sample_rate,
        channels=args.channels,
        block_duration_ms=args.block_ms,
        queue_seconds=args.queue_seconds,
    )
    try:
        result = capture(config)
    except (CaptureFailure, sd.PortAudioError, ValueError) as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
