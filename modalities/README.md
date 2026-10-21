# Modalities

`modalities`는 외부 세계의 신호를 수집해 시스템 내부에서 사용할 수 있는 표준 입력으로 변환하는 모노레포 영역이다.

여기서 modality는 AI 모델의 종류가 아니라 **입력 정보의 형태와 수집 경로**를 뜻한다. 오디오, 화면, 이미지, 사용자 이벤트는 서로 다른 속도와 시간 기준을 가지므로 각각 독립된 프로젝트로 구현한다.

## 책임

각 modality 프로젝트는 다음을 책임진다.

- 운영체제나 장치에서 입력을 수집한다.
- 입력에 순번과 monotonic timestamp를 부여한다.
- 수집한 원본을 변경하지 않고 보존 가능한 형태로 전달한다.
- 실시간 소비자를 위한 파생 스트림을 생성한다.
- 지연, 유실, 불연속, 입력 품질을 계측한다.
- 다른 서비스가 장치별 세부 사항을 알 필요가 없도록 공통 이벤트 계약을 제공한다.

다음 작업은 modality의 책임이 아니다.

- 최종 자막과 번역 생성
- 학습 자료와 퀴즈 생성
- 세션의 장기 보관 정책 결정
- 프론트엔드 표시 형식 결정
- 원본을 덮어쓰는 방식의 노이즈 제거

## 프로젝트 구성

```text
modalities/
├── README.md
└── audio/
    └── README.md
```

향후 실제 필요가 확인되면 다음과 같이 확장할 수 있다.

```text
modalities/
├── audio/          # 실시간 음성 입력
├── screen/         # 화면 프레임과 OCR 문맥
└── user-events/    # 북마크, 수동 화자 표시, 학습자 입력
```

필요가 확인되지 않은 modality를 미리 구현하지 않는다. 현재 PoC 범위는 `audio`뿐이다.

## 공통 원칙

### 원본과 파생 입력 분리

```text
device input
  └── raw input
      ├── archive/diagnostics
      └── derived input
          └── downstream consumer
```

노이즈 제거, 리샘플링, 채널 혼합은 모두 파생 처리다. 원본 입력을 덮어쓰지 않는다.

### 시간 기준

- 실시간 정렬에는 monotonic clock을 사용한다.
- wall-clock은 세션 메타데이터로 별도 보존한다.
- 각 입력 단위에는 `session_id`, `source_id`, `sequence`, `captured_at_ns`가 있어야 한다.
- 서로 다른 장치를 함께 사용할 때는 clock drift를 측정해야 한다.

### 장애 격리

- 느린 소비자가 캡처 callback을 막아서는 안 된다.
- 분석 스트림이 밀려도 원본 수집 경로는 계속 동작해야 한다.
- 유실과 불연속을 숨기지 않고 이벤트와 메트릭으로 기록한다.
- 파생 처리 실패는 raw input을 손상시키지 않아야 한다.

## 현재 프로젝트

- [`audio`](./audio/README.md): iPhone에서 재생되는 보이스룸/라이브룸 음성을 Mac이 실시간으로 수집하기 위한 입력 프로젝트

전체 시스템 설계는 [`docs/iphone-mac-ai-voice-learning-agent.md`](../docs/iphone-mac-ai-voice-learning-agent.md), 입력 계층의 상세 설계는 [`docs/multimodal-input-architecture.md`](../docs/multimodal-input-architecture.md)를 참고한다.
