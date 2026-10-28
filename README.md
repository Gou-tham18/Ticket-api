# ticket-api

A small FastAPI service that provides support ticket data, ticket summaries, an AI ticket triage service, and a modern React + TypeScript frontend.

## Requirements

- Python 3.8 or newer
- pip
- Node.js 18+ (tested on Node.js 24)
- npm 9+ (tested on npm 11)

## Project structure

```text
task3/
├── app/
│   ├── main.py
│   ├── retrieval.py
│   ├── ticket_summary.py
│   └── triage_service.py
├── data/
│   └── tickets_sample.csv
├── docs/
│   └── ROOT_CAUSE.md
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LoadingIndicator.tsx
│   │   │   ├── TicketForm.tsx
│   │   │   └── TriageResult.tsx
│   │   ├── services/
│   │   │   └── triageApi.ts
│   │   ├── types/
│   │   │   └── triage.ts
│   │   ├── App.css
│   │   ├── App.test.tsx
│   │   ├── App.tsx
│   │   ├── index.css
│   │   ├── main.tsx
│   │   ├── setupTests.ts
│   │   └── vite-env.d.ts
│   ├── .env.example
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   └── vite.config.ts
├── kb/
├── tests/
│   ├── test_api.py
│   ├── test_retrieval.py
│   └── test_triage.py
├── web/
│   └── index.html
├── pytest.ini
├── requirements.txt
└── README.md
```

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

Set the path to the sample CSV:

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

All 15 tests validate summary calculations, pagination, missing-ticket behavior, retrieval logic, and ticket triage handling.

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
- By default, `VITE_API_BASE_URL` is set to `http://127.0.0.1:8000`.
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

### Run Frontend Tests

The frontend suite uses Vitest and React Testing Library to verify full application behavior without needing a running backend server or external API keys:

```powershell
cd frontend
npm test
```

This runs 10 automated unit and integration tests covering:
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
  FastAPI has CORS middleware configured in `app/main.py` allowing `http://localhost:5173` and `http://127.0.0.1:5173`. Ensure your browser URL matches one of the allowed origins.
- **Backend Connection Failure (`Unable to connect to the backend server`)**:
  Verify the backend terminal is running `python -m uvicorn app.main:app --reload` on port 8000 and `$env:TICKETS_DATA_PATH` is set.
- **Incorrect API URL**:
  Check `frontend/.env` and verify `VITE_API_BASE_URL` points to your backend instance (e.g. `http://127.0.0.1:8000`). Restart `npm run dev` after changing `.env`.
- **Port Conflict**:
  If port 8000 or 5173 is already in use, stop conflicting processes or specify an alternate port. Remember to update `VITE_API_BASE_URL` if you change the backend port.

---

## Stop the Servers

- To stop the backend: Press `Ctrl+C` in the backend terminal.
- To stop the frontend: Press `Ctrl+C` in the frontend terminal.
