from __future__ import annotations

import json
import urllib.request

from pydantic import BaseModel, Field


class GrammarNote(BaseModel):
    pattern: str
    explanation: str
    example: str | None = None


class LearningResult(BaseModel):
    translation: str
    grammar: list[GrammarNote] = Field(default_factory=list, max_length=3)


class OllamaLearningAgent:
    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:11434/api/generate",
        model: str = "qwen3:4b",
        timeout: float = 30,
    ) -> None:
        self._url = url
        self._model = model
        self._timeout = timeout

    def analyze(self, text: str, language: str) -> LearningResult:
        schema = LearningResult.model_json_schema()
        body = json.dumps(
            {
                "model": self._model,
                "system": (
                    "You are a precise language-learning assistant. Return only JSON matching "
                    "the schema. Translate into natural Korean. Recommend at most three useful "
                    "grammar points that are actually present in the source. Preserve technical "
                    "terms, programming language names, product names, and proper nouns in their "
                    "original English or Japanese spelling. Do not invent missing context."
                ),
                "prompt": f"Source language: {language}\nSource text: {text}",
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 512},
            },
            ensure_ascii=False,
        ).encode()
        request = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            result = json.load(response)
        return LearningResult.model_validate_json(result["response"])
