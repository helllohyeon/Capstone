# D파트 개발 진행 메모 (이어서 작업할 때 이 파일부터 읽기)

## 결정 사항
- 스택: Python 3 + Pydantic v2 (F파트 v3 명세: Vercel Functions + Supabase, Pydantic 검증)
- LLM: 미정 → `d_part/llm.py`의 `LLMClient.complete_json()` 뒤로 분리. `LLM_PROVIDER=mock|anthropic|openai`, tier high/light
- C 패턴해석: `d_part/pattern_client.py` (§4.1 초안 스키마, 배치 호출). C 확정 전까지 `MockPatternClient`
- D는 라이브러리로 제공, F가 API 엔드포인트에서 `generate_*()` 호출 (F §19: POST /reels/{id}/reports, /plans, /videos/{id}/coach-analysis)
- 전달 방식: zip

## 진행 상황
- [x] D-1 보고서 에이전트 — `d_part/report/` (schemas, agent), 테스트 4개 통과
- [x] D-2 스크립트 3후보 (트렌드 믹스) — `d_part/plan/` 완료, 테스트 6개. LLM 1회 호출로 3후보 문구 생성, 실패 시 템플릿. 3단계: 요소 선별(규칙) → 타임라인 배치(규칙) → 문구 생성(LLM high). 리스크 필터: controversy_risk=높음 or 부정>40% 제외/caution, 다양성: trend_element_set 자카드<0.6
- [x] D-3 코치 1단계 — `d_part/coach/` 완료, 테스트 5개. 7개 항목(Hook문구/길이/장면구성/CTA시점/BGM/자막/제품노출) 규칙 비교, impact_note는 C 패턴해석(plan_vs_actual) → 실패 시 템플릿. B 미완료 시 status=processing. 입력은 F §8 Gemini JSON(`analysis` 객체), 반영률 = matched 1 / partial 0.5 / diverged 0 균등 평균(positive_deviation은 1)

## 다음에 할 일
MVP 3개 에이전트 1차 구현 완료 (총 테스트 15개). 남은 건 파트 간 합의 후 반영:
1. C(예나): 패턴해석 인터페이스(`pattern_client.py`), trend_candidates 스키마(`plan/schemas.py` TrendElement), Report 입력의 success_factors.weight
2. B(훈석)/F(이삭): Gemini 분석 JSON에 BGM `track_name` 추가 여부(없으면 BGM은 존재 여부만 비교), Hook/구도 enum
3. F(이삭): `generate_report` / `generate_plans` / `analyze_upload`를 API 엔드포인트에 연결, reports·plan_sets·coach_analyses 저장
4. LLM 공급자 확정 후 `LLM_PROVIDER` 설정 + 실제 프롬프트 품질 튜닝 (토큰 많이 듦 → 사용자 확인 후 진행)

## 재개 방법
작업 환경은 세션마다 초기화됨 → 새 세션에서 마지막 `d_part.zip`을 첨부하고 "PROGRESS.md 보고 이어서 개발해"라고 요청.

## 실행
`pip install -r requirements.txt && python -m pytest -q`
