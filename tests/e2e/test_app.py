from __future__ import annotations

from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import DataTable, OptionList

from book_stock_tracker.app import (
    BookStockTrackerApp,
    CompactLineInput,
    CompactReportField,
    ReportFieldInput,
    ReportLineRow,
    ReportLinesEditor,
)
from book_stock_tracker.services import StockTrackerService
from book_stock_tracker.storage import Database, StockTrackerRepository


async def type_text(pilot, text: str) -> None:
    if text:
        await pilot.press(*list(text))


def table_rows(table: DataTable) -> list[list[str]]:
    return [
        [str(cell) for cell in table.get_row_at(index)]
        for index in range(table.row_count)
    ]


def inline_rows(app: BookStockTrackerApp) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in app.query(ReportLineRow):
        rows.append(
            [
                app.query_one(f"#cell-{row.row_key}-name").value,
                app.query_one(f"#cell-{row.row_key}-in_qty").value,
                app.query_one(f"#cell-{row.row_key}-out_qty").value,
            ]
        )
    return rows


async def create_report_with_inline_line(
    app: BookStockTrackerApp,
    pilot,
    *,
    item_query: str,
    in_qty: str = "",
    out_qty: str = "",
    choose_existing: bool = False,
) -> None:
    await pilot.press("n")
    await pilot.pause()
    await pilot.press("a")
    await pilot.pause()
    await type_text(pilot, item_query)
    await pilot.pause()
    if choose_existing:
        await pilot.press("down", "up")
    await pilot.press("enter")
    await pilot.pause()
    if in_qty:
        await type_text(pilot, in_qty)
    await pilot.press("enter")
    await pilot.pause()
    if out_qty:
        await type_text(pilot, out_qty)
    await pilot.press("enter")
    await pilot.pause()
    assert len(inline_rows(app)) >= 1


def seed_existing_item(db_path: Path, item_name: str) -> None:
    database = Database(db_path)
    repository = StockTrackerRepository(database)
    service = StockTrackerService(repository)
    service.initialize()
    report = service.create_report("Seed report", "2026-04-03")
    service.create_report_line(report.id, item_name, 1, 0)
    database.close()


@pytest.mark.asyncio
async def test_create_new_item_and_show_it_in_stock(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="alpha", in_qty="10")
        await pilot.press("s")
        await pilot.pause()

        stock_rows = table_rows(app.query_one("#stock-table", DataTable))

    assert stock_rows == [["alpha", "10", "0", "10"]]


@pytest.mark.asyncio
async def test_existing_item_can_be_selected_in_new_report_and_stock_is_aggregated(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="alpha", in_qty="10")
        await pilot.press("r")
        await pilot.pause()
        await create_report_with_inline_line(
            app,
            pilot,
            item_query="alp",
            out_qty="3",
            choose_existing=True,
        )
        await pilot.press("s")
        await pilot.pause()

        stock_rows = table_rows(app.query_one("#stock-table", DataTable))

    assert stock_rows == [["alpha", "10", "3", "7"]]


@pytest.mark.asyncio
async def test_edit_delete_and_restart_persist_against_same_database(db_path: Path):
    first_app = BookStockTrackerApp(db_path=db_path)

    async with first_app.run_test() as pilot:
        await create_report_with_inline_line(first_app, pilot, item_query="beta", in_qty="4")
        await pilot.press("shift+tab")
        await pilot.pause()
        await pilot.press("backspace")
        await type_text(pilot, "6")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        stock_rows_after_delete = table_rows(first_app.query_one("#stock-table", DataTable))

    assert stock_rows_after_delete == [["beta", "0", "0", "0"]]

    second_app = BookStockTrackerApp(db_path=db_path)
    async with second_app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        stock_rows_after_restart = table_rows(second_app.query_one("#stock-table", DataTable))
        await pilot.press("r")
        await pilot.pause()
        report_rows = table_rows(second_app.query_one("#report-table", DataTable))

    assert stock_rows_after_restart == [["beta", "0", "0", "0"]]
    assert report_rows == [[StockTrackerService.today_iso(), "New report"]]


@pytest.mark.asyncio
async def test_inline_dropdown_behaviour_and_focus_progression(db_path: Path):
    seed_existing_item(db_path, "alpha")
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()
        await type_text(pilot, "alp")
        await pilot.pause()

        editor = app.query_one(ReportLinesEditor)
        option_list = app.query_one("#item-suggestions", OptionList)
        labels = [str(option_list.get_option_at_index(index).prompt) for index in range(option_list.option_count)]

        assert option_list.display is True
        assert labels[-1] == "Create new item: alp"

        await pilot.press("down")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("up")
        await pilot.pause()
        assert option_list.highlighted == 0

        await pilot.press("enter")
        await pilot.pause()

        assert editor.suggestions_visible is False
        assert app.focused is not None
        assert app.focused.id == "cell-draft-in_qty"


@pytest.mark.asyncio
async def test_delete_arm_cancels_on_escape_and_selection_change(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="gamma", in_qty="2")
        await pilot.press("d")
        await pilot.pause()
        status_after_arm = str(app.query_one("#report-status").renderable)
        row = app.query_one(ReportLineRow)
        assert "Delete armed" in status_after_arm
        assert row.has_class("delete-armed")

        await pilot.press("escape")
        await pilot.pause()
        assert row.has_class("delete-armed") is False

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("shift+tab")
        await pilot.pause()
        assert row.has_class("delete-armed") is False
        assert inline_rows(app) == [["gamma", "2", "0"]]


@pytest.mark.asyncio
async def test_tab_from_report_date_moves_into_first_line_item(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="delta", in_qty="5")
        app.query_one("#report-date", CompactReportField).focus()
        await pilot.pause()

        assert app.focused is not None
        assert app.focused.id == "report-date-editor"

        await pilot.press("tab")
        await pilot.pause()

        assert app.focused is not None
        assert app.focused.id == "cell-1-name"


@pytest.mark.asyncio
async def test_tab_from_out_moves_to_next_row_or_creates_new_draft(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="alpha", in_qty="1")
        app.query_one("#report-table").focus()
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await type_text(pilot, "beta")
        await pilot.press("enter")
        await pilot.pause()
        await type_text(pilot, "2")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()

        assert app.focused is not None
        assert app.focused.id == "cell-draft-out_qty"

        await pilot.press("tab")
        await pilot.pause()

        assert inline_rows(app) == [["alpha", "1", "0"], ["beta", "2", "3"], ["", "", ""]]
        assert app.focused is not None
        assert app.focused.id == "cell-draft-name"

        app.query_one("#cell-2-out_qty").focus()
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "cell-2-out_qty"

        await pilot.press("tab")
        await pilot.pause()

        assert app.focused is not None
        assert app.focused.id == "cell-draft-name"


@pytest.mark.asyncio
async def test_shift_tab_from_name_moves_to_previous_row_or_date(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="alpha", in_qty="1")
        app.query_one("#report-table").focus()
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await type_text(pilot, "beta")
        await pilot.press("enter")
        await pilot.pause()
        await type_text(pilot, "2")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("3", "tab")
        await pilot.pause()

        assert app.focused is not None
        assert app.focused.id == "cell-draft-name"

        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "cell-2-out_qty"

        app.query_one("#cell-1-name").focus()
        await pilot.pause()
        await pilot.press("shift+tab")
        await pilot.pause()

        assert app.focused is not None
        assert app.focused.id == "report-date-editor"


@pytest.mark.asyncio
async def test_arrow_keys_navigate_between_rows_and_table_scrolls(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        for index in range(7):
            if index == 0:
                await create_report_with_inline_line(app, pilot, item_query=f"book-{index}", in_qty="1")
            else:
                app.query_one("#report-table").focus()
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                await type_text(pilot, f"book-{index}")
                await pilot.press("enter")
                await pilot.pause()
                await type_text(pilot, "1")
                await pilot.press("enter", "enter")
                await pilot.pause()

        app.query_one("#cell-1-name").focus()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "cell-2-name"

        await pilot.press("right")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "cell-2-in_qty"

        await pilot.press("down")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "cell-3-in_qty"

        app.query_one("#cell-7-name").focus()
        await pilot.pause()
        container = app.query_one("#report-lines-container", VerticalScroll)
        assert container.max_scroll_y > 0
        assert container.scroll_y > 0


@pytest.mark.asyncio
async def test_only_active_line_editor_is_visible(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await create_report_with_inline_line(app, pilot, item_query="alpha", in_qty="2")
        editor = app.query_one(ReportLinesEditor)

        editor.focus_cell("1", "name")
        await pilot.pause()
        visible_editors = [widget.id for widget in app.query(CompactLineInput) if widget.display]
        assert visible_editors == ["cell-1-name"]

        editor.focus_cell("1", "in_qty")
        await pilot.pause()
        visible_editors = [widget.id for widget in app.query(CompactLineInput) if widget.display]
        assert visible_editors == ["cell-1-in_qty"]


@pytest.mark.asyncio
async def test_report_header_stays_compact_until_focused(db_path: Path):
    app = BookStockTrackerApp(db_path=db_path)

    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()

        title_field = app.query_one("#report-title", CompactReportField)
        title_editor = title_field.query_one(ReportFieldInput)
        assert title_editor.display is False

        title_field.focus()
        await pilot.pause()

        assert title_editor.display is True
        assert app.focused is not None
        assert app.focused.id == "report-title-editor"
