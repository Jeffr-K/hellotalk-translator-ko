from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soxr

from contracts import AudioChunk, AudioWindow, InMemoryTranscriber, TranscriptEvent


class SequenceGapError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StreamingConfig:
    target_sample_rate: int = 16_000
    window_seconds: float = 4.0
    overlap_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.target_sample_rate <= 0:
            raise ValueError("target_sample_rate must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not 0 <= self.overlap_seconds < self.window_seconds:
            raise ValueError("overlap_seconds must be >= 0 and smaller than window_seconds")

    @property
    def window_frames(self) -> int:
        return round(self.target_sample_rate * self.window_seconds)

    @property
    def step_frames(self) -> int:
        return round(
            self.target_sample_rate * (self.window_seconds - self.overlap_seconds)
        )


def int16_to_mono_float32(samples: np.ndarray) -> np.ndarray:
    if samples.dtype != np.int16 or samples.ndim != 2:
        raise ValueError("samples must be a 2D int16 array")
    mono = samples.astype(np.float32).mean(axis=1)
    return np.ascontiguousarray(mono / 32768.0, dtype=np.float32)


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """In-memory reference resampler for the pipeline boundary.

    It is intentionally replaceable. Production audio should use a stateful,
    band-limited resampler while keeping the same AudioWindow contract.
    """
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    if samples.dtype != np.float32 or samples.ndim != 1:
        raise ValueError("samples must be mono float32")
    if source_rate == target_rate or samples.size == 0:
        return samples.copy()

    output_length = max(1, round(samples.size * target_rate / source_rate))
    source_positions = np.arange(samples.size, dtype=np.float64)
    target_positions = np.linspace(0, samples.size - 1, output_length, dtype=np.float64)
    result = np.interp(target_positions, source_positions, samples)
    return np.ascontiguousarray(result, dtype=np.float32)


class AudioWindowAssembler:
    """Turns live chunks into overlapping in-memory ASR windows."""

    def __init__(self, config: StreamingConfig) -> None:
        self._config = config
        self._buffer = np.empty(0, dtype=np.float32)
        self._next_sequence: int | None = None
        self._window_id = 0
        self._next_window_start_frame = 0
        self._received_target_frames = 0
        self._session_id: str | None = None
        self._source_id: str | None = None
        self._source_rate: int | None = None
        self._resampler: soxr.ResampleStream | None = None

    def push(self, chunk: AudioChunk) -> list[AudioWindow]:
        if self._next_sequence is not None and chunk.sequence != self._next_sequence:
            raise SequenceGapError(
                f"expected sequence {self._next_sequence}, received {chunk.sequence}"
            )
        if self._session_id is not None and (
            chunk.session_id != self._session_id or chunk.source_id != self._source_id
        ):
            raise ValueError("an assembler instance accepts only one session and source")

        self._next_sequence = chunk.sequence + 1
        self._session_id = chunk.session_id
        self._source_id = chunk.source_id
        mono = int16_to_mono_float32(chunk.samples)
        if self._source_rate is None:
            self._source_rate = chunk.sample_rate
            if chunk.sample_rate != self._config.target_sample_rate:
                self._resampler = soxr.ResampleStream(
                    chunk.sample_rate,
                    self._config.target_sample_rate,
                    1,
                    dtype="float32",
                    quality="HQ",
                )
        elif chunk.sample_rate != self._source_rate:
            raise ValueError("sample rate cannot change during a session")

        resampled = (
            self._resampler.resample_chunk(mono)
            if self._resampler is not None
            else mono.copy()
        )
        self._buffer = np.concatenate((self._buffer, resampled))
        self._received_target_frames += resampled.size

        windows: list[AudioWindow] = []
        while self._buffer.size >= self._config.window_frames:
            start_frame = self._next_window_start_frame
            end_frame = start_frame + self._config.window_frames
            windows.append(
                AudioWindow(
                    session_id=chunk.session_id,
                    source_id=chunk.source_id,
                    window_id=self._window_id,
                    start_ms=round(start_frame / self._config.target_sample_rate * 1000),
                    end_ms=round(end_frame / self._config.target_sample_rate * 1000),
                    sample_rate=self._config.target_sample_rate,
                    samples=np.ascontiguousarray(
                        self._buffer[: self._config.window_frames], dtype=np.float32
                    ),
                )
            )
            self._window_id += 1
            self._next_window_start_frame += self._config.step_frames
            self._buffer = self._buffer[self._config.step_frames :]
        return windows


class InMemoryStreamingPipeline:
    """File-free analysis core. Archiving is connected outside this class."""

    def __init__(self, config: StreamingConfig, transcriber: InMemoryTranscriber) -> None:
        self._assembler = AudioWindowAssembler(config)
        self._transcriber = transcriber

    def ingest(self, chunk: AudioChunk) -> list[TranscriptEvent]:
        return [self._transcriber.transcribe(window) for window in self._assembler.push(chunk)]
