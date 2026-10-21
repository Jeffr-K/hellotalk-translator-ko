from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

PcmFloat32 = NDArray[np.float32]
PcmInt16 = NDArray[np.int16]


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A timestamped block received from a live audio source."""

    session_id: str
    source_id: str
    sequence: int
    captured_at_ns: int
    sample_rate: int
    channels: int
    samples: PcmInt16

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        if self.samples.dtype != np.int16:
            raise ValueError("AudioChunk samples must be int16")
        if self.samples.ndim != 2 or self.samples.shape[1] != self.channels:
            raise ValueError("AudioChunk samples must have shape (frames, channels)")


@dataclass(frozen=True, slots=True)
class AudioWindow:
    """An in-memory mono float window ready for an ASR implementation."""

    session_id: str
    source_id: str
    window_id: int
    start_ms: int
    end_ms: int
    sample_rate: int
    samples: PcmFloat32

    def __post_init__(self) -> None:
        if self.samples.dtype != np.float32 or self.samples.ndim != 1:
            raise ValueError("AudioWindow samples must be mono float32")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    session_id: str
    source_id: str
    window_id: int
    start_ms: int
    end_ms: int
    language: str
    text: str
    is_final: bool

    @property
    def segment_id(self) -> str:
        return f"window-{self.window_id}"


class InMemoryTranscriber(Protocol):
    """Boundary for a persistent ASR model that consumes PCM without files."""

    def transcribe(self, window: AudioWindow) -> TranscriptEvent: ...


class AudioArchive(Protocol):
    """Independent raw-audio consumer; never part of the analysis path."""

    def append(self, chunk: AudioChunk) -> None: ...
