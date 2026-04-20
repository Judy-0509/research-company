# Research Newsletter System — MVP

스마트폰 시장 리서치 뉴스레터 시스템. **Paperclip** 멀티에이전트 플랫폼 위에서 동작하는 RSS 기반 리서치 자동화 도구.

---

## 필수 레포지토리 2개

이 시스템은 두 개의 레포지토리가 모두 필요합니다.

| 레포 | 역할 | 링크 |
|------|------|------|
| **research-company** (이 레포) | RSS 백엔드 + 에이전트 프롬프트 + 플러그인 | https://github.com/Judy-0509/research-company |
| **paperclip** | 멀티에이전트 플랫폼 (서버 + UI) | https://github.com/Judy-0509/paperclip |

### 폴더 구조 (권장)

두 레포를 **같은 부모 폴더** 아래에 나란히 클론하세요.

```
workspace/
├── paperclip/          ← Paperclip 플랫폼
└── research-company/   ← 이 레포 (RSS 백엔드 + 플러그인)
```

```bash
mkdir workspace && cd workspace
git clone https://github.com/Judy-0509/paperclip.git
git clone https://github.com/Judy-0509/research-company.git
```

> **Windows 주의**: `node_modules` 경로 길이 제한 때문에 두 레포를 깊은 경로에 두지 마세요.  
> 예) `C:\workspace\` 처럼 짧은 경로 권장.

---

## Architecture

```
사용자 (Paperclip Issue)
  → Topic Analyst Agent (GLM)
      → search_recent_news 툴 (plugin-research-news)
          → FastAPI RSS Backend (port 8765)
              → SQLite DB (news.db)
  → 한국어 마크다운 주제 5개 코멘트 POST → done
```

---

## 전체 설치 순서

### Step 1. RSS 백엔드 실행

```bash
cd research-company/backend
pip install -r requirements.txt
cp .env.example .env
# .env에 GLM_API_KEY 입력
uvicorn main:app --host 127.0.0.1 --port 8765 --workers 1
```

백엔드 확인:
```bash
curl http://localhost:8765/health
curl -X POST http://localhost:8765/collect   # 뉴스 수동 수집
```

---

### Step 2. Paperclip 플랫폼 설치 및 실행

```bash
cd paperclip
pnpm install
```

**Windows에서 postgres 좀비 프로세스가 있으면 먼저 제거:**
```powershell
Get-Process -Name 'postgres' -ErrorAction SilentlyContinue | Stop-Process -Force
```

서버 실행:
```bash
pnpm dev:server   # http://localhost:3100
```

> `server/.env`에 `DATABASE_URL`을 추가하면 안 됨. embedded postgres가 자동으로 54329 포트 관리.

---

### Step 3. 플러그인 빌드 및 설치

```bash
cd paperclip
pnpm --filter @paperclipai/plugin-research-news build
```

Paperclip UI → **Settings → Plugins → Install local plugin** → 아래 경로 지정:
```
paperclip/packages/plugins/plugin-research-news/dist/manifest.js
```

플러그인 설정에서 **Backend URL** = `http://localhost:8765`

---

### Step 4. Company / Project / Agent 설정

**Company ID와 Agent ID 조회 방법은 `CLAUDE.md` → "신규 환경 설정 가이드" 참고.**

1. Paperclip UI → **Companies → New Company**: `Research Co.`
2. **Projects → New Project**: `Newsletter`
3. **Agents → New Agent** 생성:

| 필드 | 값 |
|------|----|
| Name | Topic Analyst |
| Adapter | `kimi_api` |
| API URL | `https://api.z.ai/api/paas/v4/chat/completions` |
| API Key | GLM API 키 입력 |
| Model | `GLM-4.7` |
| Max Turns | `15` |

4. 시스템 프롬프트 주입 (PowerShell):
```powershell
cd research-company
$agentId = "<your-agent-id>"   # CLAUDE.md 가이드로 조회
$sp = (Get-Content prompts/topic_analyst_prompt.json -Raw | ConvertFrom-Json).systemPrompt
$body = @{ adapterConfig = @{ systemPrompt = $sp } } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$agentId" -Method Patch -ContentType "application/json" -Body $body
```

---

### Step 5. 실행 테스트

1. Paperclip UI → Newsletter 프로젝트 → **New Issue**
2. 제목: `스마트폰 분야에 대한 주제 선정해줘`
3. Topic Analyst 에이전트에 배정
4. 에이전트가 RSS 검색 → 한국어 주제 5개 코멘트 포스팅 → done

---

## 서비스 포트 요약

| 서비스 | 포트 | 시작 명령 |
|--------|------|-----------|
| Paperclip 서버 | 3100 | `pnpm dev:server` (paperclip/) |
| PostgreSQL (embedded) | 54329 | Paperclip 서버 시작 시 자동 |
| RSS 백엔드 | 8765 | `uvicorn main:app --port 8765 --workers 1` (research-company/backend/) |

---

## GLM 모델 옵션

| 모델 | 특징 |
|------|------|
| `GLM-4.7` | 최신, 권장 |
| `glm-4-plus` | 고품질 |
| `glm-4-air` | 빠르고 저렴 |
| `glm-4-flash` | 가장 빠름 |
