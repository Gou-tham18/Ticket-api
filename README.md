# ticket-api

A support-ticket helper with a FastAPI backend and a React + TypeScript frontend. It triages new tickets with AI and suggests help articles (**AI Ticket Triage**). It also tracks escalations from the team's Help Desk export and approval spreadsheet (**Escalation Tracker**). And it emails the urgent tickets that need a decision to a manager, who answers with Approve/Reject buttons in the email (**Escalation Dashboard**). Data comes from CSV files in `data/`; the source files are never modified.

You need Python 3.10 or newer, Node.js 20 or newer, and Git. Nothing needs to be configured before the first run.

## Quick start

Use two terminals, both starting in the project folder.

**Windows PowerShell**

```powershell
# Terminal 1: backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

```powershell
# Terminal 2: frontend
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

**macOS / Linux**

```bash
# Terminal 1: backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

```bash
# Terminal 2: frontend
cd frontend
cp .env.example .env
npm install
npm run dev
```

If PowerShell refuses to run `Activate.ps1`, see [Troubleshooting](#troubleshooting).

## Check it works

1. Open http://127.0.0.1:8000/health. You should see `"status": "ok"`. `triage_ai` and `approval_email` say `not_configured` until you add those settings, which is expected.
2. Open http://localhost:5173/#/dashboard. The Escalation Dashboard should show 120 tickets, 79 of them open.

The interactive API documentation is at http://127.0.0.1:8000/docs.

## Run tests

Backend, from the project folder with the virtual environment active:

```
python -m pytest -q
```

This runs 311 tests: `test_api.py` 10, `test_triage.py` 14, `test_retrieval.py` 4, `test_escalations.py` 69, `test_email_approval.py` 61, `test_production.py` 64, and `test_approval_buttons.py` 89. Gemini and the mail server are replaced with fakes and the clock is fixed, so no keys, network, or `.env` are needed. Tests work on temporary copies and never change `data/`.

Frontend, from `frontend/`:

```
npm test
npm run build
```

`npm test` runs 56 tests: `App.test.tsx` 10, `EscalationTracker.test.tsx` 13, `EscalationDashboard.test.tsx` 27, and `ErrorHandling.test.tsx` 6. `npm run build` type-checks and writes the production bundle to `frontend/dist/`.

## Configuration

Nothing is required: the app starts and the escalation pages work without a `.env` file. Add settings only for the features that need them.

**Backend:** put settings in `.env` in the project folder. Start from the template with `Copy-Item .env.example .env` (Windows) or `cp .env.example .env` (macOS/Linux). Restart the backend after changing `.env`; `--reload` does not watch it.

| Variable | Needed for | Default |
|---|---|---|
| `GEMINI_API_KEY` | AI triage only. Get a key at https://aistudio.google.com/apikey | none: `/triage` returns `503` |
| `GEMINI_MODEL` | AI triage | `gemini-3.8-flash` |
| `APPROVAL_USER_NAME`, `APPROVAL_USER_EMAIL` | Sending approval emails: the team member who sends | none |
| `APPROVAL_MANAGER_NAME`, `APPROVAL_MANAGER_EMAIL` | Sending approval emails: the manager who decides | none |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS` | Sending approval emails | port `587`, TLS `true` |
| `PUBLIC_BASE_URL` | Sending approval emails: where the manager's browser reaches this backend, for example `https://your-name.ngrok-free.dev`. Must start with `https://` (`http://` for local testing only); a trailing `/` is removed | none: sending returns `503` |
| `APPROVAL_LINK_SECRET` | Sending approval emails: signs the Approve/Reject links. At least 32 characters. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` | none: sending returns `503` |
| `APPROVAL_LINK_DAYS` | How long Approve/Reject links work (whole days, 1 to 30) | `7` |
| `APPROVAL_REMINDER_DAYS` | Days without a decision before a ticket is ready to send again as a Reminder (whole days, 1 to 30) | `1` |
| `APPROVAL_EMAIL_LOG_PATH` | Where each sent approval email is logged (`ticket_id,sent_at,kind`) | `data/approval_emails.csv` |
| `TICKETS_DATA_PATH` | `/tickets` and `/summary` | `data/helpdesk_export_sample.csv` |
| `HELPDESK_EXPORT_PATH` | Escalation pages | `data/helpdesk_export_sample.csv` |
| `ESCALATION_TRACKER_PATH` | Escalation pages | `data/escalation_tracker_sample.csv` |
| `DECISION_LOG_PATH`, `APPROVAL_REQUEST_LOG_PATH` | Where decisions and requests are saved | `data/decision_log.csv`, `data/approval_requests.csv` |
| `MANAGERS` | Comma-separated approvers for the per-ticket form | the approvers named in the tracker |

The three log files are created on first use and are not in Git. The Help Desk export and the tracker are only read. Invalid day settings fall back to the default with a warning in the backend log; an invalid `PUBLIC_BASE_URL` or a too-short secret is ignored with a warning (the value is never logged).

**Frontend:** copy `frontend/.env.example` to `frontend/.env`. Keep `VITE_API_BASE_URL=http://127.0.0.1:8000` for local use. The value is read when `npm run dev` starts, so restart it after a change. Only `VITE_API_BASE_URL` belongs here. Email and SMTP settings go in the backend `.env`, never in `frontend/.env`.

### Sending email with Gmail

The password belongs to the **sending** account (`APPROVAL_USER_EMAIL`), never the manager's.

1. Sign in to the sending Google account and turn on 2-Step Verification (Google Account → Security).
2. Open https://myaccount.google.com/apppasswords, create an App Password (any name, for example "ticket-api"), and copy the 16 characters.
3. Set these in the backend `.env`, then restart the backend:

```
APPROVAL_USER_NAME=Riya
APPROVAL_USER_EMAIL=riya.sender@gmail.com
APPROVAL_MANAGER_NAME=Mara
APPROVAL_MANAGER_EMAIL=mara@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=riya.sender@gmail.com
SMTP_PASSWORD=the16charapppassword
SMTP_USE_TLS=true
```

To test without sending real email, run a local server that prints messages instead (`pip install aiosmtpd`, then `python -m aiosmtpd -n -l localhost:1025`) and set `SMTP_HOST=localhost`, `SMTP_PORT=1025`, `SMTP_USE_TLS=false`, with no username or password.

### Approve/Reject buttons: run with ngrok

The buttons in the email open a page served by this backend, so the manager's phone or laptop must be able to reach it. On a developer laptop, ngrok's free dev domain gives it a public `https://` address.

1. Create a free account at ngrok.com, install ngrok, and run `ngrok config add-authtoken <token>` once.
2. Copy your free dev domain from the ngrok dashboard (Domains).
3. Start the backend: `python -m uvicorn app.main:app --reload --port 8000`.
4. In another terminal, run `ngrok http 8000 --url https://<your-dev-domain>`.
5. Set `PUBLIC_BASE_URL=https://<your-dev-domain>` and `APPROVAL_LINK_SECRET` in `.env`, then restart the backend.
6. Check `https://<your-dev-domain>/health` (or `/approvals/config`) opens on your phone.

Notes:

- On ngrok's free plan, the first click shows an ngrok notice page. Click **Visit Site**; it won't appear again for 7 days.
- The laptop, backend and ngrok must be running when the manager clicks. If they are not, the link does not open and nothing is recorded; the next reminder brings fresh links.
- Changing `APPROVAL_LINK_SECRET` makes every link already sent invalid.

### Security

Never commit, zip, or share `.env` or `frontend/.env`. Git already ignores them; check before zipping the folder by hand. If a `.env` was shared, create a new Gmail App Password, a new Gemini key and a new `APPROVAL_LINK_SECRET`, and delete the old ones. The API never returns these values, and `/health` reports only `configured` or `not_configured`.

## Features

### AI Ticket Triage (`http://localhost:5173/`)

Enter a ticket subject and description. The backend sets the category with keyword rules, finds matching help articles in `kb/`, and asks Gemini for the priority and a suggested reply. Gemini can only set "urgent" for non-shipping tickets. If Gemini is temporarily unavailable, a template reply is used. A missing or rejected key returns a clear `503`.

### Escalation Tracker (`http://localhost:5173/#/escalations`)

Shows the urgent open tickets and where each is in manager approval: not requested, awaiting decision, accepted, or rejected. You can filter by category and status. **Request Approval** records a request, and **Accept** / **Reject** record a decision. Both are saved to the log files; no email is sent from this page.

### Escalation Dashboard and the email round trip (`http://localhost:5173/#/dashboard`)

The dashboard shows counts of open tickets needing attention (urgent & open, escalated label, refund over 200), the tickets ready to send, the tickets waiting for the manager, the manager's recorded decisions, and every ticket from the export (open tickets first) with its approval state. Customer email addresses never appear. The email settings and the button settings above are needed to send. The page reloads itself every minute while it is visible, and **Refresh** reloads it now.

The round trip:

1. Under **Escalations awaiting manager approval**, **Ready to send** lists each ticket as **New** or **Reminder · waiting N days**. **Preview email** shows exactly what will be sent.
2. Click **Send to manager for approval**. One email goes to the manager, with an **Approve** and a **Reject** button for each ticket.
3. The manager clicks **Approve** or **Reject**. A page opens on this backend showing the ticket and asking them to confirm. Opening the page records nothing.
4. The manager clicks **Confirm**. The decision is recorded with the manager as the decider and appears under **Manager decisions** on the dashboard (within a minute, or at once with **Refresh**).
5. A short result email ("TCK-5007 approved by Mara") goes to you, with the manager in Cc.

If the manager does not click: the ticket moves to **Waiting for the manager's reply**. After 1 day (`APPROVAL_REMINDER_DAYS`) it comes back to **Ready to send** as a Reminder, with fresh links, and this repeats until the manager decides. Accepted and rejected tickets never come back, and a ticket can only be decided once.

Replies to the email are not recorded. The old paste-reply endpoints (`/approvals/reply/preview` and `/approvals/reply/record`) still work for compatibility, but the dashboard no longer uses them. The rules are in [docs/TASK5_ESCALATIONS.md](docs/TASK5_ESCALATIONS.md).

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Status of data files, logs, and settings. Always `200` while running |
| GET | `/tickets?page=1&size=10` | Tickets from `TICKETS_DATA_PATH`, paginated (size 1 to 100) |
| GET | `/tickets/{ticket_id}` | One ticket |
| GET | `/summary` | Totals by category and average resolution hours (`null` if the file has no `resolved_at`) |
| POST | `/triage` | `{"subject", "text"}` → category, priority, suggested reply, article IDs |
| GET | `/helpdesk/tickets` | Help Desk tickets with escalation details. Filters: `status`, `category`, `priority`, `open_only`, `escalated` |
| GET | `/helpdesk/tickets/{ticket_id}` | One Help Desk ticket |
| GET | `/escalations` | Escalated tickets. Filters: `state`, `category`, `open_only` |
| GET | `/escalations/data-issues` | Problems found in the CSV files (duplicates, bad values, short rows) |
| POST | `/escalations/{ticket_id}/decision` | `{"decision": "Accept" or "Reject", "decided_by"}` |
| GET | `/approvals/urgent-open` | Urgent open tickets by approval stage. Filters: `category`, `status` |
| POST | `/approvals/{ticket_id}/request` | `{"requested_by", "approver"}` |
| GET | `/dashboard` | Dashboard data: tickets (open first), attention counts, tickets ready to send, waiting tickets, recent decisions |
| GET | `/approvals/config` | Sender and manager names, whether email and buttons are configured, and the names of missing button settings (no addresses or values) |
| GET | `/approvals/batch/preview` | Subject, text body and HTML body of the next approval email |
| POST | `/approvals/batch/send` | Send the approval email |
| GET | `/approvals/respond?token=…` | HTML confirmation page opened by an email button. Records nothing |
| POST | `/approvals/respond?token=…` | Confirm: records the decision as the manager and sends the result email (HTML page) |
| POST | `/approvals/reply/preview` | `{"reply_text"}` → decisions understood. Saves nothing. Kept for compatibility |
| POST | `/approvals/reply/record` | `{"reply_text"}` → records the clear decisions. Kept for compatibility |

## Errors and health check

Every error response has a `detail` message meant to be shown to a person. Error messages never include keys, passwords, email addresses, full file paths, or stack traces.

| Situation | Response |
|---|---|
| Invalid input | `422`. `detail` is FastAPI's list of `{loc, msg}`, and each `msg` is a plain sentence such as "subject is required." or "decision must be Accept or Reject.". `message` repeats the first problem |
| Ticket ID in the wrong format on Help Desk and approval routes | `422` "Ticket IDs look like TCK-5007." |
| Ticket CSV missing or unreadable | `503` on `/tickets` and `/summary` only. The server still starts, and the data loads once the file is back |
| Help Desk export missing, unreadable, or without a `ticket_id` column | `503` on the escalation endpoints, naming the file and setting |
| Tracker missing | Treated as empty and listed in `/escalations/data-issues` |
| Bad values in a CSV (non-numeric refund, unreadable date, short row) | Treated as blank and listed in `/escalations/data-issues` |
| Log file locked (for example, open in Excel) | `503` "Could not save to decision_log.csv. Close it if it is open in Excel and try again." Nothing is saved |
| AI or email not configured | `503` naming the missing setting |
| Gemini or the mail server fails | `502` |
| Anything unexpected | `500` with an `error_id`. The full error is in the backend log under the same ID |

`GET /health` is fast and local: it never calls Gemini, sends email, or uses the network. It returns `200` whenever the server is running, so it can be a hosting health check. Problems are reported in the body:

```json
{
  "status": "ok",
  "time": "2026-10-30T09:15:00",
  "checks": {
    "ticket_data": "ok",
    "helpdesk_export": "ok",
    "escalation_tracker": "ok",
    "logs_writable": "ok",
    "triage_ai": "configured",
    "approval_email": "configured"
  }
}
```

File checks are `ok`, `missing`, or `unreadable`. `logs_writable` is `ok` or `not_writable`. `status` is `degraded` if any of those four is not `ok`. Missing AI or email settings show as `not_configured`, but they don't make the status degraded.

## Deployment

The project is deployed on Render:

| Service | Render type | URL |
|---|---|---|
| Backend (FastAPI) | Web service | https://task4-ticket-triage-api.onrender.com |
| Frontend (React) | Static site | https://ticket-api-kr58.onrender.com |

Backend settings:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Environment: `GEMINI_API_KEY`, and the `APPROVAL_*` and `SMTP_*` settings if emails should be sent. Set them in the service's Environment settings, not in a committed file.

Frontend settings:

- Root directory: `frontend`
- Build command: `npm install && npm run build`
- Publish directory: `dist`
- Environment: `VITE_API_BASE_URL=https://task4-ticket-triage-api.onrender.com`. It is compiled in at build time, so redeploy after changing it.

If the frontend URL changes, add it to `ALLOWED_ORIGINS` in `app/main.py`. On Render's free tier the disk is reset on each deploy, so the decision and request logs written there are lost.

## Troubleshooting

- **PowerShell won't run `Activate.ps1`** ("running scripts is disabled"): run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. Or skip activation and use `.\.venv\Scripts\python -m uvicorn app.main:app --reload`.
- **"Unable to connect to the backend server"**: check the backend terminal is running and http://127.0.0.1:8000/health opens. Check `frontend/.env` has `VITE_API_BASE_URL=http://127.0.0.1:8000`, and restart `npm run dev` after changing it.
- **The pages show old data or are missing features**: check the backend was started from this project folder and not an older copy. Stop any other `uvicorn` on port 8000.
- **Blocked by CORS policy**: open the frontend at `http://localhost:5173` or `http://127.0.0.1:5173`. Private network addresses (`192.168.x.x`, `10.x.x.x`) on ports 5173, 4173, and 3000 are also allowed.
- **Dashboard says the user and manager are not configured**: the `APPROVAL_*` settings must be in the backend `.env` in the project folder, not in `frontend/.env`. Restart the backend afterwards.
- **"Email approval is not configured: PUBLIC_BASE_URL is not set" (503)** (or `APPROVAL_LINK_SECRET`): add it to the backend `.env` and restart. Check the backend log for a warning if it is set but ignored (wrong prefix, or a secret under 32 characters).
- **The manager's button says "This link is not valid"**: the secret changed since the email was sent, or the link was cut. Send again when the reminder is due.
- **"Nothing to send yet"** (409): every ticket was emailed recently; it comes back as a Reminder when the date shown is reached.
- **"Approval email could not be sent" (502)**: the backend terminal shows the reason. For Gmail, check that `SMTP_USERNAME` is the sending address and `SMTP_PASSWORD` is an App Password, not the normal password.
- **"Could not save to … Close it if it is open in Excel"**: close the log file in Excel and try again.
- **Port 8000 or 5173 already in use**: stop the other process, or start on another port (`--port 8001`) and update `VITE_API_BASE_URL` to match.
- **`pytest` fails in `test_api.py`**: a `TICKETS_DATA_PATH` left set in the terminal overrides the test data. Run `Remove-Item Env:TICKETS_DATA_PATH` (PowerShell) or `unset TICKETS_DATA_PATH`.
- **`npm test` fails with an engine error**: the test runner needs Node.js 20 or newer. Check with `node --version`.
