import numpy as np
import pytest

from frames import AudioFormat, AudioFrame


def test_audio_format_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        AudioFormat(sample_rate=0, channels=1)
    with pytest.raises(ValueError):
        AudioFormat(sample_rate=48_000, channels=0)


def test_audio_frame_reports_frame_count() -> None:
    frame = AudioFrame(
        sequence=0,
        captured_at_ns=1,
        pcm=np.zeros((4_800, 1), dtype=np.int16),
    )
    assert frame.frame_count == 4_800
