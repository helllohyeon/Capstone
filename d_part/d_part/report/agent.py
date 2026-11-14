"""D-1 보고서 에이전트 (명세서 §3.1).

흐름: 템플릿 섹션 계산 → C 패턴해석 배치 호출 → D 자체 LLM 취합(요약/액션) → 조립.
C 해석 누락 시 수치 기반 문장으로 대체하고 degraded=True (전면 실패 금지).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ..llm import LLMClient, get_llm
from ..pattern_client import MockPatternClient, NarrativeRequest, PatternClient
from .schemas import (ExecutiveSummary, NarrativeSection, PerformanceSummary, Report,
                      ReportInput, SuccessFactorOut)

SCHEMA_VERSION = "report-schema-v1"
SIMILAR_MIN_DATA = 10_000  # §3.1.4: 데이터 기준치 미만이면 비교 섹션 비활성

SYSTEM_PROMPT = (
    "너는 Instagram Reels 마케팅 리포트 작성자다. 입력 JSON에 있는 수치와 문장만 근거로 쓴다. "
    "입력에 없는 숫자를 만들지 마라. 한국어 마케터 문체. 반드시 JSON만 출력: "
    '{"key_evaluation": "2문장 이내", "top_success_factors": ["최대 4개"], '
    '"action_items": ["최대 3개, 실행 가능한 문장"]}'
)


def _ratio(a, b):
    return round(a / b, 2) if a is not None and b else None


def _fallback_narratives(inp: ReportInput, perf: PerformanceSummary) -> dict[str, str]:
    """C 해석이 없을 때 쓰는 수치 기반 축약 문장."""
    g = inp.growth_series
    return {
        "growth": f"최근 측정 조회수 {g[-1].views:,}회." if g else "성장 데이터 없음.",
        "relative_performance": (f"계정 중앙값 대비 {perf.median_multiple}배." if perf.median_multiple
                                 else "계정 비교 데이터 없음."),
        "hook": f"Hook 유형: {inp.hook_analysis.get('type', '미상')}.",
        "scene": f"총 {len(inp.scene_structure)}개 장면.",
        "bgm": f"BGM: {inp.bgm_analysis.get('track', '미상')}.",
        "caption_hashtag": "키워드: " + ", ".join(inp.caption_hashtag.get("keywords", [])[:5]),
    }


def _peak_window(g):
    if len(g) < 2:
        return None
    deltas = [(g[i].views - g[i - 1].views, f"{g[i-1].t}~{g[i].t}") for i in range(1, len(g))]
    return max(deltas)[1]


class ReportAgent:
    def __init__(self, llm: LLMClient | None = None, pattern: PatternClient | None = None,
                 dataset_size: int = 0):
        self.llm = llm or get_llm()
        self.pattern = pattern or MockPatternClient()
        self.dataset_size = dataset_size  # A파트 누적 Reel 수 (F가 주입)

    def generate(self, inp: ReportInput) -> Report:
        pm = inp.performance_metrics
        # 1) 템플릿 섹션 (9.2, 9.9, 9.12~9.15)
        perf = PerformanceSummary(views=pm.views, likes=pm.likes, comments=pm.comments,
                                  view_follower_ratio=_ratio(pm.views, pm.followers),
                                  median_multiple=_ratio(pm.views, pm.account_median_views))
        factors = sorted(inp.success_factors, key=lambda f: f.weight, reverse=True)[:5]
        factors_out = [SuccessFactorOut(rank=i + 1, factor=f.factor, evidence=f.evidence)
                       for i, f in enumerate(factors)]

        # 2) C 패턴해석 배치 호출 (9.3~9.8)
        section_data = {
            "growth": {"series": [p.model_dump() for p in inp.growth_series],
                       "peak_window": _peak_window(inp.growth_series)},
            "relative_performance": {"account_median": pm.account_median_views, "current": pm.views,
                                     "multiple": perf.median_multiple},
            "hook": inp.hook_analysis,
            "scene": {"scenes": inp.scene_structure},
            "bgm": inp.bgm_analysis,
            "caption_hashtag": inp.caption_hashtag,
        }
        reqs = [NarrativeRequest(section=s, context={"reel_id": inp.reel_id, "metrics": d,
                                                     "locale": "ko-KR", "tone": "marketer_friendly"})
                for s, d in section_data.items()]
        try:
            got = {n.section: n for n in self.pattern.narrate_batch(reqs)}
        except Exception:
            got = {}
        fb = _fallback_narratives(inp, perf)
        missing = [s for s in section_data if s not in got]
        sec = {s: NarrativeSection(narrative=got[s].narrative if s in got else fb[s], data=d)
               for s, d in section_data.items()}

        # 3) D 자체 LLM 취합 (9.1, 9.16)
        summary = self._summarize(inp, perf, factors_out, sec)

        # 4) 9.11 유사 고성과 비교 (조건부)
        if inp.similar_high_performers and self.dataset_size >= SIMILAR_MIN_DATA:
            similar = {"available": True, "items": inp.similar_high_performers}
        else:
            similar = {"available": False, "reason": "insufficient_data"}

        vs = inp.viral_score
        partial = any(getattr(vs, k) is None for k in type(vs).model_fields if k != "total")

        pva = None
        if inp.report_type == "post_publish" and inp.predicted:
            pva = {"predicted": inp.predicted, "actual": {"views": pm.views, "likes": pm.likes}}

        return Report(
            report_id=f"rpt_{uuid.uuid4().hex[:12]}", reel_id=inp.reel_id, report_type=inp.report_type,
            executive_summary=ExecutiveSummary(viral_score=vs.total, status=inp.status_label,
                                               key_evaluation=summary["key_evaluation"],
                                               top_success_factors=summary["top_success_factors"]),
            performance_summary=perf, viral_score_detail=vs,
            growth_analysis=sec["growth"], relative_performance=sec["relative_performance"],
            hook_analysis=sec["hook"], scene_breakdown=sec["scene"], bgm_analysis=sec["bgm"],
            caption_hashtag_analysis=sec["caption_hashtag"],
            success_factors=factors_out, improvement_points=inp.improvement_points,
            similar_high_performer_comparison=similar,
            next_content_recommendation=inp.next_content_recommendation,
            action_items=summary["action_items"], predicted_vs_actual=pva,
            degraded=bool(missing) or summary.get("_fallback", False), degraded_sections=missing,
            partial_score=partial,
            meta={"schema_version": SCHEMA_VERSION,
                  "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    def _summarize(self, inp, perf, factors, sec) -> dict:
        payload = {"viral_score": inp.viral_score.total, "status": inp.status_label,
                   "performance": perf.model_dump(),
                   "success_factors": [f.model_dump() for f in factors],
                   "improvement_points": [i.model_dump() for i in inp.improvement_points],
                   "section_narratives": {k: v.narrative for k, v in sec.items()}}
        try:
            r = self.llm.complete_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
            return {"key_evaluation": str(r["key_evaluation"]),
                    "top_success_factors": list(r["top_success_factors"])[:4],
                    "action_items": list(r["action_items"])[:3]}
        except Exception:
            # LLM 실패/형식 오류 → 템플릿 대체
            return {"key_evaluation": f"Viral Score {inp.viral_score.total}, 조회수 {perf.views:,}회.",
                    "top_success_factors": [f.factor for f in factors[:4]],
                    "action_items": [i.recommendation for i in inp.improvement_points[:3]],
                    "_fallback": True}


def generate_report(data: dict, **kw) -> dict:
    """F파트 API(POST /api/v1/reels/{id}/reports)에서 호출할 진입점."""
    return ReportAgent(**kw).generate(ReportInput.model_validate(data)).model_dump()
