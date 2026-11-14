"""스크립트 3후보(트렌드 믹스) 입출력 스키마 (명세서 §3.2.1~3.2.4)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ElementType = Literal["hook", "structure", "camera", "bgm", "caption", "hashtag", "cta"]
Risk = Literal["낮음", "보통", "높음"]


# ---------- 입력 ----------
class PlanBrief(BaseModel):
    brand: str
    product: str
    target: str
    goal: str
    category: str
    mood: str = ""
    desired_length_sec: int = Field(15, ge=5, le=90)
    talent_available: bool = True


class Sentiment(BaseModel):
    positive: float = 0.0
    neutral: float = 0.0
    negative: float = 0.0


class Segment(BaseModel):
    role: str          # hook / product / body / cta 등
    ratio: float       # 전체 길이 대비 비율


class TrendElement(BaseModel):
    """C파트가 준 트렌드 요소 후보 1개 (trend_candidates[] 원소)."""
    element_id: str
    trend_id: str
    type: ElementType
    value: str                      # 예: "결과 선공개", "Sunset Drive (Remix)"
    viral_score_avg: float
    controversy_risk: Risk = "낮음"
    sentiment: Sentiment = Sentiment()
    tags: list[str] = []            # mood/target 매칭용 과거 성과 태그
    segments: list[Segment] = []    # type=structure일 때 구간 템플릿


class PlanInput(BaseModel):
    brief: PlanBrief
    trend_candidates: list[TrendElement]


# ---------- 출력 ----------
class Hook(BaseModel):
    type: str
    line: str


class Scene(BaseModel):
    range: str
    role: str
    content: str
    camera: str
    source_trend_id: Optional[str] = None


class MixItem(BaseModel):
    trend_id: str
    element: str
    applied_to: str


class Candidate(BaseModel):
    candidate_id: str
    concept: str
    differentiation_note: str
    recommended_length_sec: int
    hook: Hook
    scene_by_scene: list[Scene]
    voice_script: str
    subtitles: list[str]
    cut_timing: list[str]
    bgm: dict[str, Any]
    caption: str
    hashtags: list[str]
    cta: str
    trend_mix_breakdown: list[MixItem]
    caution_flags: list[str] = []
    mix_score: float = 0.0


class PlanSet(BaseModel):
    plan_set_id: str
    input_conditions: dict[str, Any]
    candidates: list[Candidate]
    excluded_elements: list[dict[str, str]] = []   # 필터링으로 빠진 요소와 사유
    degraded: bool = False
    warnings: list[str] = []
    meta: dict[str, Any] = {}
