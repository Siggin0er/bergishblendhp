"""Importiert den öffentlichen Google-Kalender (ICS) nach website/events.json."""
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

TZ = ZoneInfo("Europe/Berlin")
OUT = Path(__file__).resolve().parents[2] / "website" / "events.json"
HORIZON_DAYS = 366
MAX_DESCRIPTION = 1000


def fail(msg):
    # Keine Exception-Details ausgeben: sie könnten die geheime URL enthalten.
    print(f"Fehler: {msg}", file=sys.stderr)
    sys.exit(1)


def fetch_ics(url):
    if not url.startswith("https://"):
        fail("GOOGLE_CALENDAR_ICS_URL muss mit https:// beginnen.")
    req = urllib.request.Request(url, headers={"User-Agent": "bergish-blend-sync"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(10_000_000)
    except Exception as exc:
        fail(f"Kalender konnte nicht abgerufen werden ({type(exc).__name__}).")
    if b"BEGIN:VCALENDAR" not in data:
        fail("Antwort ist kein gültiger ICS-Kalender.")
    return data


def clean_text(value):
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\r", "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_DESCRIPTION]


def to_local(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def normalize(ev):
    start, end = ev.start, ev.end
    if isinstance(start, dt.datetime):
        s = to_local(start)
        e = to_local(end) if isinstance(end, dt.datetime) else s
        end_day = e.date()
        if e > s and e.time() == dt.time(0, 0) and end_day > s.date():
            end_day -= dt.timedelta(days=1)
        item = {
            "date": s.date().isoformat(),
            "endDate": end_day.isoformat(),
            "allDay": False,
            "start": s.strftime("%H:%M"),
            "end": e.strftime("%H:%M") if e > s else None,
        }
    else:
        last = (end - dt.timedelta(days=1)) if isinstance(end, dt.date) and end > start else start
        item = {
            "date": start.isoformat(),
            "endDate": last.isoformat(),
            "allDay": True,
            "start": None,
            "end": None,
        }
    key = f"{ev.get('UID', '')}|{item['date']}|{item['start']}"
    item["id"] = hashlib.sha1(key.encode()).hexdigest()[:12]
    item["title"] = clean_text(ev.get("SUMMARY")) or "Auftritt"
    item["location"] = clean_text(ev.get("LOCATION")).replace("\n", ", ")
    item["description"] = clean_text(ev.get("DESCRIPTION"))
    return item


def main():
    url = os.environ.get("GOOGLE_CALENDAR_ICS_URL", "").strip()
    if not url:
        fail("Secret GOOGLE_CALENDAR_ICS_URL ist nicht gesetzt.")

    try:
        cal = icalendar.Calendar.from_ical(fetch_ics(url))
        today = dt.datetime.now(TZ).date()
        raw = recurring_ical_events.of(cal).between(today, today + dt.timedelta(days=HORIZON_DAYS))
        events = [
            normalize(ev)
            for ev in raw
            if str(ev.get("STATUS", "")).upper() != "CANCELLED"
        ]
    except SystemExit:
        raise
    except Exception as exc:
        fail(f"Kalender konnte nicht verarbeitet werden ({type(exc).__name__}).")

    events.sort(key=lambda e: (e["date"], e["start"] or "", e["title"]))

    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if old.get("events") == events:
        print("Keine Änderungen.")
        return

    payload = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "events": events}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(events)} Termine geschrieben.")


if __name__ == "__main__":
    main()
