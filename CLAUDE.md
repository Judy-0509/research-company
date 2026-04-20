# Research Company — Project Guide

## Overview

스마트폰 시장 리서치 뉴스레터 시스템. **Paperclip** (멀티에이전트 플랫폼) + **FastAPI RSS 백엔드**로 구성.
현재 MVP 단계: Manager 에이전트가 사용자 요청을 받아 리서치 주제를 제안하고, 확인 후 RSS 기반 서브 리서치를 서브에이전트에게 위임한다.

---

## 현재 구현 상태 (MVP)

| 기능 | 상태 |
|------|------|
| RSS 뉴스 수집 (수동 POST /collect) | ✅ 구현 |
| SQLite 기사 저장 + 검색 | ✅ 구현 |
| GLM summary worker (10분마다 배치) | ✅ 구현 |
| Manager → 주제 제안 → 사용자 확인 → 서브태스크 배정 | ✅ 구현 |
| 서브에이전트 RSS 기반 리서치 | ✅ 구현 (품질 검증 중) |
| 3시간 자동 수집 | ⬜ env flag로 비활성화 (운영 단계에서 활성화) |
| 최종 리포트 통합 | ⬜ 미구현 |

---

## File Tree

```
12_research_company/
├── CLAUDE.md                        ← this file
├── README.md                        ← setup guide
├── codex_review_topic_researcher.md ← Codex 리뷰 메모
│
├── backend/                         ← FastAPI RSS 뉴스 백엔드 (port 8765)
│   ├── main.py                      ← FastAPI app, /health /search /collect /validate_proposal
│   ├── rss_collector.py             ← RSS 피드 수집 + 키워드 필터링
│   ├── database.py                  ← SQLite init, CRUD, get_summary_stats
│   ├── summarize_worker.py          ← GLM API 기사 요약 배치 worker
│   ├── source_tiers.py              ← 소스 신뢰도 분류 (Tier 1–3)
│   ├── seed_data.py                 ← RSS 피드 URL (KO + EN) + 검색 키워드
│   ├── brand_labels.py              ← 브랜드 라벨링 로직
│   ├── backfill_brands.py           ← 기존 기사 브랜드 라벨 백필 스크립트
│   ├── requirements.txt
│   ├── start.bat                    ← 빠른 시작 스크립트
│   └── news.db                     ← SQLite DB (자동 생성)
│
├── prompts/                         ← 에이전트 systemPrompt 파일
│   └── online_researcher_prompt.json
│
├── rotate_api_key.ps1               ← GLM API 키 전체 에이전트 일괄 교체
└── update_online_researcher_prompt.ps1
```

### Related: Paperclip Platform

> **참고**: Paperclip은 `10_paper company/paperclip/`에 위치. Windows node_modules 경로 제한으로 물리적 이동 불가 — 같은 프로젝트로 관리하되 폴더는 분리 유지.

```
10_paper company/paperclip/
├── server/
│   ├── src/index.ts          ← 서버 진입점 (embedded postgres 관리 포함)
│   ├── src/config.ts         ← 설정 로드 (.env: server/.env 우선)
│   └── .env                  ← BETTER_AUTH_SECRET만 포함 (DATABASE_URL 없으면 embedded postgres 자동 사용)
└── .env                      ← PORT=3100 (server/.env보다 우선순위 낮음)
```

---

## Services

| Service | Port | Start Command |
|---------|------|---------------|
| Paperclip server | 3100 | `pnpm dev:server` in `10_paper company/paperclip/` |
| PostgreSQL (embedded) | 54329 | Paperclip 서버 시작 시 자동 시작 |
| RSS backend | 8765 | `uvicorn main:app --port 8765 --workers 1` in `backend/` |

### Paperclip 서버 시작 절차 (중요)

```powershell
# 1. postgres 좀비 프로세스가 있으면 먼저 제거
powershell -Command "Get-Process -Name 'postgres' -ErrorAction SilentlyContinue | Stop-Process -Force"

# 2. 서버 시작 (server/.env에 DATABASE_URL 없어야 embedded postgres 모드로 정상 동작)
cd "C:\Users\jieun\Desktop\Project_2026\10_paper company\paperclip"
pnpm dev:server
```

> **주의**: `server/.env`에 `DATABASE_URL`을 추가하면 안 됨. embedded postgres가 자체적으로 54329 포트 관리.

---

## Agents (Paperclip Company: Research Co.)

### 현재 활성 에이전트 (1개)

| Agent | ID | Role |
|-------|----|------|
| **Topic Analyst** | `<your-agent-id>` | 한국어 요청 수신 → RSS DB 최근 7일 기사 스캔 → 스마트폰(OEM+공급망+수요) 보고서 주제 5개를 근거 기사와 함께 한국어 마크다운으로 제안 → done |

### Topic Analyst 워크플로우 (단일 phase)

```
사용자 요청 (예: "스마트폰 분야에 대한 주제 선정해줘")
  → GET 배정 이슈 + PATCH status=in_progress
  → search_recent_news(days=7) × N회 (OEM별 / 공급망 요소별 / 수요 관점별, 한·영 병행)
  → 후보 10+ 생성 → 축 분산·근거 기사 ≥3건 기준으로 5개 확정
  → 한국어 마크다운 코멘트 1건 POST (각 주제에 [id:NNNN] 형식 근거 기사 3~6건 포함)
  → PATCH status=done → STOP
```

- **출력 스키마**: `prompts/topic_analyst_prompt.json` 참조 (실제 주입된 프롬프트). 주제별 근거 뉴스의 `[id:NNNN]` ID는 다음 단계 분석가가 `GET /article/{id}`로 본문을 pull 하기 위한 핸들.
- **툴 제약**: 현재 런타임 등록 툴은 `search_recent_news` 1개뿐 (`plugin-research-news/src/manifest.ts`가 이것만 선언). `list_recent` · `search_library` · `get_article_detail` · `validate_proposal`은 worker.ts에 구현돼 있으나 manifest에 미선언 → **plugin rebuild + reinstall 필요**.
- **프롬프트 재주입 방법**:
  ```powershell
  $sp = (Get-Content prompts/topic_analyst_prompt.json -Raw | ConvertFrom-Json).systemPrompt
  $body = @{ adapterConfig = @{ systemPrompt = $sp } } | ConvertTo-Json -Depth 5
  Invoke-RestMethod -Uri "http://localhost:3100/api/agents/<your-agent-id>" -Method Patch -ContentType "application/json" -Body $body
  ```

### 미구현 (향후 추가 예정)

- Topic Analyst가 넘긴 근거 기사 ID 목록을 입력으로 받아 각 주제를 develop 하는 후속 분석가
- 최종 리포트 통합 에이전트
- 3시간 자동 뉴스 수집

---

## DB Credentials (PostgreSQL)

```
host: 127.0.0.1  port: 54329
database: paperclip  user: paperclip  password: <your-db-password>
```

Company ID: `<your-company-id>`

---

## RSS Backend 주요 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /health` | 서버 상태 + summary 통계 (pending/ok/failed) |
| `POST /collect` | 수동 RSS 수집 트리거 |
| `GET /search?query=...&days=14&brand=apple` | 기사 검색 |
| `GET /list_recent?hours=72&brand=samsung` | 최신 기사 목록 |
| `GET /article/{id}` | 기사 단건 조회 |
| `POST /validate_proposal` | 리서치 proposal JSON 검증 |

### RSS Backend 환경변수

```env
AUTO_COLLECT_ON_START=false      # 서버 시작 시 자동 수집 (기본 off)
ENABLE_SCHEDULED_COLLECT=false   # 3시간 주기 자동 수집 (기본 off)
COLLECT_INTERVAL_HOURS=2         # 수집 주기 (시간)
GLM_API_KEY=...                  # summary worker용 GLM API 키
SUMMARIZE_BATCH_SIZE=20          # 회당 요약 기사 수
SUMMARIZE_WALL_CLOCK=90          # 회당 최대 실행 시간 (초)
```

> **주의**: 이 backend는 APScheduler를 프로세스 내부에서 실행하므로 반드시 `--workers 1`로 실행해야 함.
> `ENABLE_SCHEDULED_COLLECT`와 무관하게 summarize/prune/vacuum job이 항상 등록되므로,
> multi-worker 환경에서는 모든 scheduled job이 프로세스 수만큼 중복 실행됨.
> multi-worker production이 필요하면 scheduler를 별도 worker로 분리하거나 DB/file 기반 lock을 추가해야 함.

---

## Important Notes

- `kimi-api` 어댑터 변경은 `pnpm build` + 서버 재시작 필요; 에이전트 `adapterConfig.systemPrompt`는 API PATCH로 즉시 적용 가능
- `/api/agents/me`는 에이전트 런 토큰으로 항상 401 반환 → `/api/companies/{id}/issues?assigneeAgentId={id}` 사용
- 429 rate limit: 모든 에이전트가 동일 GLM API 키 공유 → 여러 에이전트 동시 실행 금지
- CN OEM 에이전트가 6개 브랜드 통합 분석; 브랜드별 세부 전략은 개별 브랜드 에이전트
- 에이전트는 사용자가 명시적으로 취소/중단한 경우 재실행 금지
- RSS 백엔드 수동 수집: `curl -X POST http://localhost:8765/collect`
