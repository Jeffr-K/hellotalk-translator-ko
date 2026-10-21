from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InteractionType(StrEnum):
    OVERLAP = "overlap"
    BACKCHANNEL = "backchannel"
    INTERRUPTION = "interruption"
    FAILED_INTERRUPTION = "failed_interruption"
    SIMULTANEOUS_START = "simultaneous_start"


@dataclass(frozen=True, slots=True)
class SpeechTurn:
    turn_id: str
    speaker_id: str
    start_ms: int
    end_ms: int
    text: str = ""

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("start_ms must not be negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True, slots=True)
class Interaction:
    type: InteractionType
    actor_speaker_id: str | None
    target_speaker_id: str | None
    at_ms: int
    overlap_ms: int


def overlap_ms(first: SpeechTurn, second: SpeechTurn) -> int:
    return max(0, min(first.end_ms, second.end_ms) - max(first.start_ms, second.start_ms))


def classify_interaction(
    first: SpeechTurn,
    second: SpeechTurn,
    *,
    simultaneous_start_ms: int = 250,
    backchannel_max_ms: int = 1_000,
    minimum_overlap_ms: int = 150,
) -> Interaction | None:
    """Classify the temporal relationship of two known speaker turns.

    This classifies ground-truth or already-diarized turns. It does not infer speakers
    from mixed audio.
    """
    if first.speaker_id == second.speaker_id:
        return None

    overlap = overlap_ms(first, second)
    if overlap < minimum_overlap_ms:
        return None

    if abs(first.start_ms - second.start_ms) <= simultaneous_start_ms:
        return Interaction(
            type=InteractionType.SIMULTANEOUS_START,
            actor_speaker_id=None,
            target_speaker_id=None,
            at_ms=max(first.start_ms, second.start_ms),
            overlap_ms=overlap,
        )

    target, actor = (first, second) if first.start_ms < second.start_ms else (second, first)
    if actor.duration_ms <= backchannel_max_ms and target.end_ms > actor.end_ms:
        interaction_type = InteractionType.BACKCHANNEL
    elif actor.end_ms > target.end_ms:
        interaction_type = InteractionType.INTERRUPTION
    elif target.end_ms > actor.end_ms:
        interaction_type = InteractionType.FAILED_INTERRUPTION
    else:
        interaction_type = InteractionType.OVERLAP

    return Interaction(
        type=interaction_type,
        actor_speaker_id=actor.speaker_id,
        target_speaker_id=target.speaker_id,
        at_ms=actor.start_ms,
        overlap_ms=overlap,
    )
