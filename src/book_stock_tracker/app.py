"""Textual application for book stock tracking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.fuzzy import Matcher
from textual.widget import Widget
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)

from .services import StockTrackerService, ValidationError
from .storage import Database, Report, ReportLine, StockSummary, StockTrackerRepository


@dataclass(slots=True)
class EditableLineState:
    """UI state for an inline editable report line."""

    line_id: int | None
    item_name: str
    in_qty: str
    out_qty: str
    is_draft: bool = False


@dataclass(slots=True)
class SuggestionOption:
    """A fuzzy-search suggestion for the item name cell."""

    label: str
    value: str
    is_create_new: bool = False


class LineCellInput(Input):
    """An input widget that knows which report-line cell it belongs to."""

    def __init__(
        self,
        *,
        row_key: str,
        column_name: str,
        value: str,
        placeholder: str,
        input_type: str = "text",
        classes: str = "",
    ) -> None:
        super().__init__(
            value=value,
            placeholder=placeholder,
            id=f"cell-{row_key}-{column_name}",
            classes=f"line-cell {classes}".strip(),
            type=input_type,
        )
        self.row_key = row_key
        self.column_name = column_name

    def on_mount(self) -> None:
        self.cursor_position = len(self.value)

    def on_focus(self) -> None:
        editor = self._find_editor()
        if editor is not None:
            editor.handle_cell_focused(self)

    def on_key(self, event: events.Key) -> None:
        editor = self._find_editor()
        if editor is None:
            return

        if event.key == "tab":
            if self.column_name == "out_qty":
                editor.advance_after_out_tab(self.row_key)
                event.prevent_default()
                event.stop()
                return
            editor.focus_relative(self.row_key, self.column_name, 1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "shift+tab":
            if self.column_name == "name":
                editor.reverse_before_name_shift_tab(self.row_key)
                event.prevent_default()
                event.stop()
                return
            editor.focus_relative(self.row_key, self.column_name, -1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "down" and self.column_name == "name" and editor.suggestions_visible:
            editor.move_suggestion(1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "up" and self.column_name == "name" and editor.suggestions_visible:
            editor.move_suggestion(-1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "down":
            editor.move_vertical(self.row_key, self.column_name, 1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "up":
            editor.move_vertical(self.row_key, self.column_name, -1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "escape" and editor.cancel_inline_state():
            event.prevent_default()
            event.stop()
            return
        if event.key == "d" and self.column_name != "name":
            editor.arm_or_delete_selected_row()
            event.prevent_default()
            event.stop()
            return
        if event.key == "left" and self.cursor_position == 0 and self.column_name != "name":
            editor.focus_relative(self.row_key, self.column_name, -1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "right" and self.cursor_position == len(self.value) and self.column_name != "out_qty":
            editor.focus_relative(self.row_key, self.column_name, 1)
            event.prevent_default()
            event.stop()

    def _find_editor(self) -> ReportLinesEditor | None:
        node = self.parent
        while node is not None:
            if isinstance(node, ReportLinesEditor):
                return node
            node = node.parent
        return None


class ReportDateInput(Input):
    """Date input that tabs directly into the report line editor."""

    def on_key(self, event: events.Key) -> None:
        if event.key != "tab":
            return
        app = self.app
        if not isinstance(app, BookStockTrackerApp):
            return
        app.query_one(ReportLinesEditor).focus_from_report_header()
        event.prevent_default()
        event.stop()


class ReportLineRow(Horizontal):
    """A single inline-editable report-line row."""

    def __init__(self, state: EditableLineState, *, delete_armed: bool = False) -> None:
        row_key = self.row_key_from_state(state)
        classes = "report-line-row draft-row" if state.is_draft else "report-line-row"
        if delete_armed:
            classes = f"{classes} delete-armed"
        super().__init__(id=f"line-row-{row_key}", classes=classes)
        self.state = state

    @staticmethod
    def row_key_from_state(state: EditableLineState) -> str:
        return "draft" if state.line_id is None else str(state.line_id)

    @property
    def row_key(self) -> str:
        return self.row_key_from_state(self.state)

    def compose(self) -> ComposeResult:
        yield LineCellInput(
            row_key=self.row_key,
            column_name="name",
            value=self.state.item_name,
            placeholder="Item name",
            classes="name-cell",
        )
        yield LineCellInput(
            row_key=self.row_key,
            column_name="in_qty",
            value=self.state.in_qty,
            placeholder="0",
            input_type="integer",
            classes="qty-cell",
        )
        yield LineCellInput(
            row_key=self.row_key,
            column_name="out_qty",
            value=self.state.out_qty,
            placeholder="0",
            input_type="integer",
            classes="qty-cell",
        )


class ReportLinesEditor(Widget):
    """Inline report-line editor with fuzzy item search."""

    def __init__(
        self,
        service: StockTrackerService,
        *,
        on_status: Callable[[str], None],
        on_lines_changed: Callable[[], None],
    ) -> None:
        super().__init__(id="report-lines-editor")
        self.service = service
        self.on_status = on_status
        self.on_lines_changed = on_lines_changed
        self.current_report_id: int | None = None
        self.line_states: list[EditableLineState] = []
        self.draft_state: EditableLineState | None = None
        self.active_row_key: str | None = None
        self.active_column: str | None = None
        self.delete_armed_row_key: str | None = None
        self.suggestion_options: list[SuggestionOption] = []
        self._suppress_name_change_row: str | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("Name", classes="line-header name-cell"),
            Static("IN", classes="line-header qty-cell"),
            Static("OUT", classes="line-header qty-cell"),
            id="report-lines-header",
        )
        yield VerticalScroll(id="report-lines-container")
        yield OptionList(id="item-suggestions")

    def on_mount(self) -> None:
        self.query_one("#item-suggestions", OptionList).display = False
        self._queue_render_rows(placeholder="No line items yet. Press A to add one.")

    @property
    def suggestions_visible(self) -> bool:
        return self.query_one("#item-suggestions", OptionList).display

    def load_report(
        self,
        report_id: int | None,
        *,
        focus: tuple[str, str] | None = None,
        preserve_draft: bool = False,
    ) -> None:
        self.current_report_id = report_id
        self.active_row_key = None
        self.active_column = None
        self.delete_armed_row_key = None
        self.suggestion_options = []
        if not preserve_draft:
            self.draft_state = None
        if report_id is None:
            self.line_states = []
            self._queue_render_rows(placeholder="Create or open a report to edit its lines.")
            return

        lines = self.service.list_report_lines(report_id)
        self.line_states = [
            EditableLineState(
                line_id=line.id,
                item_name=line.item_name,
                in_qty=str(line.in_qty),
                out_qty=str(line.out_qty),
            )
            for line in lines
        ]
        placeholder = None if self.line_states else "No line items yet. Press A to add one."
        self._queue_render_rows(focus=focus, placeholder=placeholder)

    def start_new_row(self) -> None:
        if self.current_report_id is None:
            return
        self.delete_armed_row_key = None
        if self.draft_state is None:
            self.draft_state = EditableLineState(
                line_id=None,
                item_name="",
                in_qty="",
                out_qty="",
                is_draft=True,
            )
        self._queue_render_rows(focus=("draft", "name"))

    def focus_active_or_first(self) -> None:
        if self.active_row_key is not None and self.active_column is not None:
            self.focus_cell(self.active_row_key, self.active_column)
            return
        if self.line_states:
            self.focus_cell(str(self.line_states[0].line_id), "name")
            return
        if self.draft_state is not None:
            self.focus_cell("draft", "name")

    def focus_from_report_header(self) -> None:
        if self.line_states:
            self.focus_cell(str(self.line_states[0].line_id), "name")
            return
        if self.draft_state is not None:
            self.focus_cell("draft", "name")
            return
        if self.current_report_id is not None:
            self.start_new_row()

    def arm_or_delete_selected_row(self) -> None:
        row_key = self.active_row_key
        if row_key is None:
            if self.line_states:
                row_key = str(self.line_states[0].line_id)
                self.focus_cell(row_key, "name")
            else:
                self.on_status("Select a saved row to delete.")
                return
        if row_key == "draft":
            self.on_status("Draft row has not been saved yet.")
            return
        if self.delete_armed_row_key == row_key:
            self._delete_row(row_key)
            return
        self.delete_armed_row_key = row_key
        self._apply_delete_state()
        self.on_status("Delete armed for selected row. Press D or Enter again to confirm.")

    def focus_relative(self, row_key: str, column_name: str, direction: int) -> None:
        columns = ["name", "in_qty", "out_qty"]
        index = columns.index(column_name)
        target_index = max(0, min(len(columns) - 1, index + direction))
        self.focus_cell(row_key, columns[target_index])

    def advance_after_out_tab(self, row_key: str) -> None:
        if self.current_report_id is None:
            return
        persisted_line = self._commit_row(row_key, reload_focus=None)
        if persisted_line is None:
            return
        next_focus: tuple[str, str]
        next_row_key = self._next_row_key(str(persisted_line.id))
        if next_row_key is None:
            self.draft_state = EditableLineState(
                line_id=None,
                item_name="",
                in_qty="",
                out_qty="",
                is_draft=True,
            )
            next_focus = ("draft", "name")
        else:
            next_focus = (next_row_key, "name")
        self.load_report(self.current_report_id, focus=next_focus, preserve_draft=next_focus[0] == "draft")

    def reverse_before_name_shift_tab(self, row_key: str) -> None:
        previous_row_key = self._previous_row_key(row_key)
        if previous_row_key is None:
            self.app.query_one("#report-date", Input).focus()
            return
        self.focus_cell(previous_row_key, "out_qty")

    def move_vertical(self, row_key: str, column_name: str, direction: int) -> None:
        target_row_key = (
            self._next_row_key(row_key)
            if direction > 0
            else self._previous_row_key(row_key)
        )
        if target_row_key is None:
            return
        self.focus_cell(target_row_key, column_name)

    def focus_cell(self, row_key: str, column_name: str) -> None:
        selector = f"#cell-{row_key}-{column_name}"
        try:
            input_widget = self.query_one(selector, LineCellInput)
        except Exception:
            return
        input_widget.focus()
        input_widget.cursor_position = len(input_widget.value)
        input_widget.scroll_visible(immediate=True, animate=False)
        self.active_row_key = row_key
        self.active_column = column_name
        self._hide_suggestions()

    def move_suggestion(self, direction: int) -> None:
        option_list = self.query_one("#item-suggestions", OptionList)
        if not option_list.display or option_list.option_count == 0:
            return
        if direction > 0:
            option_list.action_cursor_down()
        else:
            option_list.action_cursor_up()

    def cancel_inline_state(self) -> bool:
        handled = False
        if self.suggestions_visible:
            self._hide_suggestions()
            handled = True
        if self.delete_armed_row_key is not None:
            self.delete_armed_row_key = None
            self._apply_delete_state()
            self.on_status("Delete cancelled.")
            handled = True
        return handled

    def handle_cell_focused(self, cell: LineCellInput) -> None:
        if self.delete_armed_row_key is not None:
            self.delete_armed_row_key = None
            self._apply_delete_state()
        self.active_row_key = cell.row_key
        self.active_column = cell.column_name
        self._hide_suggestions()

    @on(Input.Changed, ".line-cell")
    def handle_cell_changed(self, event: Input.Changed) -> None:
        cell = event.input
        if not isinstance(cell, LineCellInput):
            return
        if cell.column_name == "name" and self._suppress_name_change_row == cell.row_key:
            self._suppress_name_change_row = None
            return
        if self.delete_armed_row_key == cell.row_key:
            self.delete_armed_row_key = None
            self._apply_delete_state()
        self.active_row_key = cell.row_key
        self.active_column = cell.column_name
        if cell.column_name == "name":
            self._refresh_suggestions(event.value)
        else:
            self._hide_suggestions()

    @on(Input.Submitted, ".line-cell")
    def handle_cell_submitted(self, event: Input.Submitted) -> None:
        cell = event.input
        if not isinstance(cell, LineCellInput):
            return
        if self.delete_armed_row_key == cell.row_key and cell.column_name != "name":
            self._delete_row(cell.row_key)
            return
        if cell.column_name == "name":
            self._accept_name_selection(cell.row_key)
            return
        if cell.column_name == "in_qty":
            self.focus_cell(cell.row_key, "out_qty")
            return
        self._commit_row(cell.row_key)

    @on(OptionList.OptionSelected, "#item-suggestions")
    def handle_option_selected(self) -> None:
        if self.active_row_key is not None:
            self._accept_name_selection(self.active_row_key)

    def _commit_row(
        self,
        row_key: str,
        *,
        reload_focus: tuple[str, str] | None = ("__saved__", "out_qty"),
    ) -> ReportLine | None:
        if self.current_report_id is None:
            return None
        values = self._get_row_values(row_key)
        if values is None:
            return None
        item_name, in_qty, out_qty = values
        try:
            if row_key == "draft":
                persisted_line = self.service.create_report_line(
                    self.current_report_id,
                    item_name,
                    in_qty,
                    out_qty,
                )
                status = "Line added."
            else:
                persisted_line = self.service.update_report_line(
                    int(row_key),
                    item_name,
                    in_qty,
                    out_qty,
                )
                status = "Line updated."
        except ValidationError as exc:
            self.on_status(str(exc))
            self.focus_cell(row_key, "out_qty")
            return None
        self.on_status(status)
        self.on_lines_changed()
        if reload_focus is not None:
            focus = (
                (str(persisted_line.id), "out_qty")
                if reload_focus[0] == "__saved__"
                else reload_focus
            )
            self.load_report(self.current_report_id, focus=focus)
        return persisted_line

    def _delete_row(self, row_key: str) -> None:
        if row_key == "draft":
            self.on_status("Draft row has not been saved yet.")
            return
        self.service.delete_report_line(int(row_key))
        self.delete_armed_row_key = None
        self.on_status("Line deleted.")
        self.on_lines_changed()
        self.load_report(self.current_report_id)

    def _get_row_values(self, row_key: str) -> tuple[str, str, str] | None:
        try:
            item_name = self.query_one(f"#cell-{row_key}-name", LineCellInput).value
            in_qty = self.query_one(f"#cell-{row_key}-in_qty", LineCellInput).value
            out_qty = self.query_one(f"#cell-{row_key}-out_qty", LineCellInput).value
        except Exception:
            return None
        return item_name, in_qty, out_qty

    def _accept_name_selection(self, row_key: str) -> bool:
        try:
            name_input = self.query_one(f"#cell-{row_key}-name", LineCellInput)
        except Exception:
            return False
        value = name_input.value.strip()
        if not value:
            self.on_status("Item name is required.")
            return False
        if self.suggestions_visible and self.suggestion_options:
            option_list = self.query_one("#item-suggestions", OptionList)
            highlighted = option_list.highlighted if option_list.highlighted is not None else 0
            highlighted = max(0, min(len(self.suggestion_options) - 1, highlighted))
            selected = self.suggestion_options[highlighted]
            value = selected.value
        self._suppress_name_change_row = row_key
        name_input.value = value
        name_input.cursor_position = len(value)
        self._hide_suggestions()
        self.focus_cell(row_key, "in_qty")
        return True

    def _queue_render_rows(
        self,
        *,
        focus: tuple[str, str] | None = None,
        placeholder: str | None = None,
    ) -> None:
        self.run_worker(
            self._render_rows_async(focus=focus, placeholder=placeholder),
            group="report-lines-render",
            exclusive=True,
        )

    async def _render_rows_async(
        self,
        *,
        focus: tuple[str, str] | None = None,
        placeholder: str | None = None,
    ) -> None:
        container = self.query_one("#report-lines-container", VerticalScroll)
        await container.remove_children()
        rows = [
            ReportLineRow(
                state,
                delete_armed=self.delete_armed_row_key == ReportLineRow.row_key_from_state(state),
            )
            for state in self.line_states
        ]
        if self.draft_state is not None:
            rows.append(ReportLineRow(self.draft_state))
        if rows:
            await container.mount(*rows)
        elif placeholder is not None:
            await container.mount(Static(placeholder, id="report-lines-placeholder"))
        self._hide_suggestions()
        if focus is not None:
            self.call_after_refresh(lambda: self.focus_cell(*focus))

    def _refresh_suggestions(self, query: str) -> None:
        normalized_query = query.strip()
        if self.active_column != "name" or not normalized_query:
            self._hide_suggestions()
            return
        self.suggestion_options = self._build_suggestions(normalized_query)
        if not self.suggestion_options:
            self._hide_suggestions()
            return
        option_list = self.query_one("#item-suggestions", OptionList)
        option_list.clear_options()
        option_list.add_options(option.label for option in self.suggestion_options)
        option_list.highlighted = 0
        option_list.display = True

    def _hide_suggestions(self) -> None:
        option_list = self.query_one("#item-suggestions", OptionList)
        option_list.clear_options()
        option_list.display = False
        self.suggestion_options = []

    def _build_suggestions(self, query: str) -> list[SuggestionOption]:
        item_names = [item.name for item in self.service.list_items()]
        matcher = Matcher(query)
        exact_match = any(item.casefold() == query.casefold() for item in item_names)
        ranked_matches = [
            (matcher.match(item_name), item_name)
            for item_name in item_names
        ]
        matches = [
            item_name
            for score, item_name in sorted(
                ranked_matches,
                key=lambda item: (-item[0], item[1].casefold()),
            )
            if score > 0 or item_name.casefold() == query.casefold()
        ]

        suggestions = [
            SuggestionOption(label=item_name, value=item_name)
            for item_name in matches[:20]
        ]
        if not exact_match:
            suggestions.append(
                SuggestionOption(
                    label=f"Create new item: {query}",
                    value=query,
                    is_create_new=True,
                )
            )
        return suggestions

    def _next_row_key(self, row_key: str) -> str | None:
        row_keys = self._ordered_row_keys()
        try:
            current_index = row_keys.index(row_key)
        except ValueError:
            return None
        next_index = current_index + 1
        if next_index >= len(row_keys):
            return None
        return row_keys[next_index]

    def _previous_row_key(self, row_key: str) -> str | None:
        row_keys = self._ordered_row_keys()
        try:
            current_index = row_keys.index(row_key)
        except ValueError:
            return None
        previous_index = current_index - 1
        if previous_index < 0:
            return None
        return row_keys[previous_index]

    def _ordered_row_keys(self) -> list[str]:
        row_keys = [str(state.line_id) for state in self.line_states if state.line_id is not None]
        if self.draft_state is not None:
            row_keys.append("draft")
        return row_keys

    def _apply_delete_state(self) -> None:
        for row in self.query(ReportLineRow):
            if row.row_key == self.delete_armed_row_key:
                row.add_class("delete-armed")
            else:
                row.remove_class("delete-armed")


class BookStockTrackerApp(App[None]):
    """The main stock tracking application."""

    CSS = """
    Screen {
        layout: vertical;
    }

    Header {
        dock: top;
    }

    Footer {
        dock: bottom;
    }

    #main-tabs {
        height: 1fr;
    }

    #reports-layout {
        height: 1fr;
    }

    #report-list-panel {
        width: 33%;
        min-width: 24;
        height: 1fr;
        padding: 1;
        border: round $primary;
    }

    #report-editor-panel, #stock-panel {
        height: 1fr;
        padding: 1;
        border: round $accent;
    }

    #report-editor-panel {
        width: 67%;
    }

    #report-title, #report-date {
        height: 3;
        min-height: 3;
        margin-top: 0;
        padding: 0 1;
    }

    DataTable {
        height: 1fr;
        margin-top: 1;
    }

    #report-lines-editor {
        height: 1fr;
        margin-top: 0;
    }

    #report-lines-header, .report-line-row {
        height: auto;
        width: 1fr;
    }

    .line-header, .line-cell {
        margin-right: 1;
    }

    .line-header {
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
    }

    .name-cell {
        width: 1fr;
    }

    .qty-cell {
        width: 12;
    }

    #report-lines-container {
        height: 1fr;
    }

    #report-lines-placeholder {
        color: $text-muted;
        margin-top: 1;
    }

    .report-line-row {
        padding: 0;
    }

    .report-line-row .line-cell {
        height: 3;
        min-height: 3;
        padding: 0 1;
        margin-top: 0;
    }

    .report-line-row.delete-armed .line-cell {
        border: tall $error;
    }

    #item-suggestions {
        height: 7;
        margin-top: 1;
    }

    #report-status, #report-help, #stock-help {
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new_report", "New report"),
        Binding("r", "switch_reports", "Reports"),
        Binding("s", "switch_stock", "Stock"),
        Binding("a", "add_line", "Add line"),
        Binding("e", "edit_line", "Edit line"),
        Binding("d", "delete_line", "Delete line"),
        Binding("ctrl+s", "save_report", "Save report"),
    ]

    TITLE = "Book Stock Tracker"
    SUB_TITLE = "Reports drive stock totals"

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.database = Database(Path(db_path))
        self.repository = StockTrackerRepository(self.database)
        self.service = StockTrackerService(self.repository)
        self.current_report_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="main-tabs", initial="reports"):
            with TabPane("Reports", id="reports"):
                with Horizontal(id="reports-layout"):
                    with Vertical(id="report-list-panel"):
                        yield Static("Reports", id="reports-title")
                        yield DataTable(id="report-table")
                        yield Static("Use N to create a report and Enter to open one.", id="report-list-help")
                    with Vertical(id="report-editor-panel"):
                        yield Static("Report editor", id="editor-title")
                        yield Input(placeholder="Report title", id="report-title")
                        yield ReportDateInput(placeholder="YYYY-MM-DD", id="report-date")
                        yield ReportLinesEditor(
                            self.service,
                            on_status=self._set_status,
                            on_lines_changed=self._handle_lines_changed,
                        )
                        yield Static(
                            "Use A to add a row, arrows or Tab to move, Enter to accept or save, D twice to delete, Esc to cancel pending actions.",
                            id="report-help",
                        )
                        yield Static("No report selected.", id="report-status")
            with TabPane("Stock", id="stock"):
                with Vertical(id="stock-panel"):
                    yield Static("Current stock", id="stock-title")
                    yield DataTable(id="stock-table")
                    yield Static("Stock is recalculated from every saved report line.", id="stock-help")
        yield Footer()

    def on_mount(self) -> None:
        self.service.initialize()
        self._configure_tables()
        self._reload_reports()
        self._reload_stock()
        self.query_one("#report-table", DataTable).focus()

    def on_unmount(self) -> None:
        self.database.close()

    def _configure_tables(self) -> None:
        report_table = self.query_one("#report-table", DataTable)
        report_table.cursor_type = "row"
        report_table.zebra_stripes = True
        report_table.show_row_labels = False
        report_table.add_columns("Date", "Title")

        stock_table = self.query_one("#stock-table", DataTable)
        stock_table.cursor_type = "row"
        stock_table.zebra_stripes = True
        stock_table.show_row_labels = False
        stock_table.add_columns("Item", "Total In", "Total Out", "Current Stock")

    def action_new_report(self) -> None:
        new_report = self.service.create_report("New report", self.service.today_iso())
        self._reload_reports(select_report_id=new_report.id)
        self._set_status("New report created.")
        self.query_one("#report-table", DataTable).focus()

    def action_switch_reports(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "reports"
        self.query_one("#report-table", DataTable).focus()

    def action_switch_stock(self) -> None:
        self._reload_stock()
        self.query_one("#main-tabs", TabbedContent).active = "stock"
        self.query_one("#stock-table", DataTable).focus()

    def action_save_report(self) -> None:
        if self.current_report_id is None:
            self._set_status("Create or open a report first.")
            return
        title = self.query_one("#report-title", Input).value
        report_date = self.query_one("#report-date", Input).value
        try:
            updated_report = self.service.update_report(self.current_report_id, title, report_date)
        except ValidationError as exc:
            self._set_status(str(exc))
            return
        self._reload_reports(select_report_id=updated_report.id)
        self._set_status("Report saved.")

    def action_add_line(self) -> None:
        if self.current_report_id is None:
            self.action_new_report()
        self.query_one(ReportLinesEditor).start_new_row()

    def action_edit_line(self) -> None:
        self.query_one(ReportLinesEditor).focus_active_or_first()

    def action_delete_line(self) -> None:
        self.query_one(ReportLinesEditor).arm_or_delete_selected_row()

    @on(DataTable.RowHighlighted, "#report-table")
    def handle_report_highlighted(self, event: DataTable.RowHighlighted) -> None:
        report_id = self._row_key_to_int(event.row_key)
        self._open_report(report_id)

    @on(DataTable.RowSelected, "#report-table")
    def handle_report_selected(self, event: DataTable.RowSelected) -> None:
        report_id = self._row_key_to_int(event.row_key)
        self._open_report(report_id)
        self.query_one("#report-title", Input).focus()

    def _reload_reports(self, select_report_id: int | None = None) -> None:
        report_table = self.query_one("#report-table", DataTable)
        reports = self.service.list_reports()
        report_table.clear(columns=False)
        for report in reports:
            report_table.add_row(report.report_date, report.title, key=str(report.id))

        if not reports:
            self.current_report_id = None
            self.query_one("#report-title", Input).value = ""
            self.query_one("#report-date", Input).value = ""
            self.query_one(ReportLinesEditor).load_report(None)
            self._set_status("No reports yet. Press N to create one.")
            return

        target_report_id = select_report_id or self.current_report_id or reports[0].id
        try:
            row_index = report_table.get_row_index(str(target_report_id))
        except Exception:
            row_index = 0
            target_report_id = reports[0].id
        report_table.move_cursor(row=row_index, column=0)
        self._open_report(target_report_id)

    def _open_report(self, report_id: int) -> None:
        report = self.service.get_report(report_id)
        if report is None:
            return
        if (
            self.current_report_id == report.id
            and self.query_one("#report-title", Input).value == report.title
            and self.query_one("#report-date", Input).value == report.report_date
        ):
            return
        self.current_report_id = report.id
        self.query_one("#report-title", Input).value = report.title
        self.query_one("#report-date", Input).value = report.report_date
        self.query_one(ReportLinesEditor).load_report(report.id)
        self._set_status(f"Viewing report: {report.title} ({report.report_date})")

    def _reload_stock(self) -> None:
        stock_table = self.query_one("#stock-table", DataTable)
        stock_table.clear(columns=False)
        rows = self.service.get_stock_summary()
        for stock_row in rows:
            stock_table.add_row(
                stock_row.item_name,
                str(stock_row.total_in),
                str(stock_row.total_out),
                str(stock_row.current_stock),
                key=str(stock_row.item_id),
            )
        if rows:
            stock_table.move_cursor(row=0, column=0)

    def _handle_lines_changed(self) -> None:
        self._reload_stock()

    def _set_status(self, message: str) -> None:
        self.query_one("#report-status", Static).update(message)

    @staticmethod
    def _row_key_to_int(row_key: Any) -> int:
        raw_value = getattr(row_key, "value", row_key)
        return int(str(raw_value))
