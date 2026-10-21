from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock

import numpy as np

from frames import Pcm16


@dataclass(frozen=True, slots=True)
class CaptureSnapshot:
    callbacks: int
    frames_received: int
    frames_written: int
    sequence_gaps: int
    queue_overflows: int
    callback_status_events: int
    clipped_samples: int
    peak: float
    rms: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


class CaptureMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._callbacks = 0
        self._frames_received = 0
        self._frames_written = 0
        self._sequence_gaps = 0
        self._queue_overflows = 0
        self._callback_status_events = 0
        self._clipped_samples = 0
        self._peak = 0.0
        self._sum_squares = 0.0
        self._sample_count = 0

    def record_callback(self, frame_count: int, has_status: bool) -> None:
        with self._lock:
            self._callbacks += 1
            self._frames_received += frame_count
            if has_status:
                self._callback_status_events += 1

    def record_queue_overflow(self) -> None:
        with self._lock:
            self._queue_overflows += 1

    def record_sequence_gap(self, missing_frames: int = 1) -> None:
        with self._lock:
            self._sequence_gaps += missing_frames

    def record_written(self, pcm: Pcm16) -> None:
        normalized = pcm.astype(np.float64) / 32768.0
        peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
        clipped = int(np.count_nonzero(np.abs(pcm.astype(np.int32)) >= 32767))
        sum_squares = float(np.sum(normalized * normalized))

        with self._lock:
            self._frames_written += int(pcm.shape[0])
            self._clipped_samples += clipped
            self._peak = max(self._peak, peak)
            self._sum_squares += sum_squares
            self._sample_count += int(normalized.size)

    def snapshot(self) -> CaptureSnapshot:
        with self._lock:
            rms = (
                (self._sum_squares / self._sample_count) ** 0.5
                if self._sample_count
                else 0.0
            )
            return CaptureSnapshot(
                callbacks=self._callbacks,
                frames_received=self._frames_received,
                frames_written=self._frames_written,
                sequence_gaps=self._sequence_gaps,
                queue_overflows=self._queue_overflows,
                callback_status_events=self._callback_status_events,
                clipped_samples=self._clipped_samples,
                peak=self._peak,
                rms=rms,
            )
