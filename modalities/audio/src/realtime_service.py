from __future__ import annotations

import asyncio
import contextlib
import queue
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

from contracts import AudioChunk, InMemoryTranscriber, TranscriptEvent
from events import EventBroker, StreamEvent
from learning_agent import OllamaLearningAgent
from streaming_pipeline import InMemoryStreamingPipeline, StreamingConfig
from transcriber import EnergyGatedTranscriber, WhisperCppTranscriber


@dataclass(frozen=True, slots=True)
class RealtimeConfig:
    device: int | str | None
    model: Path
    sample_rate: int = 48_000
    channels: int = 1
    block_ms: int = 100
    window_seconds: float = 4.0
    overlap_seconds: float = 1.0
    silence_rms: float = 0.006
    source_id: str = "mac-audio-input"
    learning_enabled: bool = True
    language: str | None = None


def _normalized(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.casefold(), flags=re.UNICODE)


class RealtimeSession:
    def __init__(
        self,
        config: RealtimeConfig,
        broker: EventBroker,
        loop: asyncio.AbstractEventLoop,
        transcriber: InMemoryTranscriber,
        learning_agent: OllamaLearningAgent | None,
    ) -> None:
        self.session_id = str(uuid.uuid4())
        self._config = config
        self._broker = broker
        self._loop = loop
        self._learning_agent = learning_agent
        self._pipeline = InMemoryStreamingPipeline(
            StreamingConfig(
                window_seconds=config.window_seconds,
                overlap_seconds=config.overlap_seconds,
            ),
            transcriber,
        )
        self._chunks: queue.Queue[AudioChunk | None] = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._sequence = 0
        self._previous_text = ""
        self._stream: sd.InputStream | None = None
        self._worker = threading.Thread(target=self._run_worker, name="realtime-asr", daemon=True)

    def start(self) -> None:
        block_size = round(self._config.sample_rate * self._config.block_ms / 1000)

        def callback(
            indata: np.ndarray,
            _frames: int,
            _time_info: Any,
            status: sd.CallbackFlags,
        ) -> None:
            sequence = self._sequence
            self._sequence += 1
            chunk = AudioChunk(
                session_id=self.session_id,
                source_id=self._config.source_id,
                sequence=sequence,
                captured_at_ns=time.monotonic_ns(),
                sample_rate=self._config.sample_rate,
                channels=self._config.channels,
                samples=indata.copy(),
            )
            if status:
                self._publish_threadsafe(
                    StreamEvent(
                        type="pipeline.warning",
                        session_id=self.session_id,
                        data={"message": str(status), "sequence": sequence},
                    )
                )
            try:
                self._chunks.put_nowait(chunk)
            except queue.Full:
                self._publish_threadsafe(
                    StreamEvent(
                        type="pipeline.warning",
                        session_id=self.session_id,
                        data={"message": "audio queue overflow", "sequence": sequence},
                    )
                )

        self._worker.start()
        try:
            self._stream = sd.InputStream(
                samplerate=self._config.sample_rate,
                blocksize=block_size,
                device=self._config.device,
                channels=self._config.channels,
                dtype="int16",
                callback=callback,
            )
            self._stream.start()
        except BaseException:
            self._stop.set()
            self._chunks.put_nowait(None)
            self._worker.join(timeout=5)
            raise
        self._publish_threadsafe(
            StreamEvent(
                type="session.started",
                session_id=self.session_id,
            data={
                "device": self._config.device,
                "sample_rate": self._config.sample_rate,
                "language": self._config.language or "auto",
            },
            )
        )

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        with contextlib.suppress(queue.Full):
            self._chunks.put_nowait(None)
        self._worker.join(timeout=15)
        self._publish_threadsafe(
            StreamEvent(type="session.stopped", session_id=self.session_id)
        )

    def _publish_threadsafe(self, event: StreamEvent) -> None:
        asyncio.run_coroutine_threadsafe(self._broker.publish(event), self._loop)

    def _run_worker(self) -> None:
        while True:
            chunk = self._chunks.get()
            if chunk is None or self._stop.is_set():
                return
            started = time.monotonic()
            try:
                events = self._pipeline.ingest(chunk)
                for transcript in events:
                    if not transcript.text or self._is_duplicate(transcript.text):
                        continue
                    self._publish_transcript(transcript, time.monotonic() - started)
            except Exception as exc:
                self._publish_threadsafe(
                    StreamEvent(
                        type="pipeline.warning",
                        session_id=self.session_id,
                        data={"message": str(exc)},
                    )
                )

    def _is_duplicate(self, text: str) -> bool:
        previous = _normalized(self._previous_text)
        current = _normalized(text)
        duplicate = bool(
            previous
            and current
            and (
                previous == current
                or (
                    min(len(previous), len(current)) >= 8
                    and (previous in current or current in previous)
                )
            )
        )
        if not duplicate:
            self._previous_text = text
        return duplicate

    def _publish_transcript(self, transcript: TranscriptEvent, latency: float) -> None:
        data = {
            "segment_id": transcript.segment_id,
            "revision": 1,
            "start_ms": transcript.start_ms,
            "end_ms": transcript.end_ms,
            "language": transcript.language,
            "speaker_id": None,
            "text": transcript.text,
            "latency_ms": round(latency * 1000),
        }
        self._publish_threadsafe(
            StreamEvent(type="transcript.final", session_id=self.session_id, data=data)
        )
        if self._learning_agent is not None and transcript.language != "ko":
            asyncio.run_coroutine_threadsafe(
                self._enrich(transcript),
                self._loop,
            )

    async def _enrich(self, transcript: TranscriptEvent) -> None:
        assert self._learning_agent is not None
        try:
            result = await asyncio.to_thread(
                self._learning_agent.analyze,
                transcript.text,
                transcript.language,
            )
            common = {"segment_id": transcript.segment_id, "revision": 1}
            await self._broker.publish(
                StreamEvent(
                    type="translation.final",
                    session_id=self.session_id,
                    data={**common, "text": result.translation},
                )
            )
            await self._broker.publish(
                StreamEvent(
                    type="grammar.suggested",
                    session_id=self.session_id,
                    data={
                        **common,
                        "items": [item.model_dump() for item in result.grammar],
                    },
                )
            )
        except Exception as exc:
            await self._broker.publish(
                StreamEvent(
                    type="pipeline.warning",
                    session_id=self.session_id,
                    data={
                        "message": f"learning analysis failed: {exc}",
                        "segment_id": transcript.segment_id,
                    },
                )
            )


class SessionController:
    def __init__(
        self,
        broker: EventBroker,
        *,
        learning_agent: OllamaLearningAgent | None = None,
        transcriber_factory: Callable[[RealtimeConfig], InMemoryTranscriber] | None = None,
    ) -> None:
        self._broker = broker
        self._learning_agent = learning_agent
        self._transcriber_factory = transcriber_factory or self._default_transcriber
        self._session: RealtimeSession | None = None

    @staticmethod
    def _default_transcriber(config: RealtimeConfig) -> InMemoryTranscriber:
        return EnergyGatedTranscriber(
            WhisperCppTranscriber(config.model, language=config.language),
            threshold=config.silence_rms,
        )

    @property
    def active_session_id(self) -> str | None:
        return self._session.session_id if self._session is not None else None

    async def start(self, config: RealtimeConfig) -> str:
        if self._session is not None:
            raise RuntimeError("a realtime session is already active")
        transcriber = await asyncio.to_thread(self._transcriber_factory, config)
        session = RealtimeSession(
            config,
            self._broker,
            asyncio.get_running_loop(),
            transcriber,
            self._learning_agent if config.learning_enabled else None,
        )
        await asyncio.to_thread(session.start)
        self._session = session
        return session.session_id

    async def stop(self) -> None:
        if self._session is None:
            return
        session, self._session = self._session, None
        await asyncio.to_thread(session.stop)
