"""Ticket Summary CLI.

Reads a CSV file containing support tickets, counts tickets by category,
and calculates the average resolution time in hours for resolved tickets.
"""

import csv
import sys
from datetime import datetime


def parse_timestamp(timestamp_str):
    """
    Parse a timestamp string into a datetime object.

    Supports two formats found in the dataset:
    - Primary format: 'YYYY-MM-DD HH:MM' (e.g., '2026-02-02 08:48')
    - Alternative format: 'DD/MM/YYYY HH:MM' (e.g., '02/03/2026 10:02')

    Returns:
        datetime: The parsed datetime object, or None if timestamp_str is empty.

    Raises:
        ValueError: If timestamp_str is not empty but cannot be parsed.
    """
    # Remove leading and trailing whitespace
    clean_ts = timestamp_str.strip()

    # An empty timestamp means the ticket does not have this timestamp (e.g., unresolved)
    if not clean_ts:
        return None

    # Try supported formats
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(clean_ts, fmt)
        except ValueError:
            continue

    # If none of the formats match, raise ValueError
    raise ValueError(f"Invalid timestamp format: '{timestamp_str}'")


def process_tickets_file(file_path):
    """
    Reads a tickets CSV file and computes category counts and average resolution time.

    Handles edge cases:
    - UTF-8 BOM encoding.
    - Blank lines (skipped).
    - Malformed rows with extra or missing fields (reported and skipped).
    - Invalid timestamps (reported and skipped).
    - Unresolved tickets (excluded from average resolution time).

    Returns:
        tuple: (category_counts, average_resolution_hours)
    """
    category_counts = {}
    resolution_durations = []

    # Using 'utf-8-sig' automatically handles UTF-8 BOM if present
    try:
        with open(file_path, mode="r", encoding="utf-8-sig") as csv_file:
            reader = csv.reader(csv_file)

            # Read the header row
            header = next(reader, None)

            # Handle empty CSV files
            if header is None:
                print(f"Notice: '{file_path}' is empty.")
                return category_counts, 0.0

            # Strip whitespace from header names to ensure clean matching
            clean_header = [col.strip() for col in header]

            # Verify required columns exist in the header
            required_columns = ["category", "created_at"]
            for col in required_columns:
                if col not in clean_header:
                    print(f"Error: Required column '{col}' is missing from CSV header.")
                    return category_counts, 0.0

            # The Help Desk export has no resolved_at column. Tickets are
            # still counted, but no average resolution time can be given.
            has_resolved = "resolved_at" in clean_header

            # Find the index of each column we care about
            category_idx = clean_header.index("category")
            created_idx = clean_header.index("created_at")
            resolved_idx = clean_header.index("resolved_at") if has_resolved else None
            expected_field_count = len(clean_header)

            # Iterate through rows starting from line 2 (line 1 is the header)
            for line_number, row in enumerate(reader, start=2):
                # 1. Skip completely blank lines
                if not row or not any(field.strip() for field in row):
                    continue

                # 2. Check for malformed rows (extra or missing fields)
                if len(row) != expected_field_count:
                    print(
                        f"Warning: Skipping malformed row at line {line_number} "
                        f"(expected {expected_field_count} fields, found {len(row)}): {row}"
                    )
                    continue

                category_raw = row[category_idx]
                created_raw = row[created_idx]
                resolved_raw = row[resolved_idx] if has_resolved else ""

                # 3. Parse timestamps and handle invalid ones
                try:
                    created_dt = parse_timestamp(created_raw)
                    resolved_dt = parse_timestamp(resolved_raw)
                except ValueError as error:
                    print(
                        f"Warning: Skipping row at line {line_number} due to invalid timestamp: {error}"
                    )
                    continue

                # 4. Count tickets by category
                category = category_raw.strip()
                if not category:
                    category = "Unknown"

                category_counts[category] = category_counts.get(category, 0) + 1

                # 5. Calculate resolution duration (only for resolved tickets with valid created_at)
                if created_dt is not None and resolved_dt is not None:
                    duration_seconds = (resolved_dt - created_dt).total_seconds()
                    duration_hours = duration_seconds / 3600.0
                    resolution_durations.append(duration_hours)

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        return category_counts, 0.0

    # Calculate average resolution time in hours
    if not has_resolved:
        average_hours = None
    elif resolution_durations:
        average_hours = round(sum(resolution_durations) / len(resolution_durations), 2)
    else:
        average_hours = 0.0

    return category_counts, average_hours


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python ticket_summary.py <csv_filename>")
        sys.exit(1)

    csv_path = sys.argv[1]
    category_counts, avg_hours = process_tickets_file(csv_path)

    # Display the summary report
    print("\n" + "=" * 40)
    print("         TICKET SUMMARY REPORT")
    print("=" * 40)

    print("\nTicket Counts by Category:")
    if category_counts:
        for category, count in sorted(category_counts.items()):
            print(f"  - {category}: {count}")
    else:
        print("  (No valid tickets found)")

    if avg_hours is None:
        print("\nAverage Resolution Time: not available (no resolved_at column)")
    else:
        print(f"\nAverage Resolution Time: {avg_hours:.2f} hours")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()
