"""API JSON para el dashboard de Nuevos Registros.

Run: python backend/server.py
Then: dev frontend en http://localhost:4200 consume http://localhost:8000.
"""
from __future__ import annotations

from datetime import datetime

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import connect, ingest, send_offers, status_of

DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "nuevos.csv"

app = FastAPI(title="Nuevos Registros API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _row_to_user(r, now: datetime) -> dict:
    return {
        "email": r["email"],
        "username": r["username"],
        "firstName": r["first_name"],
        "lastName": r["last_name"],
        "createdAt": r["created_at"],
        "lastVisit": r["last_visit"],
        "firstSeenAt": r["first_seen_at"],
        "offerExpiresAt": r["offer_expires_at"],
        "offerSentAt": r["offer_sent_at"],
        "offerClaimedAt": r["offer_claimed_at"],
        "status": status_of(r, now),
    }


@app.get("/api/users")
def list_users(status: str | None = None):
    now = datetime.now()
    conn = connect()
    rows = conn.execute("SELECT * FROM users ORDER BY first_seen_at DESC").fetchall()
    conn.close()
    users = [_row_to_user(r, now) for r in rows]
    counts = {"week": 0, "month": 0, "claimed": 0, "expired": 0}
    for u in users:
        counts[u["status"]] += 1
    users = [u for u in users if u["status"] != "expired"]
    if status:
        users = [u for u in users if u["status"] == status]
    return {"users": users, "counts": counts}


@app.post("/api/users/{email}/claim")
def mark_claimed(email: str):
    conn = connect()
    cur = conn.execute(
        "UPDATE users SET offer_claimed_at = COALESCE(offer_claimed_at, ?) WHERE email = ?",
        (datetime.now().isoformat(), email),
    )
    conn.commit()
    affected = cur.rowcount
    conn.close()
    if not affected:
        raise HTTPException(404, "user not found")
    return {"ok": True}


@app.delete("/api/users/{email}/claim")
def unmark_claimed(email: str):
    conn = connect()
    cur = conn.execute("UPDATE users SET offer_claimed_at = NULL WHERE email = ?", (email,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    if not affected:
        raise HTTPException(404, "user not found")
    return {"ok": True}


@app.post("/api/ingest")
def ingest_endpoint():
    if not DATA_CSV.exists():
        raise HTTPException(404, f"CSV no encontrado: {DATA_CSV}")
    stats = ingest(DATA_CSV)
    return stats


@app.post("/api/send-offers")
def send_offers_endpoint(dry_run: bool = False):
    return send_offers(dry_run=dry_run)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
