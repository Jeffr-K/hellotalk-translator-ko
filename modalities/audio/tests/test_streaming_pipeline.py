from __future__ import annotations

import builtins

import numpy as np
import pytest

from contracts import AudioChunk, AudioWindow, TranscriptEvent
from streaming_pipeline import (
    AudioWindowAssembler,
    InMemoryStreamingPipeline,
    SequenceGapError,
    StreamingConfig,
)


class FakePersistentTranscriber:
    def __init__(self) -> None:
        self.window_object_ids: list[int] = []

    def transcribe(self, window: AudioWindow) -> TranscriptEvent:
        self.window_object_ids.append(id(window.samples))
        return TranscriptEvent(
            session_id=window.session_id,
            source_id=window.source_id,
            window_id=window.window_id,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            language="en",
            text=f"window-{window.window_id}",
            is_final=False,
        )


def chunk(sequence: int, seconds: float = 1.0, sample_rate: int = 48_000) -> AudioChunk:
    samples = np.full((round(seconds * sample_rate), 1), 4_096, dtype=np.int16)
    return AudioChunk(
        session_id="session-001",
        source_id="iphone-room",
        sequence=sequence,
        captured_at_ns=sequence * 1_000_000_000,
        sample_rate=sample_rate,
        channels=1,
        samples=samples,
    )


def test_pipeline_emits_overlapping_memory_windows_without_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_file_io(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the streaming analysis path must not open files")

    monkeypatch.setattr(builtins, "open", reject_file_io)
    transcriber = FakePersistentTranscriber()
    pipeline = InMemoryStreamingPipeline(
        StreamingConfig(window_seconds=2, overlap_seconds=0.5),
        transcriber,
    )

    events = []
    for sequence in range(4):
        events.extend(pipeline.ingest(chunk(sequence)))

    assert [(event.start_ms, event.end_ms) for event in events] == [
        (0, 2000),
        (1500, 3500),
    ]
    assert [event.text for event in events] == ["window-0", "window-1"]
    assert len(set(transcriber.window_object_ids)) == 2


def test_assembler_rejects_sequence_gaps() -> None:
    assembler = AudioWindowAssembler(StreamingConfig(window_seconds=2, overlap_seconds=0))
    assembler.push(chunk(0))
    with pytest.raises(SequenceGapError, match="expected sequence 1, received 2"):
        assembler.push(chunk(2))


def test_pipeline_resamples_to_16khz_mono_float32() -> None:
    assembler = AudioWindowAssembler(StreamingConfig(window_seconds=1, overlap_seconds=0))
    windows = assembler.push(chunk(0)) + assembler.push(chunk(1, seconds=0.1))

    assert len(windows) == 1
    assert windows[0].sample_rate == 16_000
    assert windows[0].samples.shape == (16_000,)
    assert windows[0].samples.dtype == np.float32
