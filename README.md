# Research Newsletter System — MVP

Smartphone deep-research newsletter system built on **Paperclip** + **FastAPI backend**.

## Architecture

```
User (Paperclip Issue) → Researcher Agent (GLM) → search_recent_news tool
                                                  → FastAPI backend (RSS collection)
                                                  → Post 5 topic proposals as issue comment
```

---

## 1. Start the Backend

```bat
cd backend
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

- Collects RSS on startup, then every 2 hours automatically
- `GET  http://localhost:8765/search?query=iPhone&days=14`
- `POST http://localhost:8765/collect`  (manual trigger)
- `GET  http://localhost:8765/health`

---

## 2. Build the Plugin

```bash
cd "C:\Users\jieun\Desktop\Project_2026\10_paper company\paperclip"
pnpm install
pnpm --filter @paperclipai/plugin-research-news build
```

Then in Paperclip UI → **Settings → Plugins → Install local plugin** and point to:
```
packages/plugins/plugin-research-news/dist/manifest.js
```

Plugin config: set **Backend URL** to `http://localhost:8765`

---

## 3. Start Paperclip

```bash
cd "C:\Users\jieun\Desktop\Project_2026\10_paper company\paperclip"
pnpm dev
```

---

## 4. Create the Researcher Agent

In Paperclip UI → **Agents → New Agent**:

| Field | Value |
|---|---|
| Name | Researcher |
| Adapter | `kimi_api` |
| API URL | `https://open.bigmodel.cn/api/paas/v1/chat/completions` |
| API Key | Set your key in Paperclip agent settings — see `.env.example` |
| Model | `glm-4-plus` |
| Max Turns | `15` |

**System Prompt** (paste below):

```
You are a Senior Research Analyst specializing in the global smartphone market.
Your data sources include Counterpoint Research, IDC, Canalys, TrendForce, Omdia, GfK, Bloomberg, Reuters, and major tech media.

When assigned an issue requesting a newsletter (e.g. "iPhone 관련 deep research newsletter 만들고 싶어"):

1. SEARCH: Call search_recent_news multiple times with different queries to gather comprehensive coverage.
   - First call: the main topic (e.g. "iPhone shipment market share 2025")
   - Second call: supply chain angle (e.g. "iPhone TSMC Apple supply chain")
   - Third call: competitive angle (e.g. "iPhone Samsung Galaxy comparison")
   Use days=14 to focus on the last 2 weeks.

2. ANALYZE: From the collected articles, identify the most significant, data-rich stories.
   Prioritize Tier 3 sources (research firms: Counterpoint, TrendForce, IDC, Canalys) over general media.

3. PROPOSE: Post ONE comment to the issue with exactly 5 newsletter topic proposals.

Format your comment EXACTLY like this:

---
## 📋 Newsletter Topic Proposals — [Topic Name]
*Based on [N] articles collected from [date range]*

---

### Topic 1: [Title]
**Why this topic:** [2-3 sentences explaining why this is timely and important based on the sources found]

**Key sources found:**
- [Source Name] ([date]): [brief summary of what the article covers]
- [Source Name] ([date]): [brief summary]

**Proposed outline:**
1. [Section 1 heading]
2. [Section 2 heading]
3. [Section 3 heading]
4. Data/Chart: [what data to visualize]

---

### Topic 2: [Title]
[same format]

... (repeat for all 5 topics)

---
*Reply to this comment with your feedback or select a topic number to proceed.*
---

Use Korean for the final comment if the original issue was written in Korean.
Use the paperclip_api tool with POST /api/issues/{issueId}/comments to post the comment.
```

---

## 5. Create a Research Company & Project

1. Paperclip UI → **Companies → New Company**: `Research Co.`
2. **Projects → New Project**: `Newsletter`
3. Assign **Researcher** agent to the project

---

## 6. Workflow

1. Create an issue: **"iPhone 관련 deep research newsletter 만들고 싶어"**
2. Assign to **Researcher** agent
3. Agent searches RSS → analyzes → posts 5 topic proposals as comment
4. Reply to the comment with feedback (HITL)

---

## GLM Model Options

| Model | Notes |
|---|---|
| `glm-4-plus` | Best quality, recommended |
| `glm-4-air` | Faster, cheaper |
| `glm-4-flash` | Fastest |
