from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Pcm16 = NDArray[np.int16]

# slots=True
# 일반적으로 인스턴스당 메모리 사용량이 줄어든다.
# 속성 접근 속도가 약간 개선될 수 있다.
# 선언되지 않은 속성을 동적으로 추가할 수 없다.
# 일반적인 경우 인스턴스 __dict__ 가 생성되지 않는다.
# frozen=True
# 인스턴스 속성을 변경할 수 없다.
# 만약 바꾸고 싶다면, replace() 함수를 사용해야 한다.
# 결론적으로, 음성 스트리밍 시스템에서 AudioChunk, TranscriptSegment, SpeechEvent처럼 생성 후 내용이 바뀌지 않아야 하는 데이터 객체에는 @dataclass(slots=True, frozen=True) 조합을 추천한다.
# 반대로 SessionState, RingBuffer, StreamingContext처럼 내부 상태를 지속적으로 갱신해야 하는 객체에는 slots=True만 적용하거나 일반 클래스를 사용하는 편이 적합하다.
@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int
    channels: int
    sample_format: str = "s16le"

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.sample_format != "s16le":
            raise ValueError("the PoC currently supports only s16le")


@dataclass(frozen=True, slots=True)
class AudioFrame:
    sequence: int
    captured_at_ns: int
    pcm: Pcm16
    callback_status: str | None = None

    @property
    def frame_count(self) -> int:
        return int(self.pcm.shape[0])
