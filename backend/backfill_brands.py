"""Run once after adding brand_labels column to populate existing articles."""
from database import get_connection
from brand_labels import assign_brand_labels

conn = get_connection()
rows = conn.execute(
    "SELECT id, title, description FROM articles WHERE brand_labels = '' OR brand_labels IS NULL"
).fetchall()
for row in rows:
    labels = assign_brand_labels(row["title"] or "", row["description"] or "")
    conn.execute("UPDATE articles SET brand_labels = ? WHERE id = ?", (labels, row["id"]))
conn.commit()
conn.close()
print(f"Backfilled {len(rows)} articles")
