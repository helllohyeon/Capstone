"""D-3 코치/피드백 에이전트 1단계 — 기획안 대비 반영률 분석 (명세서 §3.3.1).

① B 분석 완료 여부 확인(미완료 → status=processing 반환, F가 폴링/웹훅으로 재호출)
② 기획안 항목 ↔ 영상 특징 1:1 비교(규칙) → matched / partially_matched / diverged
③ 판정 근거 문장은 C 패턴해석(section=plan_vs_actual) 배치 호출, 실패 시 템플릿 문장
④ 반영률 = 균등 가중 평균 (matched 1, partial 0.5, diverged 0, positive_deviation 1)
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from ..pattern_client import MockPatternClient, NarrativeRequest, PatternClient
from .schemas import CoachAnalysis, CoachInput, Fix, ItemResult

SCHEMA_VERSION = "coach-schema-v1"
HOOK_END_SEC = 3.0                     # F §5: Hook은 0~3초
TIME_OK, TIME_PARTIAL = 1.0, 3.0       # 시간 차 허용(초)
TEXT_OK, TEXT_PARTIAL = 0.8, 0.4       # 문구 유사도
CTA_WORDS = ("링크", "프로필", "댓글", "구매", "팔로우", "저장", "클릭", "지금")
SCORE = {"matched": 1.0, "partially_matched": 0.5, "diverged": 0.0}
LABEL = {"hook_line": "Hook 문구", "video_length": "영상 길이", "scene_structure": "장면 구성",
         "cta_timing": "CTA 시점", "bgm": "BGM", "subtitles": "자막", "product_exposure": "제품 노출"}


def _sec(r: str) -> tuple[float, float]:
    a, z = re.findall(r"[\d.]+", r)[:2]
    return float(a), float(z)


def _sim(a: str, b: str) -> float:
    n = lambda s: re.sub(r"\s+", "", s or "")
    return SequenceMatcher(None, n(a), n(b)).ratio()


def _by_time(diff: float) -> str:
    return "matched" if diff <= TIME_OK else "partially_matched" if diff <= TIME_PARTIAL else "diverged"


def _by_text(s: float) -> str:
    return "matched" if s >= TEXT_OK else "partially_matched" if s >= TEXT_PARTIAL else "diverged"


def compare(plan, va: dict) -> list[ItemResult]:
    scenes = va.get("scene_details", [])
    audio = va.get("audio_analysis", {})
    transcript = audio.get("transcript", [])
    end = scenes[-1]["end_second"] if scenes else 0.0
    out: list[ItemResult] = []

    # Hook 문구: 0~3초 화면 텍스트 + 발화
    hook_txt = " ".join([s.get("on_screen_text") or "" for s in scenes if s["start_second"] < HOOK_END_SEC] +
                        [t["text"] for t in transcript if t["start_second"] < HOOK_END_SEC]).strip()
    best = max([_sim(plan.hook.line, hook_txt)] +
               [_sim(plan.hook.line, s.get("on_screen_text") or "") for s in scenes
                if s["start_second"] < HOOK_END_SEC])
    out.append(ItemResult(item="hook_line", status=_by_text(best), planned=plan.hook.line,
                          actual=hook_txt or "(0~3초 문구 없음)"))

    # 영상 길이
    planned_len = plan.recommended_length_sec
    st = _by_time(abs(end - planned_len))
    out.append(ItemResult(item="video_length", status=st, planned=f"{planned_len}s", actual=f"{end:g}s",
                          positive_deviation=st == "diverged" and planned_len - end <= 5 and end < planned_len))

    # 장면 구성: 기획 컷 경계 vs 실제 Scene 시작점(가장 가까운 것) 평균 오차
    p_cuts = [_sec(s.range)[0] for s in plan.scene_by_scene[1:]]
    a_cuts = [s["start_second"] for s in scenes[1:]]
    near = lambda xs, ys: sum(min(abs(x - y) for y in ys) for x in xs) / len(xs)
    diff = max(near(p_cuts, a_cuts), near(a_cuts, p_cuts)) if p_cuts and a_cuts else 99  # 누락·추가 컷 모두 반영
    out.append(ItemResult(item="scene_structure", status=_by_time(diff),
                          planned=" / ".join(f"{s.range} {s.role}" for s in plan.scene_by_scene),
                          actual=" / ".join(f"{s['start_second']:g}-{s['end_second']:g}s {s.get('section', '')}"
                                            for s in scenes)))

    # CTA 시점: 기획 cta 구간 시작 vs 실제 CTA 단서가 처음 나온 시각
    p_cta = next((_sec(s.range)[0] for s in plan.scene_by_scene if s.role == "cta"), None)
    if p_cta is not None:
        words = CTA_WORDS + tuple(w for w in re.findall(r"\w{2,}", plan.cta))
        hits = [s["start_second"] for s in scenes
                if any(w in " ".join(str(s.get(k) or "") for k in ("on_screen_text", "audio_or_dialogue", "purpose"))
                       for w in words)]
        hits += [t["start_second"] for t in transcript if any(w in t["text"] for w in words)]
        a_cta = min(hits) if hits else None
        st = _by_time(abs(a_cta - p_cta)) if a_cta is not None else "diverged"
        out.append(ItemResult(item="cta_timing", status=st, planned=f"{p_cta:g}s",
                              actual=f"{a_cta:g}s" if a_cta is not None else "(CTA 미검출)",
                              positive_deviation=a_cta is not None and st == "diverged" and a_cta < p_cta))

    # BGM: B가 트랙명을 주면 비교, 아니면 존재 여부만 (F §8.9엔 track_name 없음)
    bgm = audio.get("background_music", {})
    p_track = plan.bgm.get("track")
    if p_track:
        a_track = bgm.get("track_name")
        if a_track:
            st = "matched" if _sim(p_track, a_track) >= TEXT_OK else "diverged"
        else:
            st = "partially_matched" if bgm.get("exists") else "diverged"
        out.append(ItemResult(item="bgm", status=st, planned=p_track,
                              actual=a_track or (f"BGM 있음(트랙 미식별, {bgm.get('mood')}/{bgm.get('tempo')})"
                                                 if bgm.get("exists") else "BGM 없음")))

    # 자막: 존재 + 문구 포함 정도
    if plan.subtitles:
        if not va.get("subtitle", {}).get("exists"):
            st, act = "diverged", "자막 없음"
        else:
            texts = [s["on_screen_text"] for s in scenes if s.get("on_screen_text")]
            ost = " / ".join(texts)
            hit = sum(1 for t in plan.subtitles if any(_sim(t, x) >= TEXT_PARTIAL for x in texts))
            r = hit / len(plan.subtitles)
            st, act = ("matched" if r >= 0.8 else "partially_matched" if r > 0 else "diverged"), ost[:80]
        out.append(ItemResult(item="subtitles", status=st, planned=" / ".join(plan.subtitles), actual=act))

    # 제품 노출: 기획 product 구간 존재 시 실제 노출 여부
    if any(s.role == "product" for s in plan.scene_by_scene):
        prod = va.get("product", {})
        out.append(ItemResult(item="product_exposure", status="matched" if prod.get("exists") else "diverged",
                              planned="제품 노출 구간 있음",
                              actual=prod.get("description") or ("노출됨" if prod.get("exists") else "노출 없음")))
    return out


def _template_note(r: ItemResult) -> str:
    lb = LABEL.get(r.item, r.item)
    if r.status == "matched":
        return f"{lb}이(가) 기획안대로 반영되었습니다."
    if r.positive_deviation:
        return f"{lb}이(가) 기획과 다르지만({r.planned} → {r.actual}) 긍정적인 변화로 보입니다."
    if r.status == "partially_matched":
        return f"{lb}이(가) 일부만 반영되었습니다({r.planned} → {r.actual})."
    return f"{lb}이(가) 기획안과 다릅니다({r.planned} → {r.actual})."


def _fix(r: ItemResult) -> Fix:
    rec = {"hook_line": f"첫 3초 안에 기획 Hook 문구 '{r.planned}'를 자막 또는 음성으로 넣어 주세요.",
           "video_length": f"영상 길이를 {r.planned} 전후로 편집해 주세요.",
           "scene_structure": f"컷 구간을 기획안({r.planned})에 맞춰 조정해 주세요.",
           "cta_timing": f"CTA를 {r.planned} 지점으로 옮겨 주세요.",
           "bgm": f"기획 BGM '{r.planned}' 사용 여부를 확인해 주세요.",
           "subtitles": "기획안의 핵심 자막을 화면에 추가해 주세요.",
           "product_exposure": "제품이 화면에 명확히 보이는 컷을 추가해 주세요."}
    return Fix(issue=f"{LABEL.get(r.item, r.item)}: {r.planned} → {r.actual}", recommendation=rec[r.item])


# 수정 우선순위: 이탈·전환에 영향 큰 순
PRIORITY = ["hook_line", "cta_timing", "product_exposure", "video_length", "scene_structure", "subtitles", "bgm"]


class CoachAgent:
    def __init__(self, pattern: PatternClient | None = None):
        self.pattern = pattern or MockPatternClient()

    def analyze(self, inp: CoachInput) -> CoachAnalysis:
        base = dict(analysis_id=f"coach_{uuid.uuid4().hex[:12]}", plan_id=inp.plan_id,
                    video_asset_id=inp.video_asset_id, meta={"schema_version": SCHEMA_VERSION,
                    "generated_at": datetime.now(timezone.utc).isoformat()})
        if inp.b_status != "completed" or not inp.video_analysis:
            return CoachAnalysis(status="failed" if inp.b_status == "failed" else "processing", **base)
        if inp.plan is None:
            raise NotImplementedError("2단계(기획안 없는 독립형 분석)는 Phase 4 범위입니다.")

        items = compare(inp.plan, inp.video_analysis)
        degraded = self._notes(inp, items)
        rate = sum(1.0 if r.positive_deviation else SCORE[r.status] for r in items) / len(items)
        bad = [r for r in items if r.status != "matched" and not r.positive_deviation]
        bad.sort(key=lambda r: (r.status != "diverged", PRIORITY.index(r.item)))
        return CoachAnalysis(
            status="completed", overall_reflection_rate=round(rate, 2), item_breakdown=items,
            well_reflected=[LABEL[r.item] for r in items if r.status == "matched" or r.positive_deviation],
            diverged_with_impact=[r.impact_note for r in items if r.status == "diverged" and not r.positive_deviation],
            priority_fixes=[_fix(r) for r in bad[:3]], degraded=degraded, **base)

    def _notes(self, inp, items) -> bool:
        reqs = [NarrativeRequest(section="plan_vs_actual",
                                 context={"reel_id": inp.video_asset_id, "item": r.item, "locale": "ko-KR",
                                          "metrics": r.model_dump(include={"item", "status", "planned", "actual"})})
                for r in items]
        try:
            got = self.pattern.narrate_batch(reqs)
            notes = [n.narrative for n in got] if len(got) == len(items) else None
        except Exception:
            notes = None
        for i, r in enumerate(items):
            r.impact_note = notes[i] if notes else _template_note(r)
        return notes is None


def analyze_upload(data: dict, **kw) -> dict:
    """F파트 API(POST /api/v1/videos/{video_id}/coach-analysis)에서 호출할 진입점."""
    return CoachAgent(**kw).analyze(CoachInput.model_validate(data)).model_dump()
