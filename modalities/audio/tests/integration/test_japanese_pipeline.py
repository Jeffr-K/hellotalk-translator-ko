from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from live import LiveConfig, transcribe_window, translate_to_korean

pytestmark = pytest.mark.integration

JAPANESE_TEXT = (
    "こんにちは。私はソフトウェア開発者です。"
    "Rustを使っています。日本の文化が大好きです。"
)


def _integration_enabled() -> bool:
    return os.environ.get("RUN_AUDIO_INTEGRATION") == "1"


def _read_pcm16_wav(path: Path) -> np.ndarray:
    import wave

    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16_000
        pcm = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
    return pcm.reshape(-1, 1)


@pytest.mark.skipif(not _integration_enabled(), reason="set RUN_AUDIO_INTEGRATION=1")
def test_japanese_tts_to_korean_translation(tmp_path: Path) -> None:
    for executable in ("say", "ffmpeg", "whisper-cli"):
        assert shutil.which(executable), f"missing executable: {executable}"

    project_dir = Path(__file__).resolve().parents[2]
    model = Path(
        os.environ.get("AUDIO_WHISPER_MODEL", project_dir / "models/ggml-base.bin")
    )
    assert model.exists(), f"missing Whisper model: {model}"

    aiff_path = tmp_path / "japanese.aiff"
    wav_path = tmp_path / "japanese.wav"
    subprocess.run(
        ["say", "-v", "Kyoko", "-r", "165", "-o", str(aiff_path), JAPANESE_TEXT],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(aiff_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        check=True,
    )

    config = LiveConfig(
        device=None,
        model=model,
        archive=tmp_path / "unused.wav",
        sample_rate=16_000,
    )
    transcript = transcribe_window(_read_pcm16_wav(wav_path), config)
    assert transcript.language == "ja"
    assert "日本" in transcript.text
    assert "文化" in transcript.text

    translation, elapsed = translate_to_korean(transcript.text, config)
    assert "일본" in translation
    assert "문화" in translation
    assert elapsed < 30
