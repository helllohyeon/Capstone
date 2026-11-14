"""코치/피드백 에이전트 1단계 스키마 (명세서 §3.3.1).

입력의 video_analysis는 F파트 v3 §8의 B파트 Gemini 분석 JSON(`analysis` 객체)을 그대로 받는다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

from ..plan.schemas import Candidate

Status = Literal["matched", "partially_matched", "diverged"]


class CoachInput(BaseModel):
    plan_id: Optional[str] = None          # 2단계(독립형) 확장 대비 nullable
    plan: Optional[Candidate] = None       # D-2 채택 후보
    video_asset_id: str
    b_status: Literal["processing", "completed", "failed"] = "completed"
    video_analysis: Optional[dict[str, Any]] = None


class ItemResult(BaseModel):
    item: str
    status: Status
    planned: str
    actual: str
    impact_note: str = ""
    positive_deviation: bool = False


class Fix(BaseModel):
    issue: str
    recommendation: str


class CoachAnalysis(BaseModel):
    analysis_id: str
    stage: int = 1
    plan_id: Optional[str]
    video_asset_id: str
    status: Literal["processing", "completed", "failed"]
    overall_reflection_rate: Optional[float] = None
    item_breakdown: list[ItemResult] = []
    well_reflected: list[str] = []
    diverged_with_impact: list[str] = []
    priority_fixes: list[Fix] = []
    degraded: bool = False
    meta: dict[str, Any] = {}
