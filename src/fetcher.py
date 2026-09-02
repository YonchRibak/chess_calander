"""Fetch and filter major chess broadcasts from the Lichess Broadcast API."""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests

LOG = logging.getLogger(__name__)

BROADCAST_URL = "https://lichess.org/api/broadcast"
DEFAULT_ROUND_HOURS = 4
REQUEST_TIMEOUT = 30

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "keywords.json",
)


DEFAULT_MIN_TIER = 5
DEFAULT_MAX_DAYS_AHEAD = 400


def load_config(path=CONFIG_PATH):
    """Read the selection config, lowercasing every match list."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    def lowered(key):
        return [entry.lower() for entry in data.get(key, [])]

    return {
        "keywords": lowered("keywords"),
        "exclude_keywords": lowered("exclude_keywords"),
        "skip_round_patterns": lowered("skip_round_patterns"),
        "min_tier": data.get("min_tier", DEFAULT_MIN_TIER),
        "max_days_ahead": data.get("max_days_ahead", DEFAULT_MAX_DAYS_AHEAD),
        "collapse_same_day": data.get("collapse_same_day", True),
    }


def load_keywords(path=CONFIG_PATH):
    """Read just the configured tournament keywords, lowercased."""
    return load_config(path)["keywords"]


def matches_keywords(name, keywords):
    lowered = (name or "").lower()
    return any(keyword in lowered for keyword in keywords)


def fetch_broadcasts(page_limit=5):
    """Yield raw broadcast tour objects from the Lichess API (ndjson).

    The endpoint has been observed to return the same page regardless of the
    ``page`` parameter, so tours are de-duplicated by id and paging stops as
    soon as a page contributes nothing new.
    """
    seen_ids = set()

    def emit(item):
        """Return the item the first time its tour id is seen, else None."""
        tour_id = (item.get("tour") or {}).get("id")
        if tour_id is None:
            return item
        if tour_id in seen_ids:
            return None
        seen_ids.add(tour_id)
        return item

    for page in range(1, page_limit + 1):
        response = requests.get(
            BROADCAST_URL,
            params={"page": page},
            headers={"Accept": "application/x-ndjson"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        body = response.text.strip()
        if not body:
            return

        # The endpoint historically served ndjson; newer deployments serve a
        # single JSON object with a "currentPageResults" list. Support both.
        if body.startswith("{") and '"currentPageResults"' in body.split("\n", 1)[0]:
            payload = json.loads(body)
            fresh = 0
            for item in payload.get("currentPageResults", []):
                item = emit(item)
                if item is not None:
                    yield item
                    fresh += 1
            if not payload.get("nextPage") or fresh == 0:
                return
            continue

        fresh = 0
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            item = emit(json.loads(line))
            if item is not None:
                yield item
                fresh += 1
        if fresh == 0:
            LOG.debug("Page %d returned no new tours; stopping pagination", page)
            return


def _to_utc(millis):
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def is_major(tour, keywords, min_tier=DEFAULT_MIN_TIER, exclude_keywords=()):
    """A tour qualifies on Lichess's tier ranking or a name keyword.

    Exclusions win over both, so a top-tier festival's Challengers section is
    dropped while its Masters section is kept.
    """
    name = tour.get("name")
    if matches_keywords(name, exclude_keywords):
        return False

    tier = tour.get("tier")
    if min_tier is not None and isinstance(tier, int) and tier >= min_tier:
        return True
    return matches_keywords(name, keywords)


ROUND_NUMBER_RE = re.compile(r"\bround\s*(\d+)", re.IGNORECASE)


def round_label(round_name):
    """Normalise a round name: 'Round 03' -> 'Round 3'; otherwise unchanged."""
    if not round_name:
        return None
    match = ROUND_NUMBER_RE.search(round_name)
    if match:
        return f"Round {int(match.group(1))}"
    return round_name.strip()


def extract_events(
    broadcasts,
    keywords,
    now=None,
    min_tier=DEFAULT_MIN_TIER,
    exclude_keywords=(),
    skip_round_patterns=(),
    max_days_ahead=DEFAULT_MAX_DAYS_AHEAD,
):
    """Turn matching broadcast tours into flat, calendar-ready round events.

    Rest days need no special handling: each event is built from a round's own
    ``startsAt``, so a day with no scheduled round simply produces no event.
    """
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(days=max_days_ahead) if max_days_ahead else None
    events = []

    for broadcast in broadcasts:
        tour = broadcast.get("tour") or {}
        name = tour.get("name")
        if not is_major(tour, keywords, min_tier, exclude_keywords):
            continue

        rounds = broadcast.get("rounds") or []
        for rnd in rounds:
            starts_at = rnd.get("startsAt")
            if not starts_at:
                LOG.debug("Skipping round without start time: %s", rnd.get("name"))
                continue

            if matches_keywords(rnd.get("name"), skip_round_patterns):
                LOG.debug("Skipping non-playing round: %s", rnd.get("name"))
                continue

            start = _to_utc(starts_at)
            if start < now - timedelta(hours=DEFAULT_ROUND_HOURS):
                continue  # already over
            if horizon and start > horizon:
                continue  # beyond the configured horizon

            ends_at = rnd.get("endsAt") or rnd.get("finishedAt")
            end = _to_utc(ends_at) if ends_at else start + timedelta(hours=DEFAULT_ROUND_HOURS)

            events.append(
                {
                    "tour_id": tour.get("id"),
                    "tour_name": name,
                    "tour_url": tour.get("url")
                    or f"https://lichess.org/broadcast/{tour.get('slug', '')}/{tour.get('id', '')}",
                    "tour_description": (tour.get("info") or {}).get("format")
                    or tour.get("description")
                    or "",
                    "round_id": rnd.get("id"),
                    "round_name": round_label(rnd.get("name")),
                    "round_url": rnd.get("url"),
                    "start": start,
                    "end": end,
                }
            )

    events.sort(key=lambda event: event["start"])
    return events


def _merge_round_labels(names):
    """Describe a day's sessions: 'Rounds 3-6', 'Round 3', or a joined name."""
    numbers = []
    for name in names:
        match = ROUND_NUMBER_RE.search(name or "")
        if match:
            numbers.append(int(match.group(1)))

    if numbers and len(numbers) == len(names):
        low, high = min(numbers), max(numbers)
        return f"Round {low}" if low == high else f"Rounds {low}-{high}"

    unique = list(dict.fromkeys(name for name in names if name))
    if len(unique) == 1:
        return unique[0]
    if unique:
        # Names that are not round numbers are usually match pairings, which are
        # far too long for a summary; they go in the description instead.
        return f"{len(unique)} matches"
    return None


def collapse_same_day(events):
    """Merge each tour's same-UTC-day rounds into a single spanning event.

    Team leagues run several simultaneous matches a day, which would otherwise
    become one calendar entry per match.
    """
    grouped = {}
    for event in events:
        key = (event["tour_id"], event["start"].astimezone(timezone.utc).date())
        grouped.setdefault(key, []).append(event)

    merged = []
    for (tour_id, day), group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        group.sort(key=lambda item: item["start"])
        first = dict(group[0])
        first["start"] = min(item["start"] for item in group)
        first["end"] = max(item["end"] for item in group)
        first["round_name"] = _merge_round_labels([i.get("round_name") for i in group])
        first["session_count"] = len(group)
        first["sessions"] = [
            {"name": item.get("round_name"), "start": item["start"]} for item in group
        ]
        # Keyed by day, not by round ids, so adding a session to an existing
        # day does not create a second calendar entry.
        first["round_id"] = f"day-{day.isoformat()}"
        merged.append(first)

    merged.sort(key=lambda item: item["start"])
    return merged


def fetch_major_events(keywords=None, now=None, min_tier=None):
    config = load_config()
    keywords = keywords if keywords is not None else config["keywords"]
    min_tier = min_tier if min_tier is not None else config["min_tier"]

    excludes = config["exclude_keywords"]
    broadcasts = list(fetch_broadcasts())
    LOG.info("Fetched %d distinct broadcast tours from Lichess", len(broadcasts))

    selected = [
        (b.get("tour") or {}).get("name")
        for b in broadcasts
        if is_major(b.get("tour") or {}, keywords, min_tier, excludes)
    ]
    for tour_name in selected:
        LOG.info("Selected tour: %s", tour_name)

    events = extract_events(
        broadcasts,
        keywords,
        now=now,
        min_tier=min_tier,
        exclude_keywords=excludes,
        skip_round_patterns=config["skip_round_patterns"],
        max_days_ahead=config["max_days_ahead"],
    )
    LOG.info(
        "Selected %d of %d tours (tier >= %s or %d keywords, %d exclusions) "
        "-> %d upcoming rounds",
        len(selected),
        len(broadcasts),
        min_tier,
        len(keywords),
        len(excludes),
        len(events),
    )

    if config["collapse_same_day"]:
        before = len(events)
        events = collapse_same_day(events)
        LOG.info("Collapsed same-day rounds: %d -> %d events", before, len(events))

    return events
