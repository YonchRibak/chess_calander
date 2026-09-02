"""Google Calendar authentication, event formatting and write operations."""

import base64
import binascii
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from google.oauth2 import service_account
from googleapiclient.discovery import build

LOG = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = "service_account.json"
EVENT_SOURCE_TAG = "chess-calendar-sync"


def _load_credentials_info():
    """Credentials come from the env (raw JSON or base64) or a local file."""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if raw:
        raw = raw.strip()
        if not raw.startswith("{"):
            try:
                raw = base64.b64decode(raw).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise ValueError(
                    "GOOGLE_SERVICE_ACCOUNT_KEY is neither JSON nor valid base64"
                ) from exc
        return json.loads(raw)

    if os.path.exists(SERVICE_ACCOUNT_FILE):
        with open(SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)

    raise RuntimeError(
        "No credentials found: set GOOGLE_SERVICE_ACCOUNT_KEY or provide "
        f"{SERVICE_ACCOUNT_FILE}"
    )


def get_service():
    credentials = service_account.Credentials.from_service_account_info(
        _load_credentials_info(), scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def get_calendar_id():
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not calendar_id:
        raise RuntimeError("GOOGLE_CALENDAR_ID environment variable is not set")
    return calendar_id


def _youtube_search_link(tour_name):
    query = quote_plus(f"{tour_name} live stream")
    return f"https://www.youtube.com/results?search_query={query}"


def event_key(event):
    """Stable identity for a broadcast round, used for deduplication."""
    return f"{EVENT_SOURCE_TAG}:{event['tour_id']}:{event['round_id']}"


def build_calendar_event(event):
    summary = f"♟️ {event['tour_name']}"
    if event.get("round_name"):
        summary = f"{summary} - {event['round_name']}"

    broadcast_link = event.get("round_url") or event.get("tour_url")
    description_lines = []
    sessions = event.get("sessions") or []
    if len(sessions) > 1:
        description_lines.append(f"{len(sessions)} sessions on this day (UTC):")
        for session in sessions:
            label = session.get("name") or "Session"
            description_lines.append(f"  {session['start']:%H:%M}  {label}")
        description_lines.append("")

    description_lines += [
        f"Broadcast: {broadcast_link}",
        f"Tournament: {event['tour_url']}",
        f"Live stream search: {_youtube_search_link(event['tour_name'])}",
        "",
        "All times are stored in UTC and displayed in your local timezone.",
    ]
    if event.get("tour_description"):
        description_lines.insert(0, event["tour_description"] + "\n")

    return {
        "summary": summary,
        "description": "\n".join(description_lines),
        "location": broadcast_link,
        "start": {"dateTime": event["start"].isoformat().replace("+00:00", "Z"), "timeZone": "UTC"},
        "end": {"dateTime": event["end"].isoformat().replace("+00:00", "Z"), "timeZone": "UTC"},
        "source": {"title": "Lichess Broadcast", "url": broadcast_link},
        "extendedProperties": {"private": {"syncKey": event_key(event)}},
    }


def list_existing_keys(service, calendar_id, days_back=1, days_ahead=365):
    """Return sync keys (and summary+start fallbacks) of current calendar events."""
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_back)).isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=days_ahead)).isoformat().replace("+00:00", "Z")

    keys = set()
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("items", []):
            sync_key = (
                item.get("extendedProperties", {}).get("private", {}).get("syncKey")
            )
            if sync_key:
                keys.add(sync_key)
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            keys.add(f"summary:{item.get('summary', '')}|{start}")

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return keys


def is_duplicate(event, existing_keys):
    if event_key(event) in existing_keys:
        return True
    payload = build_calendar_event(event)
    fallback = f"summary:{payload['summary']}|{payload['start']['dateTime']}"
    return fallback in existing_keys


def insert_event(service, calendar_id, event):
    payload = build_calendar_event(event)
    created = (
        service.events().insert(calendarId=calendar_id, body=payload).execute()
    )
    LOG.info("Created event: %s", payload["summary"])
    return created
