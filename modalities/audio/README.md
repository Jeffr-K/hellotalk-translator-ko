# Audio Modality

## 개요

`audio`는 iPhone의 HelloTalk 보이스룸/라이브룸에서 현재 재생되는 음성을 Mac이 실시간으로 받아 후속 처리에 전달하는 독립 프로젝트다.

첫 번째 PoC에서는 녹화 파일을 기다리지 않는다. iPhone의 출력이 발생하는 동안 Mac 입력을 계속 수집하고, 짧은 버퍼 단위로 노이즈 완화와 STT 파이프라인에 전달한다. 사용자가 대화 중에 바로 이해하고 학습한 표현을 사용할 수 있을 정도의 낮은 지연이 가장 중요한 성공 기준이다.

## PoC 목표

```text
iPhone room playback
        ↓
Mac real-time audio input
        ↓
raw capture + timestamp
        ├── raw stream preservation
        └── non-destructive enhancement
                  ↓
             live STT consumer
```

PoC가 검증할 내용은 다음과 같다.

1. Mac이 iPhone 출력을 연속적인 입력 스트림으로 받을 수 있는가?
2. 지지직거림이 어느 신호 구간에서 발생하는가?
3. 원본을 유지하면서 STT용 파생 신호의 잡음을 줄일 수 있는가?
4. 입력부터 downstream 전달까지 요구 지연을 만족하는가?
5. 느린 분석 소비자가 있어도 캡처 프레임이 유실되지 않는가?

## 현재 범위

### 포함

- macOS 오디오 입력 장치 탐색과 포맷 확인
- 입력 장치 선택
- 실시간 PCM 캡처
- timestamp와 sequence 부여
- raw ring buffer와 저장 소비자
- STT용 mono/16 kHz 파생 스트림
- 보수적인 실시간 노이즈 완화
- 입력 레벨, clipping, queue depth, 유실 프레임 계측
- 실시간 소비자에게 전달할 프레임 계약

### 제외

- 화면 기록 파일을 이용한 정밀 재처리
- 오프라인 ASR과 화자 분리
- 퀴즈 생성과 장기 학습 커리큘럼
- 화면/OCR 입력
- iPhone으로 로컬 마이크를 다시 보내는 양방향 mix-minus

양방향 참여와 정밀 경로는 수신 전용 실시간 입력이 검증된 뒤 별도 마일스톤으로 추가한다.

## 입력 방식

PoC는 다음 두 방식 중 실제 검증을 통과한 방식을 사용한다.

### A. 공간 음향 캡처

```text
iPhone speaker → air → Mac microphone
```

- 즉시 실험할 수 있다.
- 주변 소음, 반사음, 기기 위치, 스피커 왜곡에 영향을 받는다.
- 실시간 파이프라인과 지연 검증에는 사용할 수 있다.

### B. 전기적 직접 입력

```text
iPhone output → compatible audio path → CoreAudio input
```

- 주변 소음과 공간 반사의 영향을 줄일 수 있다.
- iPhone 단자, 어댑터, line level, Mac 입력 장치의 호환성 검증이 필요하다.
- 장비가 준비되면 장기적으로 선호하는 입력 방식이다.

두 방식은 캡처 구현 이후에는 동일한 PCM 프레임 계약을 사용해야 한다. 장치 차이가 downstream 코드에 노출되어서는 안 된다.

## raw와 enhanced 스트림

| 스트림 | 설명 | 소비자 |
|---|---|---|
| `audio.raw` | Mac 입력에서 받은 변경되지 않은 PCM | 저장, 장애 분석, 재처리 |
| `audio.enhanced` | 노이즈 완화와 리샘플링을 적용한 파생 PCM | VAD, 실시간 STT |

노이즈 제거는 캡처 callback 안에서 실행하지 않는다. callback은 프레임 복사, 순번 부여, timestamp 기록까지만 수행하고 즉시 반환한다.

## 프레임 계약 초안

메타데이터와 PCM payload를 함께 전달한다.

```json
{
  "type": "audio.raw",
  "session_id": "session-001",
  "source_id": "iphone-room",
  "sequence": 1242,
  "captured_at_ns": 8123456789000,
  "sample_rate": 48000,
  "channels": 1,
  "sample_format": "s16le",
  "frame_count": 4800,
  "clipped_samples": 0,
  "discontinuity": false
}
```

- `captured_at_ns`는 세션의 monotonic clock 기준이다.
- `sequence`가 연속되지 않으면 프레임 유실로 간주한다.
- 장치가 제공하는 실제 sample rate와 channel count를 기록한다.
- 48 kHz mono를 장치에 강제하지 않고 실제 포맷으로 수집한 뒤 파생 스트림에서 변환한다.

## 지지직거림 진단 순서

노이즈 제거 모델을 적용하기 전에 발생 위치를 분리한다.

1. iPhone 자체 스피커 또는 이어폰 출력에서 이미 발생하는지 듣는다.
2. Mac 입력의 raw PCM을 아무 처리 없이 재생한다.
3. clipping과 입력 gain을 확인한다.
4. PCM dtype, channel layout, sample rate 해석을 확인한다.
5. callback status와 sequence gap을 확인한다.
6. 전기적 연결이라면 케이블, TRS/TRRS, line/mic level, ground noise를 확인한다.
7. 위 문제가 없을 때만 실시간 denoiser를 비교한다.

지지직거림이 clipping이나 포맷 오류인 경우 denoiser로 감추지 않고 캡처 설정을 수정한다.

## 초기 지연 예산

| 구간 | 목표 |
|---|---:|
| 장치 callback 블록 | 20–100 ms |
| ring buffer 전달 | 10 ms 이하 |
| 리샘플링·노이즈 완화 | 100 ms 이하 |
| VAD 발화 판단 | 200–500 ms |
| live ASR 갱신 | 약 1초 간격 |
| 입력부터 partial 자막 | 2초 이내 목표, 최대 3초 |

이 수치는 보장값이 아니라 PoC 합격 여부를 판단하기 위한 초기 목표다. 각 구간의 실제 시간을 별도로 계측한다.

## 성공 기준

- 30분 연속 캡처 동안 프로세스가 중단되지 않는다.
- raw 저장 경로의 sequence gap이 0이다.
- 캡처 callback에서 queue overflow가 발생하지 않는다.
- 정상 입력에서 digital clipping이 발생하지 않는다.
- STT 소비자를 느리게 만들어도 raw 캡처가 유실되지 않는다.
- partial 자막이 입력 후 3초 이내 표시된다.
- enhanced 스트림이 raw보다 STT 정확도를 악화시키면 즉시 우회할 수 있다.

## 예정 구조

구현을 시작할 때 다음 구조를 기준으로 하되, 검증되지 않은 모듈은 미리 만들지 않는다.

```text
modalities/audio/
├── README.md
├── pyproject.toml
├── src/
│   ├── devices.py
│   ├── capture.py
│   ├── frames.py
│   ├── live.py
│   └── metrics.py
└── tests/
```

## 첫 번째 검증 단계

1. Python 버전과 macOS 마이크 권한을 확정한다.
2. CoreAudio 입력 장치와 지원 포맷을 출력한다.
3. Mac 기본 입력으로 30초 raw WAV를 만든다.
4. iPhone에서 음성 샘플을 재생하며 peak, RMS, clipping, drop을 기록한다.
5. raw WAV를 들어 지지직거림을 재현하고 발생 지점을 분류한다.
6. raw 캡처가 정상일 때만 enhancement와 실시간 STT를 연결한다.

현재 확인된 개발 환경에는 FFmpeg 7.1.1과 프로젝트 가상환경의 `sounddevice`가 준비되어 있다. CoreAudio 입력 장치 조회도 성공했으며, 실제 장치 번호와 기본 입력은 `audio-devices`로 다시 확인할 수 있다.

## 개발 명령

```bash
cd modalities/audio
uv sync --extra dev
uv run audio-devices
uv run audio-capture --device 4 --duration 30 \
  --output recordings/input-poc.wav
uv run live-transcribe --device 4
uv run pytest
uv run ruff check .
```

장치 번호는 시스템마다 달라지므로 `audio-devices` 결과를 먼저 확인한다. 최초 캡처 때 macOS가 마이크 권한을 요청하면 실행에 사용한 터미널에 권한을 허용한 뒤 다시 시도한다.

### 실시간 전사·번역

```bash
uv run live-transcribe \
  --device 4 \
  --window 4 \
  --overlap 1 \
  --archive recordings/live-session.wav
```

CLI는 4초 창을 3초마다 분석한다. 조용한 창은 건너뛰고, 한국어가 아닌 발화는 Ollama의 `qwen3:4b`를 이용해 한국어 JSON으로 번역한다. 전체 입력은 분석 창과 별개로 `--archive` WAV에 연속 저장된다. 현재 PoC에서는 Whisper 프로세스를 창마다 실행하므로 모델을 상주시키는 구현보다 느리다.

## 두 개의 분석 파이프라인

파일 기반 PoC는 삭제하지 않고 오프라인 호환 경로로 유지한다.

```text
offline / compatibility
WAV path → FFmpeg → whisper-cli → JSON
```

새 실시간 코어는 파일 경로가 아닌 메모리 PCM 계약을 사용한다.

```text
AudioChunk[int16 PCM]
→ in-memory mono conversion
→ in-memory resampling
→ overlapping AudioWindow[float32 PCM]
→ persistent InMemoryTranscriber
→ TranscriptEvent
```

`src/streaming_pipeline.py`는 WAV, FFmpeg, subprocess를 사용하지 않는다. 실제 Whisper binding은 `InMemoryTranscriber` 계약 뒤에 연결한다. 원본 녹음은 `AudioArchive` 소비자로 병렬 연결하며 분석 성공 여부와 무관하게 동작해야 한다.

현재 `resample_linear`는 연결점과 테스트를 검증하기 위한 reference 구현이다. 실제 음성 품질 경로에서는 동일한 `AudioWindow` 계약을 유지하면서 stateful band-limited resampler로 교체해야 한다.

실시간 경로는 현재 `soxr.ResampleStream`을 사용한다. `resample_linear`는 단위 테스트와 비교 실험을 위한 reference 함수로만 남아 있다.

## 최종 PoC: SSE와 React

```text
Mac audio input
→ AudioChunk (PCM, memory)
→ stateful soxr resampling
→ 4초 window / 1초 overlap
→ persistent whisper.cpp model
→ transcript.final SSE
→ React transcript card
             └→ async Ollama translation + grammar.suggested SSE
```

백엔드와 웹을 각각 실행한다.

```bash
# terminal 1
cd modalities/audio
uv run uvicorn api:app --reload --host 127.0.0.1 --port 8000

# terminal 2
cd apps/web
npm install
npm run dev
```

브라우저에서 `http://127.0.0.1:5173`을 열고 입력 장치를 고른다. `화면 테스트`는 마이크와 모델을 시작하지 않고 transcript/translation/grammar SSE 계약만 검증한다. 실제 입력은 `실시간 학습 시작`을 누르면 된다. 모델의 기본 위치는 `modalities/audio/models/ggml-base.bin`이다.

SSE 이벤트는 `session.started`, `transcript.final`, `translation.final`, `grammar.suggested`, `pipeline.warning`, `session.stopped`를 사용한다. 번역과 문법 분석 실패는 이미 게시된 자막을 취소하지 않는다.

### 실제 일본어 통합 테스트

일반 테스트는 외부 모델 없이 실행된다. macOS TTS, Whisper 모델, Ollama까지 포함한 실제 테스트는 명시적으로 활성화한다.

```bash
RUN_AUDIO_INTEGRATION=1 \
  uv run pytest tests/integration/test_japanese_pipeline.py -s
```

테스트는 Kyoko 음성으로 일본어 fixture를 생성하고, 자동 언어 감지 결과가 `ja`인지와 전사·한국어 번역에 `일본 문화`라는 핵심 의미가 유지되는지 확인한다. 소형 ASR 모델의 표기 변형 가능성 때문에 전체 문장의 완전 일치는 요구하지 않는다.
