"""보고서 에이전트 입출력 스키마 (명세서 §3.1.2, §3.1.3)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ReportType = Literal["pre_upload_reel", "post_publish"]


# ---------- 입력 ----------
class ViralScore(BaseModel):
    total: Optional[float] = None
    performance: Optional[float] = None
    relative: Optional[float] = None
    growth: Optional[float] = None
    engagement: Optional[float] = None
    content: Optional[float] = None
    trend: Optional[float] = None


class PerformanceMetrics(BaseModel):
    views: int
    likes: int
    comments: int
    followers: Optional[int] = None
    account_median_views: Optional[int] = None


class GrowthPoint(BaseModel):
    t: str
    views: int


class SuccessFactorIn(BaseModel):
    factor: str
    evidence: str
    weight: float = 0.0  # C가 준 기여도(SHAP 등). 정렬 기준


class ImprovementIn(BaseModel):
    issue: str
    benchmark: str
    recommendation: str


class ReportInput(BaseModel):
    reel_id: str
    report_type: ReportType = "pre_upload_reel"
    viral_score: ViralScore
    status_label: Optional[str] = None  # 급상승/상승/유지 등 (C 판정)
    performance_metrics: PerformanceMetrics
    growth_series: list[GrowthPoint] = []
    hook_analysis: dict[str, Any] = {}
    scene_structure: list[dict[str, Any]] = []
    bgm_analysis: dict[str, Any] = {}
    caption_hashtag: dict[str, Any] = {}
    success_factors: list[SuccessFactorIn] = []
    improvement_points: list[ImprovementIn] = []
    next_content_recommendation: dict[str, list[str]] = {}
    similar_high_performers: Optional[list[dict[str, Any]]] = None
    predicted: Optional[dict[str, Any]] = None  # post_publish 시 예측치


# ---------- 출력 ----------
class ExecutiveSummary(BaseModel):
    viral_score: Optional[float]
    status: Optional[str]
    key_evaluation: str
    top_success_factors: list[str]


class PerformanceSummary(BaseModel):
    views: int
    likes: int
    comments: int
    view_follower_ratio: Optional[float]
    median_multiple: Optional[float]


class NarrativeSection(BaseModel):
    narrative: str
    data: dict[str, Any] = {}


class SuccessFactorOut(BaseModel):
    rank: int
    factor: str
    evidence: str


class Report(BaseModel):
    report_id: str
    reel_id: str
    report_type: ReportType
    executive_summary: ExecutiveSummary
    performance_summary: PerformanceSummary
    viral_score_detail: ViralScore
    growth_analysis: NarrativeSection
    relative_performance: NarrativeSection
    hook_analysis: NarrativeSection
    scene_breakdown: NarrativeSection
    bgm_analysis: NarrativeSection
    caption_hashtag_analysis: NarrativeSection
    success_factors: list[SuccessFactorOut]
    improvement_points: list[ImprovementIn]
    similar_high_performer_comparison: dict[str, Any]
    next_content_recommendation: dict[str, list[str]]
    action_items: list[str]
    predicted_vs_actual: Optional[dict[str, Any]] = None
    # E파트 신호 (§3.1.5)
    degraded: bool = False
    degraded_sections: list[str] = []
    partial_score: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)
