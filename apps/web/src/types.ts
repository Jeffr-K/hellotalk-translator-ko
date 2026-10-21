export type GrammarNote = {
  pattern: string;
  explanation: string;
  example?: string | null;
};

export type Segment = {
  id: string;
  revision: number;
  startMs: number;
  endMs: number;
  language: string;
  text: string;
  translation?: string;
  grammar: GrammarNote[];
  latencyMs?: number;
};

export type StreamEvent = {
  id: number;
  type: string;
  session_id: string;
  occurred_at: string;
  data: Record<string, unknown>;
};

export type AudioDevice = {
  id: number;
  name: string;
  channels: number;
  sample_rate: number;
};
