from __future__ import annotations

import io
import json

from learning_agent import OllamaLearningAgent


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_learning_agent_validates_translation_and_grammar(monkeypatch) -> None:
    response = {
        "response": json.dumps(
            {
                "translation": "저는 Rust 개발자입니다.",
                "grammar": [
                    {
                        "pattern": "I am + occupation",
                        "explanation": "직업을 말하는 표현",
                        "example": "I am a Rust developer.",
                    }
                ],
            }
        )
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(json.dumps(response).encode()),
    )

    result = OllamaLearningAgent().analyze("I am a Rust developer.", "en")

    assert result.translation == "저는 Rust 개발자입니다."
    assert result.grammar[0].pattern == "I am + occupation"
