import { useEffect, useRef, useState } from "react";

import type { AudioDevice, Segment } from "./types";
import { useEventStream } from "./useEventStream";
import "./styles.css";

const LANGUAGE_MODES = [
  { value: "auto", label: "AUTO" },
  { value: "ja", label: "JP" },
  { value: "ko", label: "KO" },
  { value: "en", label: "EN" },
] as const;

function formatTime(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(totalSeconds / 60).toString().padStart(2, "0")}:${(totalSeconds % 60).toString().padStart(2, "0")}`;
}

function TranscriptMessage({ segment }: { segment: Segment }) {
  const isKorean = segment.language === "ko";

  return (
    <article className={`message ${isKorean ? "korean" : "foreign"}`}>
      <div className="avatar" aria-hidden="true">{segment.language.toUpperCase()}</div>
      <div className="message-content">
        <div className="message-meta">
          <strong>{isKorean ? "한국어" : "외국어 음성"}</strong>
          <time>{formatTime(segment.startMs)}</time>
          {segment.latencyMs ? <span>{(segment.latencyMs / 1000).toFixed(1)}s</span> : null}
        </div>
        <div className="bubble">
          <p className="source-text">{segment.text || "분석 중…"}</p>
          {segment.translation ? <p className="translation">{segment.translation}</p> : null}
          {!isKorean && !segment.translation ? <p className="pending">번역 중…</p> : null}
        </div>
        {segment.grammar.length > 0 ? (
          <details className="learning-notes">
            <summary>문법 추천 {segment.grammar.length}개</summary>
            <ul>
              {segment.grammar.map((note) => (
                <li key={`${segment.id}-${note.pattern}`}>
                  <strong>{note.pattern}</strong>
                  <span>{note.explanation}</span>
                  {note.example ? <code>{note.example}</code> : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </article>
  );
}

export default function App() {
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [device, setDevice] = useState("");
  const [language, setLanguage] = useState("auto");
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const { segments, connected, warning, clear } = useEventStream();
  const feedEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/devices")
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("입력 장치를 읽지 못했습니다.")))
      .then((items: AudioDevice[]) => {
        setDevices(items);
        if (items[0]) setDevice(String(items[0].id));
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [segments.length]);

  async function toggleSession() {
    setBusy(true);
    setError(undefined);
    try {
      const response = running
        ? await fetch("/api/sessions/stop", { method: "POST" })
        : await fetch("/api/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device: Number(device), language }),
          });
      if (!response.ok) throw new Error((await response.json()).detail ?? "요청에 실패했습니다.");
      setRunning(!running);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function publishDemo() {
    await fetch("/api/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "I have been learning Rust for two years." }),
    });
  }

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">LIVE LANGUAGE ROOM</p>
          <h1>흘러가는 대화를<br />배움의 순간으로.</h1>
          <p className="lede">Mac 오디오를 실시간으로 듣고, 원문과 번역 그리고 지금 써볼 문법을 한 화면에 정리합니다.</p>
        </div>
        <div className={`connection ${connected ? "online" : ""}`}>
          <i /> SSE {connected ? "연결됨" : "재연결 중"}
        </div>
      </header>

      <section className="controls" aria-label="실시간 입력 제어">
        <label>
          AUDIO INPUT
          <select value={device} onChange={(event) => setDevice(event.target.value)} disabled={running}>
            {devices.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.channels}ch</option>)}
          </select>
        </label>
        <fieldset className="language-mode" disabled={running}>
          <legend>LANGUAGE</legend>
          <div>
            {LANGUAGE_MODES.map((mode) => (
              <button
                type="button"
                key={mode.value}
                className={language === mode.value ? "active" : ""}
                onClick={() => setLanguage(mode.value)}
                aria-pressed={language === mode.value}
              >
                {mode.label}
              </button>
            ))}
          </div>
        </fieldset>
        <button className={running ? "stop" : "start"} onClick={toggleSession} disabled={busy || (!running && !device)}>
          {busy ? "준비 중…" : running ? "세션 종료" : "실시간 학습 시작"}
        </button>
        <button className="quiet" onClick={publishDemo}>화면 테스트</button>
        <button className="quiet" onClick={clear}>기록 지우기</button>
      </section>

      {error || warning ? <aside className="warning">{error ?? warning}</aside> : null}

      <section className="workspace">
        <div className="section-heading">
          <div><span>LIVE TRANSCRIPT</span><h2>지금 들리는 대화</h2></div>
          <b>{segments.length} messages</b>
        </div>
        <div className="feed" aria-live="polite">
          {segments.length > 0 ? <div className="timeline-label"><span>실시간 대화</span></div> : null}
          {segments.length > 0
            ? segments.map((segment) => <TranscriptMessage key={segment.id} segment={segment} />)
            : <div className="empty"><span>〰</span><p>입력을 시작하면 대화가 이곳에 나타납니다.</p></div>}
          <div ref={feedEndRef} />
        </div>
      </section>
    </main>
  );
}
