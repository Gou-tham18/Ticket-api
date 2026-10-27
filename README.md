# ticket-api

A small service that serves support ticket data and a summary, plus a simple web page.

Requires Python 3.8 or newer.

## Run

```
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open http://localhost:8000/docs for the API, or http://localhost:8000/ for the web page.

## Test

```
pytest
```
