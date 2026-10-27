# Root Cause Analysis

## 1. Incorrect ticket pagination

**Problem:** The first ticket was missing from page 1, and subsequent pages also started one record too late.

**How it was found:** A regression test compared the first ticket on each page with the corresponding row in `tickets_sample.csv`. The original implementation returned `TCK-1002` instead of `TCK-1001`.

**Root cause:** The starting index included an unnecessary `+ 1`. Python list indices start at zero.

**Fix:** Changed the calculation to `start = (page - 1) * size`.

**Verification:** The first-page and second-page regression tests pass.

## 2. Incorrect average resolution time

**Problem:** The API returned 17.69 hours instead of the sample CSV's expected 25.27 hours.

**How it was found:** A regression test calculated the average directly from rows with a resolution timestamp.

**Root cause:** The calculation divided the total resolution hours by all tickets, including unresolved tickets.

**Fix:** The calculation was updated to average only resolved tickets. The summary logic was subsequently connected to the Day 1 `process_tickets_file()` function.

**Verification:** The CSV-based average test and Day 1 module integration tests pass.

## 3. Incorrect month displayed on the web page

**Problem:** The displayed month was one less than the actual month.

**How it was found:** Inspection of `web/index.html` showed that `showDate()` used JavaScript's `getMonth()` directly.

**Root cause:** JavaScript numbers months from 0 to 11.

**Fix:** Added 1 to the returned month.

**Verification:** The updated page must be checked in the browser to confirm the displayed dates are correct.

## 4. Incorrect startup command and missing environment configuration

**Problem:** The README's original command, `uvicorn main:app --reload`, failed to import the application. The application also requires `TICKETS_DATA_PATH`.

**How it was found:** Running the original command produced an ASGI import error. Inspecting `app/main.py` revealed the required environment variable and the actual module location.

**Root cause:** The documented module path did not match the project's `app/main.py` structure, and the required CSV path was not configured.

**Fix:** Use `python -m uvicorn app.main:app --reload` after setting `TICKETS_DATA_PATH`.

**Verification:** The application started successfully with the corrected command and environment variable.

## 5. Test environment dependency mismatch

**Problem:** Test collection failed because the Python environment running pytest did not have the required HTTP client dependency.

**How it was found:** The traceback reported that `httpx2` was missing. A later run also showed that global Python was being used instead of the project virtual environment.

**Root cause:** Dependencies were installed in one Python environment while tests were run from another.

**Fix:** Activated `.venv`, installed the missing dependencies, and ran tests using `python -m pytest`.

**Verification:** Seven tests passed in the project virtual environment.

## 6. Day 1 summary integration

**Problem:** The original API implemented summary calculations separately from the Day 1 ticket summary code.

**How it was found:** Reviewing the Task 3 requirements and the original `/summary` implementation showed that the endpoint did not call the Day 1 module.

**Fix:** Imported `process_tickets_file()` from `app/ticket_summary.py` and updated `/summary` to use its category counts and average resolution time.

**Verification:** Integration tests verify that the endpoint uses the module and that its results match the sample CSV.

## Remaining verification

- Verify the corrected web page in a browser.
- Run the tests from a clean environment using the documented setup.
- Verify the final GitHub branch and pull request.
