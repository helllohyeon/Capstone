import json
from pathlib import Path

from d_part.llm import MockLLM
from d_part.plan.agent import JACCARD_MAX, PlanAgent, build_timeline, generate_plans, jaccard
from d_part.plan.schemas import PlanInput

DATA = json.loads((Path(__file__).parent.parent / "mocks/plan_input.json").read_text())


def echo_llm():
    def r(s, u, t):
        p = json.loads(u)
        return {"candidates": [{"candidate_id": c["candidate_id"], "concept": "컨셉", "differentiation_note": "차별",
                                "hook_line": "훅", "scene_contents": ["장면"] * len(c["timeline"]),
                                "voice_script": "보이스", "subtitles": ["자막"], "caption": "캡션",
                                "hashtags": ["#태그"], "cta": "CTA"} for c in p["candidates"]]}
    return MockLLM(r)


def run(llm=None, data=DATA):
    return PlanAgent(llm=llm or echo_llm()).generate(PlanInput.model_validate(data))


def test_three_diverse_candidates():
    ps = run()
    assert len(ps.candidates) == 3 and not ps.degraded and not ps.warnings
    sets = [{m.trend_id + m.element for m in c.trend_mix_breakdown} for c in ps.candidates]
    for i in range(3):
        for j in range(i + 1, 3):
            assert jaccard(sets[i], sets[j]) < JACCARD_MAX
    hs = [(c.hook.type, c.scene_by_scene[0].source_trend_id, [s.role for s in c.scene_by_scene])
          for c in ps.candidates]
    assert len({(h[0], tuple(h[2])) for h in hs}) == 3  # Hook 또는 구조가 서로 다름
    for c in ps.candidates:
        assert len({m.trend_id for m in c.trend_mix_breakdown}) >= 2
        assert c.scene_by_scene[-1].range.endswith("15s")


def test_risk_filtering():
    ps = run()
    ex = {e["element_id"] for e in ps.excluded_elements}
    assert ex == {"h4", "g2"}  # 논란 높음, 부정 50%
    used = {m.element for c in ps.candidates for m in c.trend_mix_breakdown}
    assert not any("디스" in u for u in used)
    for c in ps.candidates:   # Lo-fi(보통, 35%)를 쓴 후보엔 caution
        if c.bgm.get("track") == "Lo-fi Morning":
            assert c.caution_flags


def test_llm_failure_template():
    ps = run(llm=MockLLM(lambda *a: {"candidates": []}))
    assert ps.degraded and len(ps.candidates) == 3 and ps.candidates[0].hook.line


def test_timeline_covers_length():
    tl = build_timeline(18, None)
    assert tl[0][1] == 0 and tl[-1][2] == 18
    assert all(a < z for _, a, z in tl) and all(tl[i][2] == tl[i + 1][1] for i in range(len(tl) - 1))


def test_no_combinable_elements():
    d = {"brief": DATA["brief"], "trend_candidates": DATA["trend_candidates"][:1]}
    out = generate_plans(d, llm=echo_llm())
    assert out["candidates"] == [] and out["degraded"]


def test_caution_flag_rule():
    from d_part.plan.agent import filter_elements
    _, _, caution = filter_elements(PlanInput.model_validate(DATA).trend_candidates)
    assert set(caution) == {"b2"}  # 논란위험 보통 + 부정 35%
