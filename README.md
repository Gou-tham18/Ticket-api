# ticket-api

A small FastAPI service that provides support ticket data, ticket summaries, and a simple web page.

## Requirements

- Python 3.8 or newer
- pip

## Project structure

```text
task3/
├── app/
│   ├── main.py
│   └── ticket_summary.py
├── data/
│   └── tickets_sample.csv
├── docs/
│   └── ROOT_CAUSE.md
├── tests/
│   └── test_api.py
├── web/
│   └── index.html
├── requirements.txt
└── README.md
```

## Setup

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

## Run the application

Set the path to the sample CSV:

```powershell
$env:TICKETS_DATA_PATH = "$PWD\data\tickets_sample.csv"
```

Start the API:

```powershell
python -m uvicorn app.main:app --reload
```

Open these URLs:

- Web page: http://127.0.0.1:8000/
- Interactive API documentation: http://127.0.0.1:8000/docs

Keep the terminal running while using the application.

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/tickets?page=1&size=10` | List tickets with pagination |
| GET | `/tickets/{ticket_id}` | Retrieve a ticket by ID |
| GET | `/summary` | Get ticket totals, category counts, and average resolution hours |

Pagination starts at page 1. Page size must be between 1 and 100.

The summary uses the Day 1 `process_tickets_file()` function from `app/ticket_summary.py`.

Average resolution time includes only tickets with valid creation and resolution timestamps.

## Run the tests

Activate `.venv`, set `TICKETS_DATA_PATH` as shown above, and run:

```powershell
python -m pytest -v
```

The tests validate summary calculations against the sample CSV, pagination, missing-ticket behavior, and integration with the Day 1 summary module.

## Stop the server

Press `Ctrl+C` in the terminal running Uvicorn.