"""Entry point: fetch major chess broadcasts and sync them to Google Calendar."""

import argparse
import logging
import sys

from src import fetcher

LOG = logging.getLogger("chess_calendar")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report events without writing to the calendar",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


def run(dry_run=False):
    events = fetcher.fetch_major_events()
    if not events:
        LOG.info("No matching upcoming events found.")
        return 0

    if dry_run:
        for event in events:
            LOG.info(
                "[dry-run] %s | %s | %s -> %s",
                event["start"].strftime("%Y-%m-%d %H:%M"),
                event["tour_name"],
                event.get("round_name") or "(unnamed round)",
                event["end"].strftime("%H:%M UTC"),
            )
        LOG.info("[dry-run] %d events would be considered.", len(events))
        return 0

    # Imported lazily so --dry-run works without the Google client libraries.
    from googleapiclient.errors import HttpError

    from src import calendar_service

    service = calendar_service.get_service()
    calendar_id = calendar_service.get_calendar_id()
    existing = calendar_service.list_existing_keys(service, calendar_id)
    LOG.info("Calendar already holds %d indexed entries", len(existing))

    created = skipped = failed = 0
    for event in events:
        if calendar_service.is_duplicate(event, existing):
            skipped += 1
            continue
        try:
            calendar_service.insert_event(service, calendar_id, event)
        except HttpError as exc:
            failed += 1
            LOG.error("Failed to create event %s: %s", event["tour_name"], exc)
            continue
        existing.add(calendar_service.event_key(event))
        created += 1

    LOG.info("Sync complete: %d created, %d skipped, %d failed", created, skipped, failed)
    return 1 if failed else 0


def main(argv=None):
    args = parse_args(argv)
    # Event summaries contain emoji; legacy Windows consoles default to a
    # codepage that cannot encode them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return run(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - top-level guard for CI visibility
        LOG.error("Sync failed: %s", exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
