from __future__ import annotations

import os
import shutil
import wave
from pathlib import Path

import pytest

from timeline import InteractionType, SpeechTurn, classify_interaction

from .build_fixture import build_fixture, load_scenario


def _turns() -> tuple[SpeechTurn, SpeechTurn]:
    scenario = load_scenario()
    turns = [
        SpeechTurn(
            turn_id=turn["id"],
            speaker_id=turn["speaker_id"],
            start_ms=turn["start_ms"],
            end_ms=turn["end_ms"],
            text=turn["text"],
        )
        for turn in scenario["turns"]
    ]
    return turns[0], turns[1]


def test_ground_truth_is_a_successful_interruption() -> None:
    first, second = _turns()
    interaction = classify_interaction(first, second)

    assert interaction is not None
    assert interaction.type is InteractionType.INTERRUPTION
    assert interaction.actor_speaker_id == "speaker-b"
    assert interaction.target_speaker_id == "speaker-a"
    assert interaction.at_ms == 3500
    assert interaction.overlap_ms == 1000


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_AUDIO_INTEGRATION") != "1",
    reason="set RUN_AUDIO_INTEGRATION=1",
)
def test_generated_mixed_audio_matches_scenario_duration(tmp_path: Path) -> None:
    assert shutil.which("say")
    assert shutil.which("ffmpeg")

    generated = build_fixture(tmp_path)
    with wave.open(str(generated["mixed"]), "rb") as mixed:
        duration_ms = round(mixed.getnframes() / mixed.getframerate() * 1000)
        assert mixed.getframerate() == 16_000
        assert mixed.getnchannels() == 1
        assert mixed.getsampwidth() == 2
        assert duration_ms == 6500
