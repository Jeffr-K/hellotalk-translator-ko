from __future__ import annotations

from pathlib import Path

import numpy as np

from contracts import AudioWindow, TranscriptEvent


class WhisperCppTranscriber:
    """Persistent whisper.cpp adapter accepting in-memory float32 PCM."""

    def __init__(
        self,
        model_path: Path,
        *,
        threads: int = 4,
        use_gpu: bool = False,
        language: str | None = None,
    ) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        from pywhispercpp.model import Model

        self._language = language
        self._model = Model(
            str(model_path),
            context_params={"use_gpu": use_gpu},
            n_threads=threads,
            language=language or "",
            detect_language=language is None,
            print_progress=False,
            print_realtime=False,
            print_timestamps=False,
            no_context=True,
        )

    def transcribe(self, window: AudioWindow) -> TranscriptEvent:
        # The binding consumes normalized 16 kHz mono samples directly. No WAV,
        # FFmpeg, or child process exists on this path.
        if self._language is None:
            (language, _probability), _ = self._model.auto_detect_language(window.samples)
        else:
            language = self._language
        segments = self._model.transcribe(
            window.samples,
            language=language,
            detect_language=False,
            no_context=True,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return TranscriptEvent(
            session_id=window.session_id,
            source_id=window.source_id,
            window_id=window.window_id,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            language=language,
            text=text.strip(),
            is_final=True,
        )


class EnergyGatedTranscriber:
    """Cheap VAD boundary that avoids ASR work for silent windows."""

    def __init__(self, delegate: WhisperCppTranscriber, *, threshold: float = 0.006) -> None:
        if threshold < 0:
            raise ValueError("threshold must not be negative")
        self._delegate = delegate
        self._threshold = threshold

    def transcribe(self, window: AudioWindow) -> TranscriptEvent:
        rms = float(np.sqrt(np.mean(np.square(window.samples, dtype=np.float64))))
        if rms < self._threshold:
            return TranscriptEvent(
                session_id=window.session_id,
                source_id=window.source_id,
                window_id=window.window_id,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
                language="unknown",
                text="",
                is_final=True,
            )
        return self._delegate.transcribe(window)
