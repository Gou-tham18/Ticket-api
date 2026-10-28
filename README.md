# ticket-api

A small FastAPI service that provides support ticket data, ticket summaries, an AI ticket triage service, and a modern React + TypeScript frontend.

## Requirements

- Python 3.9 or newer (tested on Python 3.13)
- pip
- Node.js 18+ (tested on Node.js 24)
- npm 9+ (tested on npm 11)

## AI Model Setup (Google Gemini)

The ticket triage service calls Google Gemini through the `google-genai` Python package. You need a Gemini API key from https://aistudio.google.com/apikey.

The backend reads these environment variables (from the project-root `.env` file locally, or from the Render service environment when deployed):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | none | Gemini API key used by `/triage` |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | Gemini model ID |
| `TICKETS_DATA_PATH` | No | `data/tickets_sample.csv` | Ticket CSV used by `/tickets` and `/summary` |

Create the backend `.env` file from the template and add your key:

```powershell
Copy-Item .env.example .env
# then edit .env and set GEMINI_API_KEY=<your key>
```

Never commit `.env`; it is ignored by Git.

How `/triage` behaves when Gemini cannot be used:

- **`GEMINI_API_KEY` not set:** the API returns HTTP `503` with a message naming the missing setting. This is a configuration error and is not hidden.
- **Gemini temporarily unavailable** (for example, HTTP 503 "model overloaded", a timeout, or an unreadable response): the API still returns HTTP `200` with a valid result. It uses the keyword-based category, priority `normal` (unless the ticket matches a built-in urgent or high phrase), a category-specific template reply, and the retrieved article IDs. The backend log shows `Gemini unavailable; using fallback triage`.
- **Any other unexpected error:** the API returns HTTP `502` with `Ticket triage service failed.`


## Project structure

task3/
|-- app/
|   |-- escalations.py
|   |-- main.py
|   |-- retrieval.py
|   |-- ticket_summary.py
|   `-- triage_service.py
|-- data/
|   |-- tickets_sample.csv
|   |-- helpdesk_export_sample.csv
|   `-- escalation_tracker_sample.csv
|-- docs/
|   |-- ROOT_CAUSE.md
|   `-- TASK5_ESCALATIONS.md
|-- frontend/
|   `-- React + TypeScript application
|-- kb/
|-- tests/
|-- pytest.ini
|-- requirements.txt
`-- README.md

## Setup & Run Backend

Open a terminal in the project root.

Create and activate a virtual environment on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create `.env` with your `GEMINI_API_KEY` as described in [AI Model Setup](#ai-model-setup-google-gemini).

Optionally set the path to the ticket CSV (it defaults to `data/tickets_sample.csv`):

```powershell
$env:TICKETS_DATA_PATH = ".\data\tickets_sample.csv"
```

Start the API:

```powershell
python -m uvicorn app.main:app --reload
```

Open these URLs:

- Web page (Task 3 static interface): http://127.0.0.1:8000/
- Interactive API documentation: http://127.0.0.1:8000/docs

Keep this backend terminal running.

## Backend API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/tickets?page=1&size=10` | List tickets with pagination |
| GET | `/tickets/{ticket_id}` | Retrieve a ticket by ID |
| GET | `/summary` | Get ticket totals, category counts, and average resolution hours |
| POST | `/triage` | Submit a ticket for AI classification and knowledge-base article retrieval |
| GET | `/helpdesk/tickets` | Task 5: Help Desk export tickets with escalation details and filters |
| GET | `/helpdesk/tickets/{ticket_id}` | Task 5: one Help Desk ticket with its escalation details |
| GET | `/escalations?state=pending&open_only=true` | Task 5: escalations filtered by decision state |
| GET | `/escalations/data-issues` | Task 5: duplicates, orphans, and unreadable values found in the files |
| POST | `/escalations/{ticket_id}/decision` | Task 5: record an Accept or Reject decision |
| GET | `/approvals/urgent-open` | Task 5: urgent open tickets grouped by approval stage |
| POST | `/approvals/{ticket_id}/request` | Task 5: request approval from a manager |

Pagination starts at page 1. Page size must be between 1 and 100.

The summary uses the Day 1 `process_tickets_file()` function from `app/ticket_summary.py`.

Average resolution time includes only tickets with valid creation and resolution timestamps.

The `/triage` endpoint expects a JSON payload:
```json
{
  "subject": "Cannot reset my password",
  "text": "I have not received the password reset email."
}
```
And returns:
```json
{
  "category": "Login",
  "priority": "high",
  "suggested_reply": "Please use the Forgot password option and check your spam folder.",
  "article_ids": ["KB-001"]
}
```

## Run Backend Tests

Activate `.venv`, set `TICKETS_DATA_PATH` as shown above, and run:

```powershell
$env:TICKETS_DATA_PATH = ".\data\tickets_sample.csv"
python -m pytest -q
```

All 84 tests validate summary calculations, pagination, missing-ticket behavior, retrieval logic, ticket triage handling (including the missing-API-key error and the Gemini fallback), and Task 5 escalation tracking. Gemini is mocked, so no API key or network access is needed to run them.

## Task 5: Escalation tracking

Reads the Help Desk export and the escalation tracker the team already uses, joins them by ticket ID, and records Accept or Reject decisions with who decided and when. Source files are never modified; new decisions go to `data/decision_log.csv`.

| Variable | Default |
|---|---|
| `HELPDESK_EXPORT_PATH` | `data/helpdesk_export_sample.csv` |
| `ESCALATION_TRACKER_PATH` | `data/escalation_tracker_sample.csv` |
| `DECISION_LOG_PATH` | `data/decision_log.csv` |
| `APPROVAL_REQUEST_LOG_PATH` | `data/approval_requests.csv` |
| `MANAGERS` | unset: managers are the approvers named in the tracker |

See which urgent open tickets still need manager approval:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/approvals/urgent-open
```

Request approval from a manager:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/approvals/TCK-5110/request `
  -ContentType "application/json" -Body '{"requested_by": "Lia", "approver": "Joyce"}'
```

Record a decision:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/escalations/TCK-5052/decision `
  -ContentType "application/json" -Body '{"decision": "Accept", "decided_by": "Joyce"}'
```

See [docs/TASK5_ESCALATIONS.md](docs/TASK5_ESCALATIONS.md) for the requirements cross-check, decision rules, limitations, and open questions.

---

## Frontend — AI Ticket Triage (React + TypeScript)

A dedicated single-page application built with React, TypeScript, and Vite for classifying support tickets and retrieving relevant knowledge-base articles.

### Frontend Technology Stack

- **React 18** — Component-driven declarative UI.
- **TypeScript** — Strict type safety for requests, responses, and UI state.
- **Vite** — High-performance frontend build tool and local dev server.
- **CSS** — Clean, responsive, and accessible styling with WCAG-compliant contrast and priority indicators.
- **Vitest & React Testing Library** — Automated component and integration testing with mocked network requests.

### Frontend Installation

Open a second terminal window and navigate to the `frontend` directory:

```powershell
cd frontend
npm install
```

### Environment Configuration

The frontend uses Vite environment variables to locate the backend API:

- Copy `.env.example` to `.env`:
  ```powershell
  Copy-Item .env.example .env
  ```
- `.env.example` points `VITE_API_BASE_URL` at the deployed backend (`https://task4-ticket-triage-api.onrender.com`). To use a local backend, set it to `http://127.0.0.1:8000` in `frontend/.env`. If the variable is unset, the frontend falls back to `http://127.0.0.1:8000`.
- Do not store API keys or secrets in frontend environment variables. All AI model keys remain securely on the backend server.

### Start the Frontend Development Server

In the `frontend` directory, run:

```powershell
npm run dev
```

Open your browser at:
`http://localhost:5173/`

### How the Frontend Communicates with FastAPI

1. The user inputs a subject (up to 500 characters) and ticket description (up to 10,000 characters).
2. The form validates that fields are non-empty and trims whitespace.
3. The dedicated API service module (`frontend/src/services/triageApi.ts`) dispatches an HTTP `POST` request to `{VITE_API_BASE_URL}/triage` with:
   ```json
   {
     "subject": "...",
     "text": "..."
   }
   ```
4. While the request is pending, a loading indicator displays *"Analyzing ticket and retrieving relevant articles..."* and form controls are disabled to prevent duplicate submissions.
5. When the response arrives, the client strictly validates the response schema (`isValidTriageResult`) before rendering:
   - **Category**: Visual badge for category classification (Billing, Login, Shipping, Refunds, Technical, Account).
   - **Priority**: Accessible priority indicator (Urgent, High, Normal, Low) using distinct textual indicators, icons, and contrast styling so it does not rely on color alone.
   - **Suggested Reply**: Card containing the AI-generated proposed response.
   - **Relevant Knowledge-Base Articles**: Cited article ID badges (e.g. `KB-001`).
6. Clicking **Clear** resets the input form, validation errors, active loading state, and prior triage results.

### Escalation Tracker (Task 5)

The same app has a second page, **Escalation Tracker**, at `http://localhost:5173/#/escalations` (or use the navigation at the top). The triage page is still the default at `/`.

It uses the Task 5 endpoints through `frontend/src/services/escalationApi.ts`, with the same `VITE_API_BASE_URL` setting:

- `GET /approvals/urgent-open` for the summary counts (urgent open, not yet sent for approval, awaiting decision, accepted, rejected), the manager list, and the table of urgent open tickets. The **Category** and **Status** filters are sent as the `category` and `status` query parameters.
- **Request Approval** on `not_requested` tickets sends `POST /approvals/{ticket_id}/request` with `{"requested_by": "...", "approver": "..."}`. The manager list comes from the API. This only records the request; no email is sent.
- **Accept** / **Reject** on `awaiting_decision` tickets sends `POST /escalations/{ticket_id}/decision` with `{"decision": "Accept" | "Reject", "decided_by": "..."}`.

The list reloads after each successful request or decision. Backend errors (for example `409` when approval was already requested) are shown in the form.

When running locally, set `VITE_API_BASE_URL=http://127.0.0.1:8000` in `frontend/.env`. The page only works against a backend that includes the Task 5 endpoints.

### Run Frontend Tests

The frontend suite uses Vitest and React Testing Library to verify full application behavior without needing a running backend server or external API keys:

```powershell
cd frontend
npm test
```

This runs 22 automated tests. `src/App.test.tsx` has 10 tests for the triage page, and `src/EscalationTracker.test.tsx` has 12 for the Escalation Tracker (navigation, summary counts from the API, table contents, filters as query parameters, empty and error states, the exact request and decision JSON, validation, and refresh after success). The triage tests cover:
1. Main page header and description rendering.
2. Subject and description inputs, submit, and clear buttons.
3. Validation and rejection of empty and whitespace-only submissions.
4. Successful response rendering (category, priority, suggested reply, article IDs).
5. Loading indicator display and button disabling during in-flight requests.
6. HTTP 422 validation error handling.
7. HTTP 502 service/model error handling.
8. Network failure handling (when backend is unreachable).
9. Malformed or invalid JSON response handling without crashing.
10. Reset behavior clearing form inputs, errors, and prior results.

### Production Build

To verify TypeScript compilation and create an optimized production bundle:

```powershell
cd frontend
npm run build
```

This generates production-ready static assets in `frontend/dist/`.

### Troubleshooting

- **CORS Issues (`Access to fetch at ... blocked by CORS policy`)**:
  FastAPI has CORS middleware configured in `app/main.py` (`ALLOWED_ORIGINS`) allowing the local Vite ports (5173, 4173, 3000) on `localhost` and `127.0.0.1`, and the deployed frontend `https://ticket-api-kr58.onrender.com`. `ALLOWED_ORIGIN_REGEX` also allows those ports on any private network address (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`), so Vite's "Network" URL works even when your IP changes. Ensure your browser URL matches one of the allowed origins.
- **Triage returns "not configured" (HTTP 503)**:
  `GEMINI_API_KEY` is missing. Add it to the project-root `.env` (or the Render backend's environment) and restart the backend.
- **Backend Connection Failure (`Unable to connect to the backend server`)**:
  Verify the backend terminal is running `python -m uvicorn app.main:app --reload` on port 8000 and `$env:TICKETS_DATA_PATH` is set.
- **Incorrect API URL**:
  Check `frontend/.env` and verify `VITE_API_BASE_URL` points to your backend instance (e.g. `http://127.0.0.1:8000`). Restart `npm run dev` after changing `.env`.
- **Port Conflict**:
  If port 8000 or 5173 is already in use, stop conflicting processes or specify an alternate port. Remember to update `VITE_API_BASE_URL` if you change the backend port.

---

## Deployment (Render)

| Service | Render type | URL |
|---|---|---|
| Backend (FastAPI) | Web service | https://task4-ticket-triage-api.onrender.com |
| Frontend (React) | Static site | https://ticket-api-kr58.onrender.com |

The settings below are the typical values for this project; check them against the Render dashboard.

Backend:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment: set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`) in the service's Environment settings.

Frontend:

- Root directory: `frontend`
- Build command: `npm install && npm run build`
- Publish directory: `dist`
- Environment: `VITE_API_BASE_URL=https://task4-ticket-triage-api.onrender.com`. This value is compiled in at build time, so redeploy after changing it.

If the frontend URL changes, add the new origin to `ALLOWED_ORIGINS` in `app/main.py`.

---

## Stop the Servers

- To stop the backend: Press `Ctrl+C` in the backend terminal.
- To stop the frontend: Press `Ctrl+C` in the frontend terminal.
