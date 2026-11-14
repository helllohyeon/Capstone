import json
from pathlib import Path

from d_part.llm import MockLLM
from d_part.pattern_client import MockPatternClient
from d_part.report.agent import ReportAgent, generate_report
from d_part.report.schemas import ReportInput

DATA = json.loads((Path(__file__).parent.parent / "mocks/report_input.json").read_text())


def ok_llm():
    return MockLLM(lambda s, u, t: {"key_evaluation": "요약", "top_success_factors": ["결과 선공개 Hook"],
                                    "action_items": ["CTA 앞당기기"]})


def test_full_report():
    r = ReportAgent(llm=ok_llm()).generate(ReportInput.model_validate(DATA))
    assert r.performance_summary.median_multiple == 4.8
    assert r.performance_summary.view_follower_ratio == 7.5
    assert [f.factor for f in r.success_factors][0] == "결과 선공개 Hook"  # weight 정렬
    assert r.growth_analysis.data["peak_window"] == "6h~12h"
    assert r.similar_high_performer_comparison["available"] is False
    assert r.predicted_vs_actual is not None
    assert not r.degraded and not r.partial_score


def test_c_missing_sections_degraded():
    r = ReportAgent(llm=ok_llm(), pattern=MockPatternClient({"bgm", "hook"})).generate(
        ReportInput.model_validate(DATA))
    assert r.degraded and set(r.degraded_sections) == {"bgm", "hook"}
    assert "Sunset Drive" in r.bgm_analysis.narrative  # 수치 기반 대체 문장


def test_llm_failure_fallback():
    bad = MockLLM(lambda *a: {"wrong": 1})
    r = ReportAgent(llm=bad).generate(ReportInput.model_validate(DATA))
    assert r.degraded and r.action_items == ["CTA를 8~9초로 앞당기기"]


def test_partial_score():
    d = json.loads(json.dumps(DATA))
    d["viral_score"]["trend"] = None
    assert generate_report(d, llm=ok_llm())["partial_score"] is True
