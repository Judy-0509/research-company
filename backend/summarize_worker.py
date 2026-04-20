"""Background summarization worker.

Pulls articles with summary_status='pending' from SQLite and generates
1-2 sentence summaries via the GLM API (OpenAI-compatible).

Schedule: every 10 min via APScheduler (main.py).
Lock: threading.Lock prevents concurrent runs.
Retry: up to RETRY_LIMIT per article; FAIL_LIMIT failures → summary_status='failed'.
Parallel: SUMMARIZE_WORKERS threads call GLM concurrently (default 5).
"""
import concurrent.futures
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from database import get_connection

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_stop_flag = threading.Event()

_STATE_FILE = Path(__file__).parent / "summarize_state.json"

last_summarize: dict = {"at": None, "ok": 0, "failed": 0, "skipped": 0, "elapsed": 0.0, "rate_per_min": 0.0}


def _load_state() -> None:
    """Load persisted last_summarize from disk (survives restarts)."""
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            last_summarize.update(data)
    except Exception:
        pass


def _save_state() -> None:
    try:
        _STATE_FILE.write_text(json.dumps(last_summarize), encoding="utf-8")
    except Exception:
        pass

try:
    BATCH_SIZE = max(1, min(500, int(os.environ.get("SUMMARIZE_BATCH_SIZE", "40"))))
except ValueError:
    logger.warning("Invalid SUMMARIZE_BATCH_SIZE env var, defaulting to 40")
    BATCH_SIZE = 40

try:
    WALL_CLOCK_LIMIT = max(60, int(os.environ.get("SUMMARIZE_WALL_CLOCK", "3600")))
except ValueError:
    logger.warning("Invalid SUMMARIZE_WALL_CLOCK env var, defaulting to 3600")
    WALL_CLOCK_LIMIT = 3600

try:
    PARALLEL_WORKERS = max(1, min(20, int(os.environ.get("SUMMARIZE_WORKERS", "3"))))
except ValueError:
    logger.warning("Invalid SUMMARIZE_WORKERS env var, defaulting to 3")
    PARALLEL_WORKERS = 3

try:
    MIN_CALL_INTERVAL = max(0.0, float(os.environ.get("SUMMARIZE_CALL_INTERVAL", "0.8")))
except ValueError:
    MIN_CALL_INTERVAL = 0.8

RETRY_LIMIT = 3
FAIL_LIMIT = 5

# Rate limiter: enforces MIN_CALL_INTERVAL between consecutive GLM calls
_rate_lock = threading.Lock()
_last_call_time: float = 0.0


def _throttled_call(title: str, description: str, language: str) -> str:
    """Call GLM with inter-request throttling to avoid 429."""
    global _last_call_time
    with _rate_lock:
        now = time.monotonic()
        wait = MIN_CALL_INTERVAL - (now - _last_call_time)
        if wait > 0:
            time.sleep(wait)
        _last_call_time = time.monotonic()
    return _call_glm(title, description, language)

GLM_API_KEY = os.environ.get("GLM_API_KEY", "")
GLM_API_URL = os.environ.get("GLM_API_URL", "https://api.z.ai/api/paas/v4/chat/completions")
GLM_MODEL = os.environ.get("SUMMARIZE_MODEL", "glm-4.7")
# GLM-4.7 defaults to thinking mode: content="" and reasoning_content holds chain-of-thought.
# We disable thinking so content holds the final summary.
# Never fall back to reasoning_content — it is CoT, not a usable summary.
GLM_DISABLE_THINKING = os.environ.get("GLM_DISABLE_THINKING", "true").lower() == "true"


def _call_glm(title: str, description: str, language: str) -> str:
    """Return a 1-2 sentence summary. Raises on failure."""
    if language == "ko":
        instruction = (
            "다음 기사를 한국어로 3~4문장으로 요약하라. "
            "① 핵심 사실, ② 주요 수치·스펙, ③ 업계 의미 또는 시장 맥락 순서로 작성하라. "
            "숫자·고유명사·브랜드명은 원문 그대로 유지하라."
        )
    else:
        instruction = (
            "Summarize the following article in 3-4 sentences in English. "
            "Follow this order: ① core facts, ② key numbers or specs, ③ industry significance or market context. "
            "Preserve all numbers, brand names, and proper nouns exactly."
        )

    content = f"Title: {title}\n\n{description}"
    payload = {
        "model": GLM_MODEL,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": content},
        ],
        "max_tokens": 512,
        "temperature": 0.2,
    }
    if GLM_DISABLE_THINKING:
        payload["thinking"] = {"type": "disabled"}

    logger.debug(
        "GLM call: model=%s max_tokens=%s temperature=%s thinking_disabled=%s",
        payload["model"], payload["max_tokens"], payload["temperature"], GLM_DISABLE_THINKING,
    )

    resp = requests.post(
        GLM_API_URL,
        headers={"Authorization": f"Bearer {GLM_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    if not text:
        raise ValueError(
            f"GLM returned empty content (model={GLM_MODEL}, thinking_disabled={GLM_DISABLE_THINKING})"
        )
    return text


def _fetch_pending(conn, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, title, description, language, summary_attempt_count
        FROM articles
        WHERE summary_status = 'pending'
          AND summary_attempt_count < ?
        ORDER BY collected_at DESC
        LIMIT ?
        """,
        (FAIL_LIMIT, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _summarize_one(art: dict) -> tuple[int, str | None, int]:
    """Call GLM for one article. Returns (art_id, result_or_None, attempt_count)."""
    art_id = art["id"]
    attempt = art["summary_attempt_count"]

    for retry in range(RETRY_LIMIT):
        if _stop_flag.is_set():
            return art_id, None, attempt
        try:
            result = _throttled_call(
                art["title"] or "",
                art["description"] or "",
                art["language"] or "en",
            )
            return art_id, result, attempt
        except Exception as e:
            err_str = str(e)
            # 429: back off much longer to let the rate limit window reset
            if "429" in err_str:
                wait = 30 * (retry + 1)
            else:
                wait = 2 ** retry
            logger.warning(
                "summarize_worker: article %d attempt %d GLM failed: %s (retry in %ds)",
                art_id, retry + 1, e, wait,
            )
            if retry < RETRY_LIMIT - 1:
                _stop_flag.wait(timeout=wait)  # interruptible sleep

    return art_id, None, attempt


def _write_result(art_id: int, glm_result: str | None, attempt: int) -> str:
    """Write GLM result to DB. Returns 'ok', 'failed', or 'skipped'."""
    conn = get_connection()
    try:
        if glm_result is not None:
            conn.execute(
                "UPDATE articles SET summary=?, summary_status='ok', summary_attempt_count=summary_attempt_count+1 WHERE id=?",
                (glm_result, art_id),
            )
            conn.commit()
            return "ok"
        else:
            new_attempt = attempt + RETRY_LIMIT
            new_status = "failed" if new_attempt >= FAIL_LIMIT else "pending"
            conn.execute(
                "UPDATE articles SET summary_status=?, summary_attempt_count=? WHERE id=?",
                (new_status, new_attempt, art_id),
            )
            conn.commit()
            return "failed" if new_status == "failed" else "skipped"
    except Exception:
        logger.exception(
            "summarize_worker: DB update failed for article %d (GLM result not re-called)", art_id
        )
        return "skipped"
    finally:
        conn.close()


def run_summarize_batch() -> None:
    """Called by APScheduler every 10 minutes. Runs GLM calls in parallel."""
    if not GLM_API_KEY:
        logger.warning("summarize_worker: GLM_API_KEY not set, skipping")
        return

    if not _lock.acquire(blocking=False):
        logger.info("summarize_worker: already running, skipping")
        return

    _stop_flag.clear()
    start = time.monotonic()
    ok = failed = skipped = 0

    try:
        fetch_conn = get_connection()
        try:
            articles = _fetch_pending(fetch_conn, BATCH_SIZE)
        finally:
            fetch_conn.close()

        logger.info(
            "summarize_worker: %d pending articles, %d parallel workers",
            len(articles), PARALLEL_WORKERS,
        )

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS)
        try:
            future_to_art = {
                executor.submit(_summarize_one, art): art
                for art in articles
            }
            for future in concurrent.futures.as_completed(future_to_art):
                if _stop_flag.is_set():
                    logger.info("summarize_worker: stop requested")
                    break
                if time.monotonic() - start > WALL_CLOCK_LIMIT:
                    logger.info("summarize_worker: wall-clock limit reached")
                    _stop_flag.set()  # wake up sleeping threads immediately
                    break

                try:
                    art_id, glm_result, attempt = future.result()
                except Exception:
                    skipped += 1
                    continue

                outcome = _write_result(art_id, glm_result, attempt)
                if outcome == "ok":
                    ok += 1
                elif outcome == "failed":
                    failed += 1
                else:
                    skipped += 1

                # Live progress update (so /health shows non-zero rate mid-batch)
                elapsed = time.monotonic() - start
                processed = ok + failed + skipped
                last_summarize["at"] = datetime.now(timezone.utc).isoformat()
                last_summarize["ok"] = ok
                last_summarize["failed"] = failed
                last_summarize["skipped"] = skipped
                last_summarize["elapsed"] = round(elapsed, 1)
                last_summarize["rate_per_min"] = round((processed / elapsed) * 60, 1) if elapsed > 0 else 0.0
                if processed % 10 == 0:
                    _save_state()

        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        elapsed = time.monotonic() - start
        processed = ok + failed + skipped
        last_summarize["at"] = datetime.now(timezone.utc).isoformat()
        last_summarize["ok"] = ok
        last_summarize["failed"] = failed
        last_summarize["skipped"] = skipped
        last_summarize["elapsed"] = round(elapsed, 1)
        last_summarize["rate_per_min"] = round((processed / elapsed) * 60, 1) if elapsed > 0 else 0.0
        _save_state()
        logger.info(
            "summarize_worker: done — ok=%d failed=%d skipped=%d elapsed=%.1fs",
            ok, failed, skipped, time.monotonic() - start,
        )
    except Exception:
        logger.exception("summarize_worker: unexpected error")
    finally:
        _lock.release()


def request_stop() -> None:
    """Signal the running batch to stop gracefully."""
    _stop_flag.set()
