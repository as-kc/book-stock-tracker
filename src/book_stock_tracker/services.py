"""Application services and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .storage import Item, Report, ReportLine, StockSummary, StockTrackerRepository


class ValidationError(ValueError):
    """Raised when app-level validation fails."""


@dataclass(slots=True)
class LineInput:
    """Normalized input for creating or updating a report line."""

    item_name: str
    in_qty: int
    out_qty: int


class StockTrackerService:
    """Business logic for the stock tracker app."""

    def __init__(self, repository: StockTrackerRepository) -> None:
        self.repository = repository

    def initialize(self) -> None:
        """Initialize storage."""
        self.repository.initialize()

    def list_reports(self) -> list[Report]:
        """Return all reports."""
        return self.repository.list_reports()

    def get_report(self, report_id: int) -> Report | None:
        """Fetch a single report."""
        return self.repository.get_report(report_id)

    def create_report(self, title: str, report_date: str) -> Report:
        """Validate and insert a report."""
        normalized_title = self._validate_title(title)
        normalized_date = self._validate_report_date(report_date)
        return self.repository.create_report(normalized_title, normalized_date)

    def update_report(self, report_id: int, title: str, report_date: str) -> Report:
        """Validate and update a report."""
        normalized_title = self._validate_title(title)
        normalized_date = self._validate_report_date(report_date)
        return self.repository.update_report(report_id, normalized_title, normalized_date)

    def list_items(self) -> list[Item]:
        """Return the item catalog."""
        return self.repository.list_items()

    def upsert_item_by_name(self, name: str) -> Item:
        """Validate and return a catalog item."""
        normalized_name = self._validate_item_name(name)
        return self.repository.upsert_item_by_name(normalized_name)

    def list_report_lines(self, report_id: int) -> list[ReportLine]:
        """Return lines for a single report."""
        return self.repository.list_report_lines(report_id)

    def create_report_line(
        self,
        report_id: int,
        item_name: str,
        in_qty: str | int,
        out_qty: str | int,
    ) -> ReportLine:
        """Validate and create a report line."""
        line_input = self.normalize_line_input(item_name, in_qty, out_qty)
        item = self.upsert_item_by_name(line_input.item_name)
        return self.repository.create_report_line(
            report_id=report_id,
            item_id=item.id,
            in_qty=line_input.in_qty,
            out_qty=line_input.out_qty,
        )

    def update_report_line(
        self,
        line_id: int,
        item_name: str,
        in_qty: str | int,
        out_qty: str | int,
    ) -> ReportLine:
        """Validate and update a line item."""
        line_input = self.normalize_line_input(item_name, in_qty, out_qty)
        item = self.upsert_item_by_name(line_input.item_name)
        return self.repository.update_report_line(
            line_id=line_id,
            item_id=item.id,
            in_qty=line_input.in_qty,
            out_qty=line_input.out_qty,
        )

    def delete_report_line(self, line_id: int) -> None:
        """Delete a line item."""
        self.repository.delete_report_line(line_id)

    def get_stock_summary(self) -> list[StockSummary]:
        """Return stock totals."""
        return self.repository.get_stock_summary()

    def normalize_line_input(
        self,
        item_name: str,
        in_qty: str | int,
        out_qty: str | int,
    ) -> LineInput:
        """Normalize raw line values from the UI."""
        normalized_item_name = self._validate_item_name(item_name)
        normalized_in = self._parse_quantity(in_qty, field_name="IN")
        normalized_out = self._parse_quantity(out_qty, field_name="OUT")
        if normalized_in == 0 and normalized_out == 0:
            raise ValidationError("At least one of IN or OUT must be greater than zero.")
        return LineInput(
            item_name=normalized_item_name,
            in_qty=normalized_in,
            out_qty=normalized_out,
        )

    @staticmethod
    def today_iso() -> str:
        """Return the current date in ISO format."""
        return date.today().isoformat()

    @staticmethod
    def _validate_title(title: str) -> str:
        normalized = title.strip()
        if not normalized:
            raise ValidationError("Report title is required.")
        return normalized

    @staticmethod
    def _validate_item_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("Item name is required.")
        return normalized

    @staticmethod
    def _validate_report_date(report_date: str) -> str:
        candidate = report_date.strip()
        if not candidate:
            raise ValidationError("Report date is required.")
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError as exc:
            raise ValidationError("Report date must use YYYY-MM-DD.") from exc

    @staticmethod
    def _parse_quantity(value: str | int, field_name: str) -> int:
        if isinstance(value, int):
            quantity = value
        else:
            candidate = value.strip()
            if candidate == "":
                return 0
            try:
                quantity = int(candidate)
            except ValueError as exc:
                raise ValidationError(f"{field_name} quantity must be a whole number.") from exc
        if quantity < 0:
            raise ValidationError(f"{field_name} quantity cannot be negative.")
        return quantity
