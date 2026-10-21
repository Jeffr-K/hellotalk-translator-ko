from pathlib import Path

import numpy as np
import pytest

from live import LiveConfig, is_duplicate, is_non_speech, normalize_text, pcm_rms


def config(**changes: object) -> LiveConfig:
    values = {
        "device": None,
        "model": Path("model.bin"),
        "archive": Path("archive.wav"),
    }
    values.update(changes)
    return LiveConfig(**values)  # type: ignore[arg-type]


def test_live_config_calculates_step() -> None:
    assert config(window_seconds=4, overlap_seconds=1).step_seconds == 3


@pytest.mark.parametrize(
    ("window", "overlap"),
    [(0, 0), (4, -1), (4, 4), (4, 5)],
)
def test_live_config_rejects_invalid_windows(window: float, overlap: float) -> None:
    with pytest.raises(ValueError):
        config(window_seconds=window, overlap_seconds=overlap)


def test_pcm_rms() -> None:
    assert pcm_rms(np.zeros((100, 1), dtype=np.int16)) == 0
    assert 0.49 < pcm_rms(np.full((100, 1), 16_384, dtype=np.int16)) < 0.51


def test_duplicate_detection_handles_punctuation_and_overlap() -> None:
    assert normalize_text("Hello, world!") == "helloworld"
    assert is_duplicate("Hello, world!", "hello world")
    assert is_duplicate(
        "I am a software developer",
        "I am a software developer, Rust developer",
    )
    assert not is_duplicate("Hello, world", "I love Japanese cultures")


@pytest.mark.parametrize("text", ["(upbeat music)", "[Music]", "<silence>"])
def test_non_speech_markers_are_ignored(text: str) -> None:
    assert is_non_speech(text)


def test_spoken_text_is_not_treated_as_non_speech() -> None:
    assert not is_non_speech("I love Japanese cultures.")
