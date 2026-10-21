import { describe, expect, it } from "vitest";

import { applyStreamEvent } from "./segments";
import type { StreamEvent } from "./types";

function event(type: string, data: Record<string, unknown>): StreamEvent {
  return { id: 1, type, session_id: "s1", occurred_at: "2026-01-01", data };
}

describe("applyStreamEvent", () => {
  it("merges transcript, translation and grammar by segment id", () => {
    let state = applyStreamEvent([], event("transcript.final", {
      segment_id: "window-1", revision: 1, start_ms: 0, end_ms: 4000,
      language: "en", text: "I use Rust.", latency_ms: 500,
    }));
    state = applyStreamEvent(state, event("translation.final", {
      segment_id: "window-1", revision: 1, text: "저는 Rust를 사용합니다.",
    }));
    state = applyStreamEvent(state, event("grammar.suggested", {
      segment_id: "window-1", revision: 1,
      items: [{ pattern: "use", explanation: "사용하다" }],
    }));

    expect(state).toHaveLength(1);
    expect(state[0].translation).toContain("Rust");
    expect(state[0].grammar[0].pattern).toBe("use");
  });

  it("ignores stale revisions", () => {
    const current = applyStreamEvent([], event("transcript.final", {
      segment_id: "window-1", revision: 2, text: "new",
    }));
    const stale = applyStreamEvent(current, event("transcript.partial", {
      segment_id: "window-1", revision: 1, text: "old",
    }));
    expect(stale).toBe(current);
  });
});
