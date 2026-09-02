# Major Chess Events → Google Calendar

Automated sync of top-tier chess broadcasts (Candidates, World Championship, Tata Steel,
Norway Chess, Champions Chess Tour, Freestyle Chess, …) from the
[Lichess Broadcast API](https://lichess.org/api#tag/Broadcasts) into a public Google Calendar.

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full specification.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `GOOGLE_CALENDAR_ID` | Target calendar id (e.g. `abc123@group.calendar.google.com`) |
| `GOOGLE_SERVICE_ACCOUNT_KEY` | Service account JSON, raw or base64-encoded |

Locally you may instead drop the key at `service_account.json` in the repo root — it is
git-ignored.

Create the service account in Google Cloud with the Calendar API enabled, then share the
target calendar with the service account's email address, granting
**"Make changes to events"**.

Selection rules live in [config/keywords.json](config/keywords.json). A tour is kept when

> (`tier >= min_tier` **OR** name matches a `keyword`) **AND** name matches no
> `exclude_keyword`

- **`min_tier`** — Lichess's own importance ranking (`3` normal, `4` high, `5` best).
  Default `5` admits only top-tier broadcasts.
- **`keywords`** — rescues events Lichess ranks lower than they stream; the Global Chess
  League is tier 4.
- **`exclude_keywords`** — drops the lower sections of a festival. Prague ships as
  Masters + Challengers + Futures and only Masters is major. Note that `women` is
  deliberately absent here: the Women's World Championship *is* a major event.

Lower `min_tier` to `4` for a busier calendar. `max_days_ahead` (default 400) ignores
rounds scheduled further out, since those schedules churn.

### Rounds and rest days

Each calendar event is one playing session, built from that round's own `startsAt`. Rest
days therefore need no special handling — a day with no scheduled round simply produces
no event. Round names are normalised (`Round 03` → `Round 3`) and appear in the event
summary; `skip_round_patterns` drops scheduling artifacts such as opening ceremonies and
drawing of lots.

With `collapse_same_day` (default `true`), a tour's rounds on the same UTC day merge into
one event running from the first start to the last finish, labelled `Rounds 1-4`, with the
session count noted in the description. Team leagues play several simultaneous matches per
day — the Global Chess League fields four — which would otherwise be four entries on one
day. Set it to `false` for one event per round.

Collapsed events take a day-based sync key (`…:<tourId>:day-2026-09-05`) rather than a
round-based one, so adding a session to a day that is already on the calendar does not
create a duplicate entry.

### Coverage limit

Lichess relays over-the-board chess, so **online Chess.com events — Champions Chess Tour,
Speed Chess Championship, Titled Tuesday — are out of scope** and their keywords have been
removed rather than left in place implying coverage that does not exist. Freestyle Chess,
World Rapid and World Blitz stay, as those are over-the-board and do get relayed.

## Usage

```bash
python -m src.main --dry-run     # list what would be synced, no writes
python -m src.main               # sync
python -m src.main --verbose     # debug logging
```

## Automation

[.github/workflows/sync_calendar.yml](.github/workflows/sync_calendar.yml) runs daily at
00:00 UTC and on manual dispatch. Add `GOOGLE_SERVICE_ACCOUNT_KEY` and
`GOOGLE_CALENDAR_ID` as repository secrets.

## Deduplication

Each created event carries a private `syncKey` extended property
(`chess-calendar-sync:<tourId>:<roundId>`). Reruns skip any round whose key — or whose
summary + start time — already exists on the calendar, so the job is safe to run
repeatedly.

Rounds without a published start time are skipped; rounds without an end time default to
a 4-hour duration.

Note that `/api/broadcast` has been observed returning the same page for every `page`
value, so the fetcher de-duplicates tours by id and stops paging once a page adds nothing
new.
