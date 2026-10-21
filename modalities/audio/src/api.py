from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import sounddevice as sd
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from events import EventBroker, StreamEvent
from learning_agent import OllamaLearningAgent
from realtime_service import RealtimeConfig, SessionController


class StartSessionRequest(BaseModel):
    device: int | str | None = None
    model: str = "models/ggml-base.bin"
    sample_rate: int = Field(default=48_000, gt=0)
    channels: int = Field(default=1, gt=0)
    window_seconds: float = Field(default=4.0, gt=0)
    overlap_seconds: float = Field(default=1.0, ge=0)
    learning: bool = True
    language: Literal["auto", "ja", "ko", "en"] = "auto"


def create_app(
    *,
    broker: EventBroker | None = None,
    controller: SessionController | None = None,
) -> FastAPI:
    event_broker = broker or EventBroker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.broker = event_broker
        app.state.controller = controller or SessionController(
            event_broker,
            learning_agent=OllamaLearningAgent(),
        )
        yield
        await app.state.controller.stop()

    app = FastAPI(title="HelloTalk realtime learning API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health(request: Request) -> dict[str, str | None]:
        return {
            "status": "ok",
            "active_session_id": request.app.state.controller.active_session_id,
        }

    @app.get("/api/devices")
    async def devices() -> list[dict[str, int | float | str]]:
        return [
            {
                "id": index,
                "name": str(device["name"]),
                "channels": int(device["max_input_channels"]),
                "sample_rate": float(device["default_samplerate"]),
            }
            for index, device in enumerate(sd.query_devices())
            if int(device["max_input_channels"]) > 0
        ]

    @app.post("/api/sessions")
    async def start_session(payload: StartSessionRequest, request: Request) -> dict[str, str]:
        if payload.overlap_seconds >= payload.window_seconds:
            raise HTTPException(422, "overlap_seconds must be smaller than window_seconds")
        config = RealtimeConfig(
            device=payload.device,
            model=Path(payload.model).resolve(),
            sample_rate=payload.sample_rate,
            channels=payload.channels,
            window_seconds=payload.window_seconds,
            overlap_seconds=payload.overlap_seconds,
            learning_enabled=payload.learning,
            language=None if payload.language == "auto" else payload.language,
        )
        try:
            session_id = await request.app.state.controller.start(config)
        except (FileNotFoundError, RuntimeError, sd.PortAudioError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"session_id": session_id}

    @app.post("/api/sessions/stop")
    async def stop_session(request: Request) -> dict[str, str]:
        await request.app.state.controller.stop()
        return {"status": "stopped"}

    @app.get("/api/events")
    async def events(
        request: Request,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> StreamingResponse:
        event_broker: EventBroker = request.app.state.broker
        after_id = event_broker.parse_cursor(last_event_id)

        async def stream():
            yield ": connected\n\n"
            async for event in request.app.state.broker.subscribe(after_id):
                if await request.is_disconnected():
                    break
                yield event.as_sse(event_broker.cursor_for(event))

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/demo")
    async def demo(
        request: Request,
        text: Annotated[str, Body(embed=True)] = "I have been learning Rust for two years.",
    ) -> dict[str, str]:
        session_id = request.app.state.controller.active_session_id or "demo-session"
        segment_id = "demo-1"
        await request.app.state.broker.publish(
            StreamEvent(
                type="transcript.final",
                session_id=session_id,
                data={
                    "segment_id": segment_id,
                    "revision": 1,
                    "start_ms": 0,
                    "end_ms": 4000,
                    "language": "en",
                    "speaker_id": None,
                    "text": text,
                    "latency_ms": 120,
                },
            )
        )
        await request.app.state.broker.publish(
            StreamEvent(
                type="translation.final",
                session_id=session_id,
                data={
                    "segment_id": segment_id,
                    "revision": 1,
                    "text": "저는 2년 동안 Rust를 배우고 있습니다.",
                },
            )
        )
        await request.app.state.broker.publish(
            StreamEvent(
                type="grammar.suggested",
                session_id=session_id,
                data={
                    "segment_id": segment_id,
                    "revision": 1,
                    "items": [
                        {
                            "pattern": "have been + -ing",
                            "explanation": "과거부터 현재까지 계속된 동작을 나타냅니다.",
                            "example": "I have been learning Rust.",
                        }
                    ],
                },
            )
        )
        return {"status": "published"}

    return app


app = create_app()
