from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd


@dataclass(frozen=True, slots=True)
class LiveConfig:
    device: int | str | None
    model: Path
    archive: Path
    sample_rate: int = 48_000
    channels: int = 1
    block_ms: int = 100
    window_seconds: float = 4.0
    overlap_seconds: float = 1.0
    silence_rms: float = 0.006
    ollama_url: str = "http://127.0.0.1:11434/api/generate"
    translation_model: str = "qwen3:4b"
    no_translation: bool = False

    @property
    def step_seconds(self) -> float:
        return self.window_seconds - self.overlap_seconds

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not 0 <= self.overlap_seconds < self.window_seconds:
            raise ValueError("overlap_seconds must be >= 0 and smaller than window_seconds")
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        if self.silence_rms < 0:
            raise ValueError("silence_rms must not be negative")


@dataclass(frozen=True, slots=True)
class Transcript:
    language: str
    text: str
    asr_seconds: float


def pcm_rms(pcm: np.ndarray) -> float:
    if pcm.size == 0:
        return 0.0
    normalized = pcm.astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(normalized * normalized)))


def normalize_text(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.casefold(), flags=re.UNICODE)


def is_duplicate(previous: str, current: str) -> bool:
    old = normalize_text(previous)
    new = normalize_text(current)
    if not old or not new:
        return False
    return old == new or (min(len(old), len(new)) >= 8 and (old in new or new in old))


def is_non_speech(text: str) -> bool:
    stripped = text.strip()
    return bool(re.fullmatch(r"(?:\([^)]*\)|\[[^]]*\]|<[^>]*>)[.!?]?", stripped))


def _write_wav(path: Path, pcm: np.ndarray, sample_rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes(order="C"))


def transcribe_window(pcm: np.ndarray, config: LiveConfig) -> Transcript:
    with tempfile.TemporaryDirectory(prefix="hellotalk-live-") as directory:
        temp_dir = Path(directory)
        source = temp_dir / "window.wav"
        resampled = temp_dir / "window-16k.wav"
        output = temp_dir / "transcript"
        _write_wav(source, pcm, config.sample_rate, config.channels)

        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(resampled),
            ],
            check=True,
            start_new_session=True,
        )
        started = time.monotonic()
        completed = subprocess.run(
            [
                "whisper-cli",
                "--no-gpu",
                "--no-prints",
                "-m",
                str(config.model),
                "-l",
                "auto",
                "-oj",
                "-of",
                str(output),
                str(resampled),
            ],
            check=True,
            capture_output=True,
            start_new_session=True,
            text=True,
        )
        asr_seconds = time.monotonic() - started
        result_path = output.with_suffix(".json")
        if not result_path.exists():
            raise RuntimeError(f"whisper-cli did not create JSON: {completed.stderr.strip()}")
        result = json.loads(result_path.read_text(encoding="utf-8"))

    language = str(result.get("result", {}).get("language", "unknown"))
    text = " ".join(
        str(segment.get("text", "")).strip()
        for segment in result.get("transcription", [])
        if str(segment.get("text", "")).strip()
    ).strip()
    return Transcript(language=language, text=text, asr_seconds=asr_seconds)


def translate_to_korean(text: str, config: LiveConfig) -> tuple[str, float]:
    schema = {
        "type": "object",
        "properties": {"translation": {"type": "string"}},
        "required": ["translation"],
    }
    body = json.dumps(
        {
            "model": config.translation_model,
            "system": (
                "You are a translation engine. Return only valid JSON matching the schema. "
                "Translate faithfully into natural Korean. Do not explain or reason."
            ),
            "prompt": f"Translate into natural Korean: {text}",
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": 256},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        config.ollama_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=30) as response:
        ollama_result = json.load(response)
    elapsed = time.monotonic() - started
    structured = json.loads(ollama_result["response"])
    return str(structured["translation"]).strip(), elapsed


def render_result(transcript: Transcript, translation: str | None, elapsed: float) -> None:
    language = transcript.language.upper()
    print(f"\n[{language}] {transcript.text}", flush=True)
    if translation:
        print(f"[KO] {translation}", flush=True)
    print(
        f"[LATENCY] ASR {transcript.asr_seconds:.2f}s | total {elapsed:.2f}s",
        flush=True,
    )


def process_window(pcm: np.ndarray, config: LiveConfig) -> Transcript | None:
    rms = pcm_rms(pcm)
    if rms < config.silence_rms:
        return None
    return transcribe_window(pcm, config)


def run_live(config: LiveConfig) -> None:
    config.archive.parent.mkdir(parents=True, exist_ok=True)
    block_size = round(config.sample_rate * config.block_ms / 1000)
    window_frames = round(config.sample_rate * config.window_seconds)
    step_frames = round(config.sample_rate * config.step_seconds)
    input_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
    analysis_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=2)
    worker_errors: list[BaseException] = []
    last_text = ""

    def callback(
        indata: np.ndarray,
        _frames: int,
        _time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(f"[AUDIO] {status}", file=sys.stderr, flush=True)
        try:
            input_queue.put_nowait(indata.copy())
        except queue.Full:
            raise sd.CallbackAbort from None

    def worker() -> None:
        nonlocal last_text
        while True:
            pcm = analysis_queue.get()
            try:
                if pcm is None:
                    return
                started = time.monotonic()
                transcript = process_window(pcm, config)
                if transcript is None or not transcript.text or is_non_speech(transcript.text):
                    continue
                if is_duplicate(last_text, transcript.text):
                    continue
                translation: str | None = None
                if not config.no_translation and transcript.language != "ko":
                    translation, _ = translate_to_korean(transcript.text, config)
                render_result(transcript, translation, time.monotonic() - started)
                last_text = transcript.text
            except (
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
                urllib.error.URLError,
            ) as exc:
                print(f"[ANALYSIS ERROR] {exc}", file=sys.stderr, flush=True)
                worker_errors.append(exc)
            finally:
                analysis_queue.task_done()

    worker_thread = threading.Thread(target=worker, name="live-analysis", daemon=True)
    worker_thread.start()
    rolling = np.empty((0, config.channels), dtype=np.int16)
    frames_since_window = 0

    print(
        f"[LISTENING] device={config.device!r}, window={config.window_seconds:.1f}s, "
        f"overlap={config.overlap_seconds:.1f}s — Ctrl+C to stop",
        flush=True,
    )
    try:
        with wave.open(str(config.archive), "wb") as archive:
            archive.setnchannels(config.channels)
            archive.setsampwidth(2)
            archive.setframerate(config.sample_rate)
            with sd.InputStream(
                samplerate=config.sample_rate,
                blocksize=block_size,
                device=config.device,
                channels=config.channels,
                dtype="int16",
                callback=callback,
            ):
                while True:
                    block = input_queue.get()
                    archive.writeframesraw(block.tobytes(order="C"))
                    rolling = np.concatenate((rolling, block))
                    if rolling.shape[0] > window_frames:
                        rolling = rolling[-window_frames:]
                    frames_since_window += block.shape[0]
                    if rolling.shape[0] == window_frames and frames_since_window >= step_frames:
                        frames_since_window = 0
                        try:
                            analysis_queue.put_nowait(rolling.copy())
                        except queue.Full:
                            print("[BACKPRESSURE] analysis window skipped", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[STOPPING] finishing current analysis...", flush=True)
    finally:
        while True:
            try:
                analysis_queue.get_nowait()
                analysis_queue.task_done()
            except queue.Empty:
                break
        analysis_queue.put(None)
        worker_thread.join(timeout=60)
        if worker_thread.is_alive():
            print("[WARNING] analysis worker did not stop in time", file=sys.stderr)
        if worker_errors:
            print(f"[SUMMARY] analysis errors={len(worker_errors)}", file=sys.stderr)


def _device_arg(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live microphone transcription and translation")
    parser.add_argument("--device", type=_device_arg)
    parser.add_argument("--model", type=Path, default=Path("models/ggml-base.bin"))
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("recordings/live-session.wav"),
    )
    parser.add_argument("--window", type=float, default=4.0)
    parser.add_argument("--overlap", type=float, default=1.0)
    parser.add_argument("--silence-rms", type=float, default=0.006)
    parser.add_argument("--translation-model", default="qwen3:4b")
    parser.add_argument("--no-translation", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = LiveConfig(
        device=args.device,
        model=args.model.resolve(),
        archive=args.archive,
        window_seconds=args.window,
        overlap_seconds=args.overlap,
        silence_rms=args.silence_rms,
        translation_model=args.translation_model,
        no_translation=args.no_translation,
    )
    if not config.model.exists():
        raise SystemExit(f"Whisper model not found: {config.model}")
    run_live(config)


if __name__ == "__main__":
    main()
