from __future__ import annotations

import asyncio
import json

from events import EventBroker, StreamEvent


def test_stream_event_serializes_named_sse() -> None:
    event = StreamEvent(
        id=7,
        type="transcript.final",
        session_id="session-1",
        data={"text": "こんにちは"},
    )

    rendered = event.as_sse()

    assert rendered.startswith("id: 7\nevent: transcript.final\ndata: ")
    payload = json.loads(rendered.split("data: ", 1)[1])
    assert payload["data"]["text"] == "こんにちは"


def test_broker_rejects_cursor_from_previous_process() -> None:
    broker = EventBroker()

    assert broker.parse_cursor(f"{broker.instance_id}:42") == 42
    assert broker.parse_cursor("old-process:42") == 0
    assert broker.parse_cursor("42") == 0


def test_broker_replays_events_after_last_seen_id() -> None:
    async def scenario() -> tuple[int, int, str]:
        broker = EventBroker()
        first = await broker.publish(StreamEvent(type="first", session_id="s1"))
        second = await broker.publish(StreamEvent(type="second", session_id="s1"))

        subscription = broker.subscribe(after_id=first.id)
        replayed = await anext(subscription)
        await subscription.aclose()
        return replayed.id, second.id, replayed.type

    replayed_id, second_id, event_type = asyncio.run(scenario())
    assert replayed_id == second_id
    assert event_type == "second"
