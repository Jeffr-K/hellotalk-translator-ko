from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

FIXTURE_DIR = Path(__file__).resolve().parent
SCENARIO_PATH = FIXTURE_DIR / "scenario.yaml"


def load_scenario() -> dict[str, Any]:
    return yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8"))


def build_fixture(output_dir: Path) -> dict[str, Path]:
    scenario = load_scenario()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_paths: dict[str, Path] = {}

    turns_by_speaker = {turn["speaker_id"]: turn for turn in scenario["turns"]}
    for speaker_id, speaker in scenario["speakers"].items():
        turn = turns_by_speaker[speaker_id]
        source_path = output_dir / f"{speaker_id}-source.aiff"
        subprocess.run(
            [
                "say",
                "-v",
                speaker["voice"],
                "-r",
                "165",
                "-o",
                str(source_path),
                turn["text"],
            ],
            check=True,
        )
        source_paths[speaker_id] = source_path

    duration_seconds = scenario["duration_ms"] / 1000
    filters: list[str] = []
    labels: list[str] = []
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for index, turn in enumerate(scenario["turns"]):
        command.extend(["-i", str(source_paths[turn["speaker_id"]])])
        turn_duration = (turn["end_ms"] - turn["start_ms"]) / 1000
        delay = int(turn["start_ms"])
        label = f"speaker{index}"
        filters.append(
            f"[{index}:a]aresample={scenario['sample_rate']},"
            f"atrim=duration={turn_duration},apad,atrim=duration={turn_duration},"
            f"adelay={delay}:all=1[{label}]"
        )
        labels.append(f"[{label}]")

    mixed_path = output_dir / "mixed.wav"
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"atrim=duration={duration_seconds}[mixed]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[mixed]",
            "-ar",
            str(scenario["sample_rate"]),
            "-ac",
            str(scenario["channels"]),
            "-c:a",
            "pcm_s16le",
            str(mixed_path),
        ]
    )
    subprocess.run(command, check=True)
    return {"mixed": mixed_path, **source_paths}


if __name__ == "__main__":
    generated = build_fixture(FIXTURE_DIR / "artifacts")
    for name, path in generated.items():
        print(f"{name}: {path}")
