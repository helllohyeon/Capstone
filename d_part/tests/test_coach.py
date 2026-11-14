import json
from pathlib import Path

import pytest

from d_part.coach.agent import CoachAgent, analyze_upload
from d_part.coach.schemas import CoachInput
from d_part.pattern_client import MockPatternClient

DATA = json.loads((Path(__file__).parent.parent / "mocks/coach_input.json").read_text())


def run(d=DATA, **kw):
    return CoachAgent(**kw).analyze(CoachInput.model_validate(d))


def items(r):
    return {i.item: i for i in r.item_breakdown}


def test_reflection_breakdown():
    r = run()
    it = items(r)
    assert r.status == "completed"
    assert it["hook_line"].status == "matched"
    assert it["cta_timing"].status == "diverged" and it["cta_timing"].actual == "12s"  # 기획 8s
    assert it["video_length"].status == "partially_matched"  # 15s → 18s (3초 차)
    assert it["bgm"].status == "partially_matched"          # 트랙명 미식별
    assert it["subtitles"].status == "matched"
    assert 0 < r.overall_reflection_rate < 1
    assert r.priority_fixes[0].issue.startswith("CTA 시점")  # diverged 중 최우선
    assert all(i.impact_note for i in r.item_breakdown) and not r.degraded


def test_processing_and_failed():
    d = {**DATA, "b_status": "processing", "video_analysis": None}
    assert analyze_upload(d)["status"] == "processing"
    assert analyze_upload({**d, "b_status": "failed"})["status"] == "failed"


def test_positive_deviation_cta_earlier():
    d = json.loads(json.dumps(DATA))
    sc = d["video_analysis"]["scene_details"]
    sc[3]["on_screen_text"] = "프로필 링크 확인"   # 실제 CTA 9초
    sc[2]["start_second"], sc[1]["end_second"] = 3.0, 3.0
    sc[2]["on_screen_text"] = None
    d["plan"]["scene_by_scene"][2]["range"] = "13-15s"   # 기획 CTA 13s, 실제 9s → 앞당김
    it = items(run(d))
    assert it["cta_timing"].positive_deviation and "CTA 시점" in run(d).well_reflected


def test_c_failure_template_notes():
    r = run(pattern=MockPatternClient({"plan_vs_actual"}))
    assert r.degraded and "기획안" in items(r)["cta_timing"].impact_note


def test_stage2_not_in_mvp():
    with pytest.raises(NotImplementedError):
        run({**DATA, "plan": None, "plan_id": None})
