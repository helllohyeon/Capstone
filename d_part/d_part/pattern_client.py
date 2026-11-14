"""C파트 패턴해석 모듈 클라이언트 (명세서 §4.1). C 인터페이스 확정 전까지 Mock 사용."""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel

Section = Literal["growth", "hook", "scene", "bgm", "caption_hashtag",
                  "relative_performance", "trend_mix_rationale", "plan_vs_actual"]


class NarrativeRequest(BaseModel):
    module: Literal["pattern_narrative"] = "pattern_narrative"
    section: Section
    context: dict[str, Any]  # reel_id, metrics, locale, tone


class Narrative(BaseModel):
    section: Section
    narrative: str
    cited_fields: list[str] = []
    confidence: Literal["high", "medium", "low"] = "medium"


class PatternClient(Protocol):
    def narrate_batch(self, reqs: list[NarrativeRequest]) -> list[Narrative]:
        """§4.1.3 배치 호출 제안안. 실패한 섹션은 결과에서 빠질 수 있다."""
        ...


class MockPatternClient:
    """C 응답을 흉내낸다. fail_sections에 넣은 섹션은 누락시켜 degraded 경로를 테스트한다."""

    def __init__(self, fail_sections: set[str] | None = None):
        self.fail = fail_sections or set()

    def narrate_batch(self, reqs):
        out = []
        for r in reqs:
            if r.section in self.fail:
                continue
            m = r.context.get("metrics", {})
            out.append(Narrative(section=r.section, narrative=f"[mock:{r.section}] {_brief(m)}",
                                 cited_fields=list(m)[:3], confidence="medium"))
        return out


def _brief(m: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in list(m.items())[:3] if not isinstance(v, (list, dict)))
