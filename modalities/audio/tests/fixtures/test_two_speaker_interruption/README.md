# test_two_speaker_interruption

두 화자의 발화가 겹친 뒤 두 번째 화자가 발언권을 이어가는 성공한 끼어들기 fixture다.

```text
Speaker A: 0ms  ─────────────────────x 4500ms
Speaker B:                 3500ms ───────────────── 6500ms
                            overlap: 1000ms
```

구성:

- `scenario.yaml`: 화자, 발화, 정답 시간 구간과 기대 interaction
- `build_fixture.py`: macOS TTS로 화자별 트랙과 mono 혼합 WAV 생성
- `test_fixture.py`: 시간축 분류 단위 테스트와 실제 오디오 생성 통합 테스트
- `artifacts/`: 테스트 실행 시 생성되며 Git에는 포함하지 않음

실제 오디오 fixture 생성 테스트:

```bash
RUN_AUDIO_INTEGRATION=1 \
  uv run pytest tests/fixtures/test_two_speaker_interruption -s
```

이 fixture는 알려진 화자 트랙으로 타임라인과 정답 데이터를 검증한다. 혼합 mono 신호에서 화자를 자동 추론하는 diarization 테스트는 아니다.
