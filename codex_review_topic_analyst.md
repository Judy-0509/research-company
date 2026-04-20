# Codex Review — Topic Analyst (fc7d34f3)

> **검토 요청**: 아래 스펙·프롬프트·실제 구현 상태를 검토하고, 실행 전에 보완해야 할 점을 지적해 주세요. 특히 **데이터 무결성**, **툴 제약과 프롬프트 정합성**, **출력 포맷 파싱 가능성** 관점을 중점적으로 봐주세요.

---

## 1. 의도한 역할 (최종 합의)

- **트리거**: 사용자가 한국어로 "스마트폰 분야에 대한 주제 선정해줘" 류 요청을 Paperclip 이슈로 올림.
- **입력 데이터**: 사용자는 요약을 제공하지 않음. RSS 백엔드(`backend/news.db`, 현재 ok=1130건) 안의 기사 요약을 에이전트가 직접 조회.
- **시간 범위**: 요청 시점 기준 **최근 7일**.
- **분석 범위 (3축 모두 포함)**:
  1. OEM 본체 (Apple / Samsung / Xiaomi / Huawei / Honor / Oppo / Vivo / Transsion 등)
  2. 공급망 (메모리 DRAM/NAND/HBM, 파운드리 TSMC/공정, AP·디스플레이·배터리·카메라 등 부품)
  3. 수요/매크로 (출하량·판매, 환율/관세, 이벤트)
- **출력**: **한국어 마크다운** 코멘트 1건. 각 주제마다 근거 기사 3~6건을 `[id:NNNN]` 형식으로 명시 (이 ID가 다음 단계 에이전트의 입력이 됨).
- **종료 조건**: 코멘트 POST → 이슈 `status=done`. 재실행 없음.

---

## 2. 현재 구현 상태

### 2.1 Paperclip 에이전트
- **Agent ID**: `fc7d34f3-4a5b-4c62-8adb-bd505b304b99`
- **Company ID**: `ca76e1f0-7d21-42ac-9524-3def6a302b5d`
- **Adapter**: `kimi_api` · model `GLM-4.7` · `https://api.z.ai/api/paas/v4/chat/completions`
- **현재 배정 이슈 수**: 0 (테스트 전)
- **시스템 프롬프트**: 오늘 `PATCH /api/agents/fc7d34f3...` 로 교체 완료. 소스는 `prompts/topic_analyst_prompt.json`. 핵심 지시:
  - `days=7` 강제
  - 한·영 쿼리 병행
  - CN OEM 6개 개별 쿼리
  - 후보 10+ → 축 분산·근거 ≥3건 기준으로 5개 확정
  - 출력은 한국어 마크다운만 (JSON 금지), `[id:NNNN]` 포맷 고정

### 2.2 RSS 백엔드 (`backend/`)
- FastAPI, port 8765, 단일 worker
- `/search?query=...&days=...&limit=...&brand=...` → `{ articles: [{id,url,title,description,source_name,source_tier,published_at,...}] }`
- `/list_recent`, `/article/{id}`, `/validate_proposal` 등도 구현되어 있음
- `/health` 기준: summary ok=1130, pending=0, failed=0
- 기사 수집은 현재 수동 POST `/collect`만 활성 (`ENABLE_SCHEDULED_COLLECT=false`)

### 2.3 플러그인 (`plugin-research-news`)
- worker.ts 에는 5개 툴이 `ctx.tools.register`로 구현됨: `search_recent_news`, `list_recent`, `search_library`, `get_article_detail`, `validate_proposal`.
- **그러나 `manifest.ts`의 `tools` 배열에는 `search_recent_news` 하나만 선언**되어 있음.
- 서버 런타임 확인 (`GET /api/plugins/tools`):
  ```
  [ { "name":"research-news:search_recent_news", ... } ]   // 1개만 노출
  ```
- 따라서 현재 Topic Analyst가 호출 가능한 툴은 **`search_recent_news` 1개**. 프롬프트도 이 전제로 작성.

---

## 3. Codex에 묻고 싶은 점

1. **툴 1개 제약 → 분석 품질**: 광역 브라우징용 `list_recent`가 없고 키워드 검색만 가능. 최근 7일치 전체 풀을 파악하려면 쿼리 개수를 늘려야 하는데, 한·영 × OEM 8개 + 공급망 4~5개 + 수요 3~4개 = 30회 가까이 될 수 있습니다. GLM-4.7 호출당 토큰 부담과 기사 풀 커버리지 사이에서 프롬프트가 제시하는 "광역 스캔 8회 이상" 기준이 **충분한가, 과한가**?
2. **"깊이 있는 사고" 지시**: 프롬프트는 후보 10+ → 5개로 좁히라고만 지시하고, CoT 전개를 JSON 필드로 강제하지는 않음. GLM-4.7이 이 단계를 실제로 수행하는지 보장할 수 있는 더 나은 장치가 있나요? (예: 코멘트 본문 앞부분에 "## 분석 메모" 섹션 강제 → 사용자에게 노출, 또는 별도 코멘트 2개로 분리)
3. **`[id:NNNN]` 포맷**: 다음 에이전트가 정규식 `\[id:(\d+)\]`로 파싱할 계획. 이 설계가 취약한 지점(예: LLM이 `[ID:1234]`, `id:1234`, `[id:1234-5]` 같이 변형)? 프롬프트에 포맷을 얼마나 강하게 못 박아야 안정적일까요?
4. **데이터 무결성 리스크**: 학습 지식 오염 방지를 위해 "search_recent_news가 반환한 데이터만 사용" 문구를 넣었으나, 제목·URL 환각 가능성은 남음. 현재 `backend/main.py`의 `/validate_proposal`은 JSON 구조용 검증이라 마크다운 출력에 바로 쓸 수 없음. **마크다운 출력도 자동 검증**할 수 있는 경량 훅(예: 에이전트 코멘트 POST 후 별도 스크립트가 `[id:NNNN]`을 추출해 `GET /article/{id}`로 존재 여부만 확인)을 도입해야 할까요, 아니면 과설계일까요?
5. **단일 phase 설계의 함정**: 이전에는 "사용자 확인 대기(in_review) → 재실행" 2-phase였음. 이번엔 단일 phase로 단순화했는데, 주제가 마음에 안 들 경우 사용자가 단순히 "다시 해줘" 코멘트만 달아도 에이전트가 재기동되는지? Paperclip 동작과 엇갈리지 않는지 확인 필요.
6. **미선언 툴 활용 여부**: `list_recent` / `get_article_detail`이 worker.ts에 구현돼 있는데 manifest.ts에만 추가하면 유용성이 큽니다. 지금 Topic Analyst 단계에서 이 4개를 추가해야 할지, 아니면 단일 툴로 1차 검증 후 분리할지?

---

## 4. 관련 파일

- `prompts/topic_analyst_prompt.json` — 현재 주입된 시스템 프롬프트
- `prompts/online_researcher_prompt.json` — 다른 에이전트(Online Researcher, id `698ff064`)의 프롬프트. 혼동 주의.
- `backend/main.py` — FastAPI 엔드포인트 (`/search`, `/list_recent`, `/article/{id}`, `/validate_proposal`)
- `backend/rss_collector.py`, `backend/seed_data.py` — 수집 대상 피드와 키워드
- `C:\Users\jieun\Desktop\Project_2026\10_paper company\paperclip\packages\plugins\plugin-research-news\src\manifest.ts` — 툴 선언부 (현재 1개만 있음, 5개로 늘려야 runtime 노출됨)
- `CLAUDE.md` — Topic Analyst 섹션 갱신 완료

---

## 5. 아직 하지 않은 것

- 테스트 이슈 생성 및 실제 실행 (Codex 피드백 반영 후 진행 예정)
- 플러그인 manifest에 나머지 4개 툴 추가 + rebuild + reinstall
- 다음 단계 에이전트(주제 Develop) 설계

피드백은 이 파일 아래에 `## Codex Feedback` 섹션으로 직접 추가해 주세요.
