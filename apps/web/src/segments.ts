import type { Segment, StreamEvent } from "./types";

export function applyStreamEvent(previous: Segment[], event: StreamEvent): Segment[] {
  const segmentId = event.data.segment_id;
  if (typeof segmentId !== "string") return previous;
  const streamSegmentId = `${event.session_id}:${segmentId}`;

  const index = previous.findIndex((segment) => segment.id === streamSegmentId);
  const current: Segment = index >= 0
    ? previous[index]
    : {
        id: streamSegmentId,
        revision: 0,
        startMs: 0,
        endMs: 0,
        language: "unknown",
        text: "",
        grammar: [],
      };
  const revision = typeof event.data.revision === "number" ? event.data.revision : 1;
  if (revision < current.revision) return previous;

  let next = { ...current, revision };
  if (event.type === "transcript.partial" || event.type === "transcript.final") {
    next = {
      ...next,
      startMs: Number(event.data.start_ms ?? current.startMs),
      endMs: Number(event.data.end_ms ?? current.endMs),
      language: String(event.data.language ?? current.language),
      text: String(event.data.text ?? current.text),
      latencyMs: Number(event.data.latency_ms ?? current.latencyMs),
    };
  } else if (event.type === "translation.final") {
    next = { ...next, translation: String(event.data.text ?? "") };
  } else if (event.type === "grammar.suggested") {
    next = { ...next, grammar: Array.isArray(event.data.items) ? event.data.items : [] };
  } else {
    return previous;
  }

  if (index < 0) return [...previous, next];
  const copy = previous.slice();
  copy[index] = next;
  return copy;
}
