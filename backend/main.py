"""FastAPI backend — RSS collection + article search for Research Newsletter."""
import html
import logging
import os
import re
import secrets
import threading
import unicodedata
from pathlib import Path

# Load .env before any module-level os.environ reads
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    _env = Path(__file__).parent / ".env"
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from database import init_db, prune_old_articles, search_articles, vacuum_db, list_recent_articles, get_article_by_id, get_summary_stats
from rss_collector import fetch_all_feeds
from summarize_worker import run_summarize_batch, request_stop as stop_summarize, last_summarize, _load_state as load_summarize_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── validate_proposal helpers (module-level for reuse) ────────────────────────
_ARTICLE_ID_RE = re.compile(r"^(?:a_)?(\d{1,18})$")
_BRAND_NAMES_RE = re.compile(
    r"\b(samsung|apple|xiaomi|huawei|honor|oppo|vivo|transsion|"
    r"motorola|qualcomm|mediatek|tsmc)\b",
    re.IGNORECASE,
)

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()

def _is_brand_number_only(text: str) -> bool:
    """Return True only if quote has no meaningful content after removing brands/numbers.

    Uses character count (not word count) for CJK text where spaces are sparse.
    """
    stripped = _BRAND_NAMES_RE.sub("", text)
    stripped = re.sub(r"[\d%$.,\-\+\s]+", " ", stripped).strip()
    # Word-count gate (works for space-delimited languages)
    if len(stripped.split()) >= 2:
        return False
    # Character-count gate (covers CJK where words aren't space-separated)
    char_count = len(re.sub(r"\s+", "", stripped))
    return char_count < 10

scheduler = BackgroundScheduler()
_collect_lock = threading.Lock()
last_collect: dict = {"at": None, "inserted": 0, "skipped": 0}

COLLECT_TOKEN = os.environ.get("COLLECT_TOKEN", "")
AUTO_COLLECT_ON_START = os.environ.get("AUTO_COLLECT_ON_START", "false").lower() == "true"
ENABLE_SCHEDULED_COLLECT = os.environ.get("ENABLE_SCHEDULED_COLLECT", "false").lower() == "true"
ENABLE_SUMMARIZE_WORKER = os.environ.get("ENABLE_SUMMARIZE_WORKER", "true").lower() == "true"

try:
    COLLECT_INTERVAL_HOURS = max(1, min(24, int(os.environ.get("COLLECT_INTERVAL_HOURS", "2"))))
except ValueError:
    logger.warning("Invalid COLLECT_INTERVAL_HOURS env var, defaulting to 2")
    COLLECT_INTERVAL_HOURS = 2

try:
    SUMMARIZE_INTERVAL_MINUTES = max(1, min(60, int(os.environ.get("SUMMARIZE_INTERVAL_MINUTES", "10"))))
except ValueError:
    SUMMARIZE_INTERVAL_MINUTES = 10

BrandFilter = Literal[
    "apple", "samsung", "huawei", "honor", "xiaomi",
    "oppo", "vivo", "transsion", "cn_oem", ""
]


def run_collection() -> None:
    if not _collect_lock.acquire(blocking=False):
        logger.info("Collection already in progress, skipping")
        return
    try:
        logger.info("RSS collection started")
        inserted, skipped = fetch_all_feeds()
        last_collect["at"] = datetime.now(timezone.utc).isoformat()
        last_collect["inserted"] = inserted
        last_collect["skipped"] = skipped
        logger.info("RSS collection done: +%d new, %d skipped", inserted, skipped)
        if inserted > 0:
            threading.Thread(target=_trigger_summarize_if_pending, daemon=True).start()
    except Exception:
        logger.exception("RSS collection failed")
    finally:
        _collect_lock.release()


def _trigger_summarize_if_pending() -> None:
    """Start summarize batch in background if there are pending articles."""
    from summarize_worker import _lock
    if _lock.locked():
        return
    stats = get_summary_stats()
    if stats["pending"] > 0:
        logger.info("Auto-triggering summarize: %d pending articles", stats["pending"])
        threading.Thread(target=run_summarize_batch, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_summarize_state()
    if AUTO_COLLECT_ON_START:
        threading.Thread(target=run_collection, daemon=True).start()
    elif ENABLE_SUMMARIZE_WORKER:
        threading.Thread(target=_trigger_summarize_if_pending, daemon=True).start()
    if ENABLE_SCHEDULED_COLLECT:
        scheduler.add_job(
            run_collection, "interval", hours=COLLECT_INTERVAL_HOURS,
            id="rss_collect", coalesce=True, max_instances=1,
        )
    if ENABLE_SUMMARIZE_WORKER:
        scheduler.add_job(run_summarize_batch, "interval", minutes=SUMMARIZE_INTERVAL_MINUTES, id="summarize", coalesce=True, max_instances=1)
    scheduler.add_job(lambda: prune_old_articles(90), "cron", day_of_week="sun", hour=3, id="db_prune")
    scheduler.add_job(vacuum_db, "cron", day=1, hour=4, id="db_vacuum")
    scheduler.start()
    yield
    stop_summarize()
    scheduler.shutdown(wait=False)


app = FastAPI(title="Research Newsletter Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "collecting": _collect_lock.locked(),
        "last_collect": last_collect,
        "auto_collect_on_start": AUTO_COLLECT_ON_START,
        "scheduled_collect_enabled": ENABLE_SCHEDULED_COLLECT,
        "summary": {
            **get_summary_stats(),
            "last_run_at": last_summarize["at"],
            "rate_per_min": last_summarize["rate_per_min"],
            "last_elapsed": last_summarize["elapsed"],
        },
    }


@app.post("/collect", status_code=202)
def trigger_collect(
    request: Request,
    x_admin_token: str = Header(default=""),
):
    """Trigger RSS collection in background. Returns 202 immediately.
    If already collecting, returns status=already_collecting without starting a new run."""
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local access only")
    if COLLECT_TOKEN and not secrets.compare_digest(x_admin_token, COLLECT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")
    if _collect_lock.locked():
        return {"status": "already_collecting", **last_collect}
    threading.Thread(target=run_collection, daemon=True).start()
    return {"status": "accepted", "collecting": True}


@app.post("/reset_failed", status_code=200)
def reset_failed(request: Request):
    """Reset all failed articles back to pending so they can be retried."""
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local access only")
    from database import get_connection
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE articles SET summary_status='pending', summary_attempt_count=0 WHERE summary_status='failed'"
        )
        conn.commit()
        return {"reset": cur.rowcount}
    finally:
        conn.close()


@app.post("/summarize", status_code=202)
def trigger_summarize(
    request: Request,
    x_admin_token: str = Header(default=""),
):
    """Trigger summarization batch immediately in background."""
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local access only")
    if COLLECT_TOKEN and not secrets.compare_digest(x_admin_token, COLLECT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")
    from summarize_worker import _lock
    if _lock.locked():
        return {"status": "already_running"}
    threading.Thread(target=run_summarize_batch, daemon=True).start()
    return {"status": "accepted"}


@app.get("/stats", response_class=HTMLResponse)
def stats_page():
    """HTML dashboard showing summarization progress."""
    from database import get_connection
    stats = get_summary_stats()
    total = stats["ok"] + stats["pending"] + stats["failed"]
    pct = round(stats["ok"] / total * 100, 1) if total > 0 else 0
    bar_filled = int(pct / 2)
    bar_empty = 50 - bar_filled

    rate = last_summarize.get("rate_per_min", 0) or 0
    eta_str = f"{round(stats['pending'] / rate)}분" if rate > 0 and stats["pending"] > 0 else ("완료!" if stats["pending"] == 0 else "계산 중...")
    last_run = last_summarize.get("at") or "아직 없음"
    last_ok = last_summarize.get("ok", 0)
    last_elapsed = last_summarize.get("elapsed", 0)

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT title, source_name, summary, published_at, url
            FROM articles WHERE summary_status = 'ok'
            ORDER BY rowid DESC LIMIT 12
        """).fetchall()
        recent = [dict(r) for r in rows]
    finally:
        conn.close()

    recent_html = "".join(
        f"""<a class="article" href="{html.escape(r['url'] or '#')}" target="_blank" rel="noopener">
            <div class="article-title">{html.escape(r['title'] or '(제목없음)')}</div>
            <div class="article-meta">{html.escape(r['source_name'] or '')} · {(r['published_at'] or '')[:10]}</div>
            <div class="article-summary">{html.escape(r['summary'] or '')}</div>
        </a>"""
        for r in recent
    )

    from summarize_worker import BATCH_SIZE, PARALLEL_WORKERS, MIN_CALL_INTERVAL

    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RSS 요약 현황</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f13; color: #e0e0e0; padding: 24px; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; color: #fff; margin-bottom: 4px; }}
  .subtitle {{ color: #666; font-size: 0.8rem; margin-bottom: 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #1a1a24; border-radius: 10px; padding: 16px; border: 1px solid #2a2a3a; }}
  .card-label {{ font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
  .card-value {{ font-size: 1.8rem; font-weight: 700; }}
  .card-value.ok {{ color: #4ade80; }}
  .card-value.pending {{ color: #facc15; }}
  .card-value.failed {{ color: #f87171; }}
  .card-value.total {{ color: #60a5fa; }}
  .progress-wrap {{ background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 10px; padding: 20px; margin-bottom: 24px; }}
  .progress-header {{ display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 0.85rem; }}
  .progress-pct {{ font-size: 1.1rem; font-weight: 700; color: #4ade80; }}
  .bar-bg {{ background: #2a2a3a; border-radius: 99px; height: 18px; overflow: hidden; }}
  .bar-fill {{ height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 99px; transition: width 0.4s; width: {pct}%; }}
  .meta-row {{ display: flex; gap: 24px; margin-top: 12px; font-size: 0.8rem; color: #888; }}
  .meta-row span b {{ color: #ccc; }}
  .config-wrap {{ background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 10px; padding: 16px; margin-bottom: 24px; font-size: 0.8rem; color: #888; }}
  .config-wrap b {{ color: #ccc; }}
  .config-row {{ display: flex; gap: 20px; flex-wrap: wrap; }}
  .section-title {{ font-size: 0.85rem; font-weight: 600; color: #aaa; margin-bottom: 12px; }}
  .article {{ display: block; background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 8px; padding: 14px; margin-bottom: 8px; text-decoration: none; color: inherit; cursor: pointer; }}
  .article:hover {{ border-color: #4a4a6a; background: #1f1f2e; }}
  .article-title {{ font-size: 0.85rem; font-weight: 600; color: #e0e0e0; margin-bottom: 4px; line-height: 1.4; }}
  .article-meta {{ font-size: 0.7rem; color: #666; margin-bottom: 6px; }}
  .article-summary {{ font-size: 0.78rem; color: #aaa; line-height: 1.5; }}
  .refresh-note {{ text-align: right; font-size: 0.7rem; color: #444; margin-top: 12px; }}
  .trigger-btn {{ background: #1d4ed8; color: #fff; border: none; border-radius: 6px; padding: 6px 14px; font-size: 0.78rem; cursor: pointer; margin-left: 12px; }}
  .trigger-btn:hover {{ background: #2563eb; }}
</style>
</head>
<body>
<h1>📊 RSS 요약 현황</h1>
<div class="subtitle">마지막 갱신: <span id="now">{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</span>
  <button class="trigger-btn" onclick="triggerSummarize()">▶ 지금 요약 실행</button>
</div>

<div class="cards">
  <div class="card"><div class="card-label">전체 기사</div><div class="card-value total">{total:,}</div></div>
  <div class="card"><div class="card-label">요약 완료</div><div class="card-value ok">{stats['ok']:,}</div></div>
  <div class="card"><div class="card-label">대기 중</div><div class="card-value pending">{stats['pending']:,}</div></div>
  <div class="card"><div class="card-label">실패</div><div class="card-value failed">{stats['failed']:,}</div></div>
</div>

<div class="progress-wrap">
  <div class="progress-header">
    <span>요약 진행률</span>
    <span class="progress-pct">{pct}% ({stats['ok']:,} / {total:,})</span>
  </div>
  <div class="bar-bg"><div class="bar-fill"></div></div>
  <div class="meta-row">
    <span>속도: <b>{rate}/분</b></span>
    <span>예상 완료: <b>{eta_str}</b></span>
    <span>마지막 배치: <b>{last_run[:19] if len(str(last_run)) > 10 else last_run}</b></span>
    <span>직전 처리: <b>{last_ok}건 / {last_elapsed}초</b></span>
  </div>
</div>

<div class="config-wrap">
  <div class="config-row">
    <span>⚙ 배치 크기: <b>{BATCH_SIZE}</b></span>
    <span>병렬 Workers: <b>{PARALLEL_WORKERS}</b></span>
    <span>API 간격: <b>{MIN_CALL_INTERVAL}s</b></span>
    <span>스케줄 간격: <b>{SUMMARIZE_INTERVAL_MINUTES}분</b></span>
  </div>
</div>

<div class="section-title">최근 요약 완료 기사 (최신 12건)</div>
{recent_html}

<div class="refresh-note">5초마다 자동 갱신</div>

<script>
let countdown = 5;
setInterval(() => {{
  countdown--;
  if (countdown <= 0) {{ location.reload(); }}
}}, 1000);

function triggerSummarize() {{
  fetch('/summarize', {{method:'POST'}})
    .then(r => r.json())
    .then(d => alert('요약 실행: ' + JSON.stringify(d)))
    .catch(e => alert('오류: ' + e));
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=page)


@app.get("/search")
def search(
    query: str = Query(..., description="Search terms (space-separated)"),
    days: int = Query(14, ge=1, le=90, description="Look back N days"),
    limit: int = Query(30, ge=1, le=100),
    brand: BrandFilter = Query(""),
):
    """Search collected articles. Returns articles sorted by tier then recency."""
    articles = search_articles(query, days=days, limit=limit, brand=brand)
    return {
        "query": query,
        "days": days,
        "count": len(articles),
        "articles": articles,
    }


@app.get("/list_recent")
def list_recent(
    hours: int = Query(72, ge=1, le=720),
    brand: BrandFilter = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    """Return recent articles with summary/fallback_text for agent browsing."""
    articles = list_recent_articles(hours=hours, brand=brand, limit=limit)
    return {"hours": hours, "count": len(articles), "articles": articles}


@app.get("/articles/failed")
def list_failed_articles():
    """Return articles with summary_status='failed'."""
    from database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, title, url, source_name, published_at, summary_attempt_count
            FROM articles WHERE summary_status = 'failed'
            ORDER BY collected_at DESC
        """).fetchall()
        return {"count": len(rows), "articles": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/article/{article_id}/retry")
def retry_article(article_id: int):
    """Reset a failed article to pending so it gets re-summarized."""
    from database import get_connection
    conn = get_connection()
    try:
        result = conn.execute(
            "UPDATE articles SET summary_status='pending', summary_attempt_count=0, summary=NULL WHERE id=? AND summary_status='failed'",
            (article_id,),
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Article not found or not failed")
        return {"retrying": article_id}
    finally:
        conn.close()


@app.delete("/article/{article_id}")
def delete_article(article_id: int):
    """Permanently delete an article from the DB."""
    from database import get_connection
    conn = get_connection()
    try:
        result = conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Article not found")
        return {"deleted": article_id}
    finally:
        conn.close()


@app.get("/article/{article_id}")
def get_article(article_id: int):
    """Return full article record including content_text if available."""
    article = get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


_VALID_KINDS = {"rss_excerpt", "verified_quote"}
_VALID_STATUSES = {"complete", "partial", "insufficient_data"}
_STATUS_TOPIC_RANGE = {
    "complete": (5, 5),
    "partial": (4, 4),
    "insufficient_data": (1, 3),
}

@app.post("/validate_proposal")
def validate_proposal(payload: dict):
    """
    Validate a research_proposal JSON.
    Returns proposal_errors (structural) + evidence_results (per-evidence, with path).
    """
    proposal_errors: list[dict] = []
    evidence_results: list[dict] = []
    all_valid = True

    # ── Proposal-level structural validation ────────────────────────────────
    p_type = payload.get("type")
    if p_type != "research_proposal":
        return {"valid": False, "proposal_errors": [{"path": "type", "reason": "must_be_research_proposal"}], "evidence_results": []}

    status = payload.get("status", "")
    if not isinstance(status, str) or status not in _VALID_STATUSES:
        proposal_errors.append({"path": "status", "reason": f"invalid_status (got '{status}', expected one of {sorted(_VALID_STATUSES)})"})
        all_valid = False

    topics = payload.get("topics", [])
    if not isinstance(topics, list) or not topics:
        return {"valid": False, "proposal_errors": [{"path": "topics", "reason": "topics_must_be_non_empty_array"}], "evidence_results": []}

    if status in _STATUS_TOPIC_RANGE:
        lo, hi = _STATUS_TOPIC_RANGE[status]
        if not (lo <= len(topics) <= hi):
            proposal_errors.append({
                "path": "topics",
                "reason": f"{status}_requires_{lo}_to_{hi}_topics (got {len(topics)})"
            })
            all_valid = False

    if status in ("partial", "insufficient_data") and not payload.get("warning"):
        proposal_errors.append({"path": "warning", "reason": f"{status}_requires_warning_field"})
        all_valid = False

    # ── Per-evidence validation ──────────────────────────────────────────────
    for ti, topic in enumerate(topics):
        if not isinstance(topic, dict):
            proposal_errors.append({"path": f"topics[{ti}]", "reason": "topic_must_be_object"})
            all_valid = False
            continue

        topic_articles: set[int] = set()
        evidence = topic.get("evidence", [])
        if not isinstance(evidence, list):
            proposal_errors.append({"path": f"topics[{ti}].evidence", "reason": "evidence_must_be_array"})
            all_valid = False
            evidence = []

        if status == "complete" and len(evidence) < 3:
            proposal_errors.append({
                "path": f"topics[{ti}].evidence",
                "reason": f"complete_requires_min_3_evidence (got {len(evidence)})"
            })
            all_valid = False
        elif status in ("partial", "insufficient_data") and len(evidence) < 1:
            proposal_errors.append({
                "path": f"topics[{ti}].evidence",
                "reason": f"{status}_requires_min_1_evidence_per_topic (got 0)"
            })
            all_valid = False

        for ei, ev in enumerate(evidence):
            path = f"topics[{ti}].evidence[{ei}]"
            if not isinstance(ev, dict):
                evidence_results.append({"path": path, "article_id": None, "kind": None, "valid": False, "reason": "evidence_item_must_be_object"})
                all_valid = False
                continue
            article_id_raw = ev.get("article_id", "")
            kind = ev.get("kind", "")
            if "quote" in ev:
                raw_quote = ev["quote"]
            elif "excerpt" in ev:
                raw_quote = ev["excerpt"]
            else:
                raw_quote = ""
            if not isinstance(raw_quote, str):
                evidence_results.append({"path": path, "article_id": article_id_raw, "kind": kind, "valid": False, "reason": "quote_must_be_string"})
                all_valid = False
                continue
            quote = raw_quote
            result: dict = {"path": path, "article_id": article_id_raw, "kind": kind, "valid": False, "reason": None}

            # Unknown kind → reject
            if not isinstance(kind, str) or kind not in _VALID_KINDS:
                result["reason"] = f"invalid_evidence_kind (got '{kind}', expected rss_excerpt or verified_quote)"
                evidence_results.append(result)
                all_valid = False
                continue

            # Safe article_id parsing
            m = _ARTICLE_ID_RE.fullmatch(str(article_id_raw).strip())
            if not m:
                result["reason"] = "invalid_article_id_format"
                evidence_results.append(result)
                all_valid = False
                continue
            art_id = int(m.group(1))

            # Duplicate article within same topic
            if art_id in topic_articles:
                result["reason"] = "duplicate_article_in_topic"
                evidence_results.append(result)
                all_valid = False
                continue
            topic_articles.add(art_id)

            article = get_article_by_id(art_id)
            if not article:
                result["reason"] = "article_not_found"
                evidence_results.append(result)
                all_valid = False
                continue

            norm_quote = _normalize(quote)
            # Min length was 20 but Google News RSS often returns short descriptions;
            # 15 still excludes single brand+number fragments, which _is_brand_number_only catches below.
            if len(norm_quote) < 15:
                result["reason"] = "quote_too_short"
                evidence_results.append(result)
                all_valid = False
                continue

            if _is_brand_number_only(norm_quote):
                result["reason"] = "quote_brand_or_number_only"
                evidence_results.append(result)
                all_valid = False
                continue

            # verified_quote requires content_text; rss_excerpt uses description
            if kind == "verified_quote":
                if not article.get("content_text"):
                    result["reason"] = "content_text_missing"
                    evidence_results.append(result)
                    all_valid = False
                    continue
                source_text = _normalize(article["content_text"])
            else:
                source_text = _normalize(article.get("description") or "")

            if norm_quote in source_text:
                result["valid"] = True
            else:
                result["reason"] = "quote_not_found"
                all_valid = False

            evidence_results.append(result)

    return {"valid": all_valid, "proposal_errors": proposal_errors, "evidence_results": evidence_results}
