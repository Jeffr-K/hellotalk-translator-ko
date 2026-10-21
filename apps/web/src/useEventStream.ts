import { useEffect, useState } from "react";

import { applyStreamEvent } from "./segments";
import type { Segment, StreamEvent } from "./types";

const EVENT_TYPES = [
  "session.started",
  "session.stopped",
  "transcript.partial",
  "transcript.final",
  "translation.final",
  "grammar.suggested",
  "pipeline.warning",
] as const;

export function useEventStream(url = "/api/events") {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [connected, setConnected] = useState(false);
  const [warning, setWarning] = useState<string>();

  useEffect(() => {
    const source = new EventSource(url);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    const receive = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as StreamEvent;
      if (event.type === "session.started") {
        setSegments([]);
        setWarning(undefined);
        return;
      }
      if (event.type === "pipeline.warning") {
        setWarning(String(event.data.message ?? "알 수 없는 파이프라인 오류"));
        return;
      }
      setSegments((current) => applyStreamEvent(current, event));
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive as EventListener);
    return () => source.close();
  }, [url]);

  return { segments, connected, warning, clear: () => setSegments([]) };
}
