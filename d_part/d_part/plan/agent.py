"""D-2 스크립트 3후보 생성 에이전트 — 트렌드 믹스 (명세서 §3.2).

3단계 파이프라인: ① 요소 선별(규칙) → ② 조합·타임라인 배치(규칙) → ③ 문구 생성(LLM high, 1회 호출).
LLM 실패 시 템플릿 문구로 대체(degraded=True).
"""
from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime, timezone

from ..llm import LLMClient, get_llm
from .schemas import (Candidate, Hook, MixItem, PlanInput, PlanSet, Scene, Segment,
                      TrendElement)

SCHEMA_VERSION = "plan-schema-v1"
NEG_EXCLUDE = 0.40      # §8.7 초기 가정치: 부정 반응 40% 초과 → 제외
NEG_CAUTION = 0.30      # 30~40% → caution 표시
JACCARD_MAX = 0.60      # §8.7 초기 가정치: 후보 간 요소 집합 유사도 상한
N_CANDIDATES = 3
DEFAULT_SEGMENTS = [Segment(role="hook", ratio=0.15), Segment(role="product", ratio=0.4),
                    Segment(role="body", ratio=0.3), Segment(role="cta", ratio=0.15)]
CORE_TYPES = ("hook", "structure", "camera", "bgm", "cta")  # 조합 단위

SYSTEM_PROMPT = (
    "너는 Instagram Reels 숏폼 기획자다. 각 후보의 확정된 요소와 타임라인을 바꾸지 말고 문구만 작성한다. "
    "제품 효능을 과장하거나 입력에 없는 수치를 만들지 마라. 한국어. JSON만 출력: "
    '{"candidates":[{"candidate_id":"A","concept":"","differentiation_note":"다른 후보 대비 차별점",'
    '"hook_line":"","scene_contents":["장면 수와 동일"],"voice_script":"","subtitles":[""],'
    '"caption":"","hashtags":["#.."],"cta":""}]}'
)


# ---------- ① 요소 선별 ----------
def filter_elements(els: list[TrendElement]):
    kept, excluded, caution = [], [], {}
    for e in els:
        neg = e.sentiment.negative
        if e.controversy_risk == "높음" or neg > NEG_EXCLUDE:
            reason = "논란위험 높음" if e.controversy_risk == "높음" else f"부정 반응 {neg:.0%}"
            excluded.append({"element_id": e.element_id, "reason": reason})
            continue
        if e.controversy_risk == "보통" or neg >= NEG_CAUTION:
            caution[e.element_id] = f"{e.value}: 논란위험 {e.controversy_risk}, 부정 반응 {neg:.0%} — 주의"
        kept.append(e)
    return kept, excluded, caution


def score(e: TrendElement, brief) -> float:
    keys = {k for k in (brief.mood, brief.target, brief.category) if k}
    match = sum(1 for t in e.tags if any(k in t or t in k for k in keys))
    return round(e.viral_score_avg * (1 + 0.1 * match), 2)


# ---------- ② 조합 ----------
def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def pick_combos(pool: dict[str, list[TrendElement]], s: dict[str, float]):
    """핵심 요소 조합을 점수순으로 훑으며, 서로 자카드 < 0.6 이고 트렌드 소스 2개 이상인 3개를 고른다."""
    lists = [pool.get(t, [])[:4] or [None] for t in CORE_TYPES]
    combos = []
    for c in itertools.product(*lists):
        els = [e for e in c if e]
        if len({e.trend_id for e in els}) < 2:      # MVP: 최소 2개 트렌드 소스
            continue
        combos.append((sum(s[e.element_id] for e in els), els))
    combos.sort(key=lambda x: -x[0])
    def key(els):  # §3.2.3-2: Hook 유형 또는 영상 구조 중 하나는 달라야 함
        return tuple(next((e.element_id for e in els if e.type == t), None) for t in ("hook", "structure"))

    chosen, warn = [], []
    for sc, els in combos:
        ids = {e.element_id for e in els}
        if all(jaccard(ids, {e.element_id for e in c[1]}) < JACCARD_MAX and key(els) != key(c[1])
               for c in chosen):
            chosen.append((sc, els))
        if len(chosen) == N_CANDIDATES:
            break
    if len(chosen) < N_CANDIDATES:   # 요소가 부족하면 다양성 조건 완화
        warn.append("트렌드 요소가 부족해 후보 간 다양성 기준(자카드<0.6)을 완화했습니다.")
        for sc, els in combos:
            if len(chosen) == N_CANDIDATES:
                break
            if all({e.element_id for e in els} != {e.element_id for e in c[1]} for c in chosen):
                chosen.append((sc, els))
    return chosen, warn


def build_timeline(length: int, structure: TrendElement | None):
    segs = structure.segments if structure and structure.segments else DEFAULT_SEGMENTS
    total = sum(x.ratio for x in segs) or 1
    out, t = [], 0.0
    for i, seg in enumerate(segs):
        end = length if i == len(segs) - 1 else round(t + length * seg.ratio / total)
        end = max(end, int(t) + 1)
        out.append((seg.role, int(t), int(end)))
        t = end
    return out


# ---------- ③ 문구 생성 ----------
def _template_copy(cid, by, scenes, brief):
    hook = by.get("hook")
    return {"candidate_id": cid,
            "concept": f"{hook.value if hook else '기본'}형 {brief.product} 소개",
            "differentiation_note": " / ".join(f"{t}: {by[t].value}" for t in CORE_TYPES if t in by),
            "hook_line": f"{brief.target}라면 주목! {brief.product}",
            "scene_contents": [f"{r} 구간 — {brief.product}" for r, _, _ in scenes],
            "voice_script": f"{brief.target}를 위한 {brief.product}, 지금 확인해 보세요.",
            "subtitles": [brief.product], "caption": f"{brief.product} | {brief.goal}",
            "hashtags": [], "cta": by["cta"].value if "cta" in by else "프로필 링크 확인"}


class PlanAgent:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or get_llm()

    def generate(self, inp: PlanInput) -> PlanSet:
        b = inp.brief
        kept, excluded, caution = filter_elements(inp.trend_candidates)
        s = {e.element_id: score(e, b) for e in kept}
        pool: dict[str, list[TrendElement]] = {}
        for e in sorted(kept, key=lambda e: -s[e.element_id]):
            pool.setdefault(e.type, []).append(e)
        combos, warnings = pick_combos(pool, s)
        if not combos:
            return PlanSet(plan_set_id=_id(), input_conditions=b.model_dump(), candidates=[],
                           excluded_elements=excluded, degraded=True,
                           warnings=["조합 가능한 트렌드 요소가 없습니다(최소 2개 트렌드 소스 필요)."],
                           meta=_meta())

        drafts = []
        for idx, (sc, els) in enumerate(combos):
            by = {e.type: e for e in els}
            scenes = build_timeline(b.desired_length_sec, by.get("structure"))
            drafts.append((chr(65 + idx), sc, els, by, scenes))

        copies, degraded = self._write_copy(b, drafts, pool)
        cands = [self._assemble(d, copies.get(d[0]), b, caution, pool) for d in drafts]
        return PlanSet(plan_set_id=_id(), input_conditions=b.model_dump(), candidates=cands,
                       excluded_elements=excluded, degraded=degraded, warnings=warnings, meta=_meta())

    def _write_copy(self, b, drafts, pool):
        payload = {"brief": b.model_dump(), "hashtag_pool": [e.value for e in pool.get("hashtag", [])],
                   "caption_patterns": [e.value for e in pool.get("caption", [])],
                   "candidates": [{"candidate_id": cid, "elements": {t: e.value for t, e in by.items()},
                                   "timeline": [f"{r} {a}-{z}s" for r, a, z in sc]}
                                  for cid, _, _, by, sc in drafts]}
        try:
            r = self.llm.complete_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), tier="high")
            got = {c["candidate_id"]: c for c in r["candidates"]}
            for cid, _, _, _, sc in drafts:   # 장면 수 불일치 = 형식 오류
                if len(got[cid]["scene_contents"]) != len(sc):
                    raise ValueError(cid)
            return got, False
        except Exception:
            return {cid: _template_copy(cid, by, sc, b) for cid, _, _, by, sc in drafts}, True

    def _assemble(self, d, c, b, caution, pool):
        cid, sc, els, by, scenes = d
        hook_e, cam_e = by.get("hook"), by.get("camera")
        cta_role_src = by.get("cta")
        scene_objs = []
        for (role, a, z), content in zip(scenes, c["scene_contents"]):
            src = (hook_e if role == "hook" else cta_role_src if role == "cta" else by.get("structure"))
            scene_objs.append(Scene(range=f"{a}-{z}s", role=role, content=content,
                                    camera=cam_e.value if cam_e else "정면",
                                    source_trend_id=src.trend_id if src else None))
        mix = [MixItem(trend_id=e.trend_id, element=f"{e.type}: {e.value}",
                       applied_to=("0-%ds" % scenes[0][2] if e.type == "hook" else
                                   f"{scenes[-1][1]}-{scenes[-1][2]}s" if e.type == "cta" else "전체"))
               for e in els]
        tags = c.get("hashtags") or [e.value for e in pool.get("hashtag", [])[:3]]
        return Candidate(
            candidate_id=cid, concept=c["concept"], differentiation_note=c["differentiation_note"],
            recommended_length_sec=b.desired_length_sec,
            hook=Hook(type=hook_e.value if hook_e else "기본", line=c["hook_line"]),
            scene_by_scene=scene_objs, voice_script=c["voice_script"], subtitles=c["subtitles"],
            cut_timing=[f"{a}s" for _, a, _ in scenes] + [f"{scenes[-1][2]}s"],
            bgm={"track": by["bgm"].value, "source_trend_id": by["bgm"].trend_id} if "bgm" in by else {},
            caption=c["caption"], hashtags=tags, cta=c["cta"], trend_mix_breakdown=mix,
            caution_flags=[caution[e.element_id] for e in els if e.element_id in caution],
            mix_score=round(sc, 2))


def _id():
    return f"plan_{uuid.uuid4().hex[:12]}"


def _meta():
    return {"schema_version": SCHEMA_VERSION, "generated_at": datetime.now(timezone.utc).isoformat()}


def generate_plans(data: dict, **kw) -> dict:
    """F파트 API(POST /api/v1/plans)에서 호출할 진입점."""
    return PlanAgent(**kw).generate(PlanInput.model_validate(data)).model_dump()
