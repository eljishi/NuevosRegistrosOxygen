"""Nuevos Registros - retention store for the ggleap offer flow.

Subcommands:
  ingest <csv>       Upsert the full ggleap export into SQLite.
  list [status]      Print tracked users (optional filter: pending|sent|claimed|expired).
  send-offers        Enviar oferta vía Brevo a los usuarios con first_seen_at entre 24h-48h.
  demo               Self-check with a synthetic CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "registros.db"

_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
OFFER_DAYS = 31
RECLAIM_BUFFER_HOURS = 12  # last_visit must be at least this long after first_seen to count as reclaim
SEND_DELAY_HOURS = 24  # offer goes out this long after first_seen
SEND_WINDOW_HOURS = 48  # users older than this are never sent
MIN_OFFER_AGE = 14  # under this age (or unknown birth date) no offer is sent

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TEXT,
    last_visit TEXT,
    first_seen_at TEXT NOT NULL,
    offer_expires_at TEXT NOT NULL,
    offer_sent_at TEXT,
    offer_claimed_at TEXT,
    birth_date TEXT
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "birth_date" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN birth_date TEXT")
    return conn


def parse_ggleap_dt(s: str) -> datetime | None:
    """ggleap format example: '10/16/2026 4:36:34 PM' (US, no leading zeros)."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        return None


def parse_ggleap_birth_date(s: str) -> date | None:
    """ggleap exports birth dates as local midnight shifted to UTC ('6/4/2006 10:00:00 PM'
    means 5 June), so round to the nearest day."""
    dt = parse_ggleap_dt(s)
    return (dt + timedelta(hours=12)).date() if dt else None


def age_on(birth: date, day: date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def ingest(csv_path: Path) -> dict:
    """Insert users not yet tracked (the full export) and update last_visit for tracked ones.

    Also sets offer_claimed_at when a tracked user's Last Visit jumps past first_seen + buffer,
    while the offer window is still open.
    """
    now = datetime.now()
    conn = connect()
    inserts = reclaims = updates = 0

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            email = (row.get("Email") or "").strip().lower()
            if not email:
                continue
            created_at = parse_ggleap_dt(row.get("Created At", ""))
            last_visit = parse_ggleap_dt(row.get("Last Visit", ""))
            birth = parse_ggleap_birth_date(row.get("Date of Birth", ""))
            birth_iso = birth.isoformat() if birth else None

            existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                new_claim = None
                if (
                    last_visit
                    and not existing["offer_claimed_at"]
                    and last_visit > datetime.fromisoformat(existing["first_seen_at"]) + timedelta(hours=RECLAIM_BUFFER_HOURS)
                    and datetime.fromisoformat(existing["offer_expires_at"]) > now
                ):
                    new_claim = last_visit.isoformat()
                    reclaims += 1
                conn.execute(
                    "UPDATE users SET last_visit = ?, offer_claimed_at = COALESCE(offer_claimed_at, ?),"
                    " birth_date = ? WHERE email = ?",
                    (last_visit.isoformat() if last_visit else None, new_claim, birth_iso, email),
                )
                updates += 1
            else:
                if not created_at:
                    continue
                offer_expires = created_at + timedelta(days=OFFER_DAYS)
                conn.execute(
                    """INSERT INTO users
                       (email, username, first_name, last_name, created_at, last_visit, first_seen_at,
                        offer_expires_at, birth_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        email,
                        (row.get("Username") or "").strip(),
                        (row.get("First Name") or "").strip(),
                        (row.get("Last Name") or "").strip(),
                        created_at.isoformat(),
                        last_visit.isoformat() if last_visit else None,
                        created_at.isoformat(),
                        offer_expires.isoformat(),
                        birth_iso,
                    ),
                )
                inserts += 1
    conn.commit()
    conn.close()
    stats = {"inserts": inserts, "updates": updates, "reclaims": reclaims}
    print(f"ingested: {inserts} new, {updates} updated, {reclaims} marked claimed")
    return stats


def status_of(row: sqlite3.Row, now: datetime) -> str:
    if row["offer_claimed_at"]:
        return "claimed"
    age_days = (now - datetime.fromisoformat(row["first_seen_at"])).days
    if age_days < 7:
        return "week"
    if age_days < 31:
        return "month"
    return "expired"


def brevo_state(row: sqlite3.Row, now: datetime) -> str | None:
    """'sent' if already in Brevo, 'pending' if send_offers will add them once
    SEND_DELAY_HOURS have passed, None if they will never enter."""
    if row["offer_sent_at"]:
        return "sent"
    if (
        row["offer_claimed_at"]
        or not row["last_visit"]
        or not row["birth_date"]
        or datetime.fromisoformat(row["first_seen_at"]) < now - timedelta(hours=SEND_WINDOW_HOURS)
        or age_on(date.fromisoformat(row["birth_date"]), now.date()) < MIN_OFFER_AGE
    ):
        return None
    return "pending"


def list_users(status_filter: str | None = None) -> None:
    now = datetime.now()
    conn = connect()
    rows = conn.execute("SELECT * FROM users ORDER BY first_seen_at DESC").fetchall()
    for r in rows:
        st = status_of(r, now)
        if status_filter and st != status_filter:
            continue
        print(f"{st:8} {r['email']:40} first_seen={r['first_seen_at'][:19]} expires={r['offer_expires_at'][:19]}")
    conn.close()


BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"


def _brevo_upsert_contact(api_key: str, email: str, attrs: dict, list_id: int) -> None:
    payload = {"email": email, "attributes": attrs, "listIds": [list_id], "updateEnabled": True}
    req = urllib.request.Request(
        BREVO_CONTACTS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": api_key, "content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Brevo returned {resp.status}: {resp.read()!r}")


def send_offers(dry_run: bool = False) -> dict:
    """Añade a Brevo (lista BREVO_LIST_ID) los usuarios cuya primera captura fue hace 24-48h.

    Solo usuarios que han iniciado sesión alguna vez (last_visit no vacío) y que tienen
    al menos MIN_OFFER_AGE años; sin fecha de nacimiento no se envía.

    El drip (bienvenida + 3d + 21d + 7d) lo dispara Brevo al entrar en la lista.

    Config vía env:
      BREVO_API_KEY   obligatoria (si no, dry-run forzado)
      BREVO_LIST_ID   id numérico de la lista destino
    """
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    list_id = os.environ.get("BREVO_LIST_ID", "").strip()
    if not api_key or not list_id:
        print("WARN: BREVO_API_KEY o BREVO_LIST_ID vacíos — forzando dry-run")
        dry_run = True
    list_id_int = int(list_id) if list_id else 0

    now = datetime.now()
    window_start = now - timedelta(hours=SEND_WINDOW_HOURS)
    window_end = now - timedelta(hours=SEND_DELAY_HOURS)
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM users
           WHERE offer_sent_at IS NULL
             AND offer_claimed_at IS NULL
             AND last_visit IS NOT NULL
             AND birth_date IS NOT NULL
             AND first_seen_at >= ?
             AND first_seen_at <= ?""",
        (window_start.isoformat(), window_end.isoformat()),
    ).fetchall()

    sent = failed = 0
    for r in rows:
        if age_on(date.fromisoformat(r["birth_date"]), now.date()) < MIN_OFFER_AGE:
            continue
        attrs = {"FIRSTNAME": r["first_name"] or "", "LASTNAME": r["last_name"] or ""}
        if dry_run:
            print(f"[dry-run] would add {r['email']} to Brevo list {list_id or '?'}")
            sent += 1
            continue
        try:
            _brevo_upsert_contact(api_key, r["email"], attrs, list_id_int)
            conn.execute("UPDATE users SET offer_sent_at = ? WHERE email = ?", (now.isoformat(), r["email"]))
            sent += 1
        except (urllib.error.URLError, RuntimeError) as e:
            print(f"ERROR añadiendo {r['email']}: {e}")
            failed += 1

    conn.commit()
    conn.close()
    stats = {"sent": sent, "failed": failed, "dry_run": dry_run}
    print(f"send-offers: {sent} añadidos, {failed} fallidos (dry_run={dry_run})")
    return stats


def _demo() -> None:
    import tempfile
    global DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        DB_PATH = Path(tmp) / "t.db"
        csv_path = Path(tmp) / "u.csv"
        now = datetime.now()
        new_dt = now.strftime("%m/%d/%Y %I:%M:%S %p")
        csv_path.write_text(
            "Username,Email,First Name,Last Name,Date of Birth,Created At,Last Visit\n"
            f"newuser,new@test.com,New,User,,{new_dt},{new_dt}\n"
            "olduser,old@test.com,Old,User,,01/01/2020 12:00:00 PM,01/01/2020 12:00:00 PM\n",
            encoding="utf-8",
        )
        stats = ingest(csv_path)
        assert stats["inserts"] == 2, stats  # the full export is stored, old users included
        assert stats["reclaims"] == 0, stats

        later = (now + timedelta(days=2)).strftime("%m/%d/%Y %I:%M:%S %p")
        csv_path.write_text(
            "Username,Email,First Name,Last Name,Date of Birth,Created At,Last Visit\n"
            f"newuser,new@test.com,New,User,,{new_dt},{later}\n",
            encoding="utf-8",
        )
        stats = ingest(csv_path)
        assert stats["reclaims"] == 1, stats
        conn = connect()
        row = conn.execute("SELECT offer_claimed_at FROM users WHERE email = 'new@test.com'").fetchone()
        assert row["offer_claimed_at"], row["offer_claimed_at"]
        conn.close()

        # Only adults-enough who logged in and registered 24-48h ago get the offer.
        fmt = "%m/%d/%Y %I:%M:%S %p"
        day_ago = (now - timedelta(hours=30)).strftime(fmt)
        adult = "1/1/2000 12:00:00 AM"
        minor = (now - timedelta(days=365 * 13)).strftime(fmt)
        csv_path.write_text(
            "Username,Email,First Name,Last Name,Date of Birth,Created At,Last Visit\n"
            f"visitor,visitor@test.com,Visi,Tor,{adult},{day_ago},{day_ago}\n"
            f"ghost,ghost@test.com,Ghost,User,{adult},{day_ago},\n"
            f"kid,kid@test.com,Kid,User,{minor},{day_ago},{day_ago}\n"
            f"nodob,nodob@test.com,No,Dob,,{day_ago},{day_ago}\n"
            f"fresh,fresh@test.com,Fresh,User,{adult},{new_dt},{new_dt}\n",
            encoding="utf-8",
        )
        ingest(csv_path)
        stats = send_offers(dry_run=True)
        assert stats["sent"] == 1, stats

        assert parse_ggleap_birth_date("6/4/2006 10:00:00 PM") == date(2006, 6, 5)
        assert age_on(date(2012, 11, 2), date(2026, 11, 1)) == 13
        assert age_on(date(2012, 11, 1), date(2026, 11, 1)) == 14
    print("demo OK")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s_ing = sub.add_parser("ingest")
    s_ing.add_argument("csv", type=Path)
    s_list = sub.add_parser("list")
    s_list.add_argument("status", nargs="?", choices=["pending", "sent", "claimed", "expired"])
    s_send = sub.add_parser("send-offers")
    s_send.add_argument("--dry-run", action="store_true")
    sub.add_parser("demo")
    args = p.parse_args()
    if args.cmd == "ingest":
        ingest(args.csv)
    elif args.cmd == "list":
        list_users(args.status)
    elif args.cmd == "send-offers":
        send_offers(dry_run=args.dry_run)
    elif args.cmd == "demo":
        _demo()


if __name__ == "__main__":
    main()
