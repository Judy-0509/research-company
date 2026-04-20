"""SQLite database setup and article storage."""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "news.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
    migrations: list[tuple[str, str]] = [
        ("brand_labels",           "ALTER TABLE articles ADD COLUMN brand_labels TEXT DEFAULT ''"),
        ("summary",                "ALTER TABLE articles ADD COLUMN summary TEXT"),
        ("summary_status",         "ALTER TABLE articles ADD COLUMN summary_status TEXT DEFAULT 'pending' CHECK (summary_status IN ('pending','ok','failed'))"),
        ("summary_attempt_count",  "ALTER TABLE articles ADD COLUMN summary_attempt_count INTEGER DEFAULT 0"),
        ("content_text",           "ALTER TABLE articles ADD COLUMN content_text TEXT"),
        ("fetch_status",           "ALTER TABLE articles ADD COLUMN fetch_status TEXT DEFAULT 'pending' CHECK (fetch_status IN ('pending','ok','failed','blocked'))"),
        ("fetch_attempt_count",    "ALTER TABLE articles ADD COLUMN fetch_attempt_count INTEGER DEFAULT 0"),
    ]
    for col, ddl in migrations:
        if col not in existing:
            conn.execute(ddl)
            logger.info("DB migration: added column %s", col)
    conn.commit()
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_summary_status ON articles(summary_status);
        CREATE INDEX IF NOT EXISTS idx_fetch_status ON articles(fetch_status);
    """)


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                source_name TEXT,
                source_tier INTEGER DEFAULT 1,
                language TEXT DEFAULT 'en',
                published_at TEXT,
                keywords TEXT,
                brand_labels TEXT DEFAULT '',
                collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                summary TEXT,
                summary_status TEXT DEFAULT 'pending'
                    CHECK (summary_status IN ('pending','ok','failed')),
                summary_attempt_count INTEGER DEFAULT 0,
                content_text TEXT,
                fetch_status TEXT DEFAULT 'pending'
                    CHECK (fetch_status IN ('pending','ok','failed','blocked')),
                fetch_attempt_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_tier ON articles(source_tier DESC);
        """)
        _ensure_columns(conn)
    finally:
        conn.close()


def insert_articles(articles: list[dict]) -> tuple[int, int]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        inserted = skipped = 0
        for a in articles:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO articles
                        (url, title, description, source_name, source_tier,
                         language, published_at, keywords, brand_labels)
                    VALUES
                        (:url, :title, :description, :source_name, :source_tier,
                         :language, :published_at, :keywords, :brand_labels)
                    """,
                    a,
                )
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("insert failed for %s: %s", a.get("url"), e)
                skipped += 1
        conn.commit()
        return inserted, skipped
    finally:
        conn.close()


VALID_BRANDS = frozenset({
    "apple", "samsung", "huawei", "honor", "xiaomi",
    "oppo", "vivo", "transsion", "cn_oem", "",
})

_DATE_FILTER = (
    "COALESCE(datetime(published_at), datetime(collected_at)) >= datetime('now', ?)"
)
_ORDER_DATE = "COALESCE(datetime(published_at), datetime(collected_at))"


def search_articles(
    query: str, days: int = 14, limit: int = 30, brand: str = ""
) -> list[dict]:
    """Full-text search across title + description, filtered to last N days.

    Uses AND logic (all terms must match). Falls back to OR logic when AND
    returns fewer than 3 results so agents don't get empty result sets.
    """
    conn = get_connection()
    try:
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        if not terms:
            return []

        date_param = f"-{days} days"
        brand_clause = ""
        brand_param: list = []
        if brand and brand in VALID_BRANDS:
            brand_clause = "AND brand_labels LIKE ?"
            brand_param = [f"%,{brand},%"]

        def _run(logic: str) -> list[dict]:
            if logic == "AND":
                per_term = " AND ".join(
                    "(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)" for _ in terms
                )
                p = [v for t in terms for v in (f"%{t}%", f"%{t}%")]
            else:
                per_term = " OR ".join(
                    "(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)" for _ in terms
                )
                p = [v for t in terms for v in (f"%{t}%", f"%{t}%")]
            sql = f"""
                SELECT id, url, title, description, source_name, source_tier,
                       language, published_at, keywords, brand_labels, collected_at
                FROM articles
                WHERE ({per_term})
                  AND {_DATE_FILTER}
                  {brand_clause}
                ORDER BY source_tier DESC, {_ORDER_DATE} DESC
                LIMIT ?
            """
            rows = conn.execute(sql, p + [date_param] + brand_param + [limit]).fetchall()
            return [dict(r) for r in rows]

        results = _run("AND")
        if len(results) < 3 and len(terms) > 1:
            results = _run("OR")
        return results
    finally:
        conn.close()


def list_recent_articles(hours: int = 72, brand: str = "", limit: int = 50) -> list[dict]:
    """Return recent articles with summary/fallback_text for agent browsing."""
    conn = get_connection()
    try:
        params: list = [f"-{hours} hours"]
        where = [_DATE_FILTER]
        if brand and brand in VALID_BRANDS:
            where.append("brand_labels LIKE ?")
            params.append(f"%,{brand},%")
        params.append(limit)
        sql = f"""
            SELECT id, title, source_name AS source, source_tier, published_at, language,
                   summary, summary_status,
                   CASE WHEN summary_status IN ('pending','failed')
                        THEN SUBSTR(description, 1, 200) ELSE NULL END AS fallback_text
            FROM articles
            WHERE {" AND ".join(where)}
            ORDER BY source_tier DESC, {_ORDER_DATE} DESC
            LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_article_by_id(article_id: int) -> dict | None:
    """Return full article record including content_text if available."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, url, title, description, source_name AS source, source_tier,
                   language, published_at, keywords, brand_labels,
                   summary, summary_status, content_text, fetch_status
            FROM articles WHERE id = ?
            """,
            (article_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def prune_old_articles(keep_days: int = 90) -> int:
    cutoff = f"-{keep_days} days"
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM articles WHERE COALESCE(datetime(published_at), datetime(collected_at)) < datetime('now', ?)",
            (cutoff,),
        )
        deleted = cur.rowcount
        conn.commit()
        logger.info("DB prune: deleted %d old articles", deleted)
        return deleted
    finally:
        conn.close()


def vacuum_db() -> None:
    conn = get_connection()
    try:
        conn.execute("VACUUM")
        logger.info("DB vacuum complete")
    except Exception:
        logger.exception("DB vacuum failed (non-critical)")
    finally:
        conn.close()


def get_summary_stats() -> dict:
    """Return pending/failed/ok counts for the summary status dashboard."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT summary_status, COUNT(*) AS cnt FROM articles GROUP BY summary_status"
        ).fetchall()
        counts = {r["summary_status"]: r["cnt"] for r in rows}
        return {
            "pending": counts.get("pending", 0),
            "ok": counts.get("ok", 0),
            "failed": counts.get("failed", 0),
        }
    finally:
        conn.close()
