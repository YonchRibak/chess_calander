# Major Chess Events & Streams Google Calendar Sync

## Overview
This project is an automated Python pipeline that periodically fetches upcoming major chess tournaments from public broadcast APIs (e.g., Lichess Broadcast API) and syncs them to a dedicated public Google Calendar. 

The goal is to provide a central, public calendar feed for top-tier streamable chess events (Candidates, Champions Chess Tour, Tata Steel, Norway Chess, World Championship, Speed Chess Championship, Freestyle Chess, etc.) with direct streaming/broadcast details.

---

## Technical Stack & Environment

### Virtual Environment Requirement
**Yes, a Python virtual environment (`venv`) is required** to isolate dependencies and maintain project structure across local development and GitHub Actions runner environments.

#### Environment Setup Instructions:
```bash
# 1. Create a virtual environment named .venv
python3 -m venv .venv

# 2. Activate the virtual environment
# On macOS / Linux:
source .venv/bin/activate
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# 3. Upgrade pip and install requirements
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Project Structure
```text
.
├── .venv/                         # Virtual environment directory (git-ignored)
├── .github/
│   └── workflows/
│       └── sync_calendar.yml      # GitHub Actions workflow for daily automation
├── config/
│   └── keywords.json              # List of tournament keywords to filter
├── src/
│   ├── __init__.py
│   ├── calendar_service.py        # Google Calendar API authentication & operations
│   ├── fetcher.py                 # Lichess/Chess.com broadcast data fetcher
│   └── main.py                    # Orchestration script entry point
├── .gitignore                     # Git ignore rules (ignore .venv, service_account.json)
├── requirements.txt               # Dependencies list
└── README.md                      # Development and deployment guide
```

---

## Dependencies (`requirements.txt`)
```text
google-api-python-client>=2.100.0
google-auth-httplib2>=0.1.1
google-auth-oauthlib>=1.1.0
requests>=2.31.0
python-dateutil>=2.8.2
```

---

## Core Functional Specifications

### 1. Data Ingestion (`src/fetcher.py`)
* **Source:** Lichess Broadcast API (`GET https://lichess.org/api/broadcast`).
* **Filtering Logic:**
  * Parse incoming events from both `active` and `upcoming` endpoints.
  * Compare event title (`tour.name`) against configured major event keywords (case-insensitive):
    `["candidates", "world championship", "tata steel", "grand chess tour", "speed chess", "champions chess tour", "norway chess", "fide grand prix", "freestyle chess", "world rapid", "world blitz"]`
  * Deduplicate incoming events against current/upcoming calendar events to avoid creating duplicate entries.

### 2. Google Calendar Integration (`src/calendar_service.py`)
* **Authentication:** Use Google Cloud Service Account credentials (`service_account.json` loaded from GitHub Secrets or local file).
* **Calendar ID:** Handled via environment variable `GOOGLE_CALENDAR_ID`.
* **Event Formatting:**
  * **Summary:** `♟️ <Tournament Name> - Round / Stage`
  * **Description:** 
    * Broadcaster / Lichess link
    * Auto-generated YouTube search link for live streaming (`https://www.youtube.com/results?search_query=<Encoded+Tournament+Name>+live+stream`)
    * Timezone notice (UTC/Local)
  * **Start/End Time:** Converted from timestamp milliseconds to RFC3339 UTC strings. Default duration per round/session set to 4 hours if end time is unspecified.

### 3. Orchestrator (`src/main.py`)
* Connects to Google Calendar API.
* Fetches filtered events.
* Checks existing calendar entries to prevent duplicates.
* Inserts missing major broadcast events.

### 4. CI/CD & Automation (`.github/workflows/sync_calendar.yml`)
* Cron schedule running daily (`0 0 * * *`).
* `workflow_dispatch` enabled for manual runs.
* Retrieves `GOOGLE_SERVICE_ACCOUNT_KEY` (base64-encoded or raw JSON string) and `GOOGLE_CALENDAR_ID` from GitHub Repository Secrets.

---

## Security & `.gitignore` Requirements
Ensure `.gitignore` contains:
```text
.venv/
__pycache__/
*.pyc
service_account.json
.env
```
