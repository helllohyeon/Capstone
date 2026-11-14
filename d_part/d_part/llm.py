"""LLM 교체형 인터페이스 (명세서 §1.4, §1.5).

LLM_PROVIDER 환경변수로 선택: mock(기본) | anthropic | openai
에이전트는 complete_json()만 호출하므로 공급자를 바꿔도 에이전트 코드는 그대로다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Protocol


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, *, tier: str = "high") -> dict[str, Any]:
        """구조화 JSON 응답을 반환. tier: high(Sonnet급) | light(Haiku급)."""
        ...


class MockLLM:
    """개발·테스트용. 실제 호출 없이 입력 기반 결정적 응답을 돌려준다."""

    def __init__(self, responder=None):
        self.calls: list[dict[str, Any]] = []
        self._responder = responder

    def complete_json(self, system: str, user: str, *, tier: str = "high") -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "tier": tier})
        if self._responder:
            return self._responder(system, user, tier)
        return {"mock": True}


class AnthropicLLM:
    MODELS = {"high": os.getenv("LLM_MODEL_HIGH", "claude-sonnet-5-5"),
              "light": os.getenv("LLM_MODEL_LIGHT", "claude-haiku-5-5")}

    def __init__(self):
        import anthropic  # 선택 의존성
        self._c = anthropic.Anthropic()

    def complete_json(self, system, user, *, tier="high"):
        r = self._c.messages.create(model=self.MODELS[tier], max_tokens=2048, system=system,
                                    messages=[{"role": "user", "content": user}])
        return _parse(r.content[0].text)


class OpenAILLM:
    MODELS = {"high": os.getenv("LLM_MODEL_HIGH", "gpt-4o"),
              "light": os.getenv("LLM_MODEL_LIGHT", "gpt-4o-mini")}

    def __init__(self):
        import openai  # 선택 의존성
        self._c = openai.OpenAI()

    def complete_json(self, system, user, *, tier="high"):
        r = self._c.chat.completions.create(
            model=self.MODELS[tier], response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return _parse(r.choices[0].message.content)


def _parse(text: str) -> dict[str, Any]:
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    return json.loads(text)


def get_llm() -> LLMClient:
    p = os.getenv("LLM_PROVIDER", "mock")
    return {"mock": MockLLM, "anthropic": AnthropicLLM, "openai": OpenAILLM}[p]()
