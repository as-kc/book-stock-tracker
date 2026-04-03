from __future__ import annotations

import sqlite3

import pytest

from book_stock_tracker.services import StockTrackerService, ValidationError
from book_stock_tracker.storage import Database


def test_schema_initialization_creates_tables(db_path):
    database = Database(db_path)
    database.initialize()

    table_names = {
        row["name"]
        for row in database.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert {"items", "reports", "report_lines"}.issubset(table_names)
    database.close()


def test_item_names_are_globally_unique(service: StockTrackerService):
    first_item = service.upsert_item_by_name("The Hobbit")
    second_item = service.upsert_item_by_name("the hobbit")

    all_items = service.list_items()

    assert first_item.id == second_item.id
    assert len(all_items) == 1
    assert all_items[0].name == "The Hobbit"


def test_duplicate_lines_for_same_item_within_report_are_allowed(service: StockTrackerService):
    report = service.create_report("Morning delivery", "2026-04-03")

    first_line = service.create_report_line(report.id, "Dune", 5, 0)
    second_line = service.create_report_line(report.id, "Dune", 2, 1)

    lines = service.list_report_lines(report.id)

    assert [line.id for line in lines] == [first_line.id, second_line.id]
    assert [line.item_name for line in lines] == ["Dune", "Dune"]


def test_stock_aggregation_across_reports_is_correct(service: StockTrackerService):
    first_report = service.create_report("Inbound", "2026-04-03")
    second_report = service.create_report("Sales", "2026-04-04")

    service.create_report_line(first_report.id, "Neuromancer", 10, 0)
    service.create_report_line(second_report.id, "Neuromancer", 0, 4)
    service.create_report_line(second_report.id, "Snow Crash", 3, 0)

    summary = service.get_stock_summary()

    neuromancer = next(row for row in summary if row.item_name == "Neuromancer")
    snow_crash = next(row for row in summary if row.item_name == "Snow Crash")
    assert (neuromancer.total_in, neuromancer.total_out, neuromancer.current_stock) == (10, 4, 6)
    assert (snow_crash.total_in, snow_crash.total_out, snow_crash.current_stock) == (3, 0, 3)


def test_negative_stock_is_allowed_and_reported(service: StockTrackerService):
    report = service.create_report("Oversold", "2026-04-03")

    service.create_report_line(report.id, "Foundation", 0, 2)

    stock_row = next(row for row in service.get_stock_summary() if row.item_name == "Foundation")
    assert stock_row.current_stock == -2


def test_report_updates_and_line_deletes_change_totals(service: StockTrackerService):
    report = service.create_report("Original", "2026-04-03")
    first_line = service.create_report_line(report.id, "Silo", 5, 0)
    second_line = service.create_report_line(report.id, "Silo", 0, 1)

    updated_report = service.update_report(report.id, "Updated", "2026-04-05")
    service.delete_report_line(second_line.id)

    fetched_report = service.get_report(report.id)
    stock_row = next(row for row in service.get_stock_summary() if row.item_name == "Silo")
    remaining_lines = service.list_report_lines(report.id)

    assert updated_report.title == "Updated"
    assert fetched_report is not None
    assert fetched_report.report_date == "2026-04-05"
    assert stock_row.current_stock == 5
    assert [line.id for line in remaining_lines] == [first_line.id]


@pytest.mark.parametrize(
    ("title", "report_date", "item_name", "in_qty", "out_qty", "expected_message"),
    [
        ("", "2026-04-03", "Book", 1, 0, "Report title is required."),
        ("Valid", "03-04-2026", "Book", 1, 0, "Report date must use YYYY-MM-DD."),
        ("Valid", "2026-04-03", "", 1, 0, "Item name is required."),
        ("Valid", "2026-04-03", "Book", -1, 0, "IN quantity cannot be negative."),
        ("Valid", "2026-04-03", "Book", 0, 0, "At least one of IN or OUT must be greater than zero."),
    ],
)
def test_invalid_input_is_rejected(
    service: StockTrackerService,
    title: str,
    report_date: str,
    item_name: str,
    in_qty: int,
    out_qty: int,
    expected_message: str,
):
    with pytest.raises(ValidationError) as exc_info:
        report = service.create_report(title, report_date)
        service.create_report_line(report.id, item_name, in_qty, out_qty)

    assert str(exc_info.value) == expected_message


def test_invalid_report_date_rejected_before_line_creation(service: StockTrackerService):
    with pytest.raises(ValidationError, match="Report date must use YYYY-MM-DD."):
        service.create_report("Bad date", "2026/04/03")


def test_database_constraints_guard_against_invalid_rows(db_path):
    database = Database(db_path)
    database.initialize()
    connection = database.connection
    connection.execute("INSERT INTO reports (title, report_date) VALUES (?, ?)", ("Valid", "2026-04-03"))
    connection.execute("INSERT INTO items (name) VALUES (?)", ("Book",))

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO report_lines (report_id, item_id, in_qty, out_qty, position)
            VALUES (1, 1, 0, 0, 1)
            """
        )

    database.close()
