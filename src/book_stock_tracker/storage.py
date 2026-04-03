"""SQLite persistence for the book stock tracker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    report_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(length(trim(title)) > 0)
);

CREATE TABLE IF NOT EXISTS report_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    in_qty INTEGER NOT NULL DEFAULT 0,
    out_qty INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE RESTRICT,
    CHECK(in_qty >= 0),
    CHECK(out_qty >= 0),
    CHECK(in_qty > 0 OR out_qty > 0)
);

CREATE INDEX IF NOT EXISTS idx_reports_report_date
ON reports(report_date DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_report_lines_report_id
ON report_lines(report_id, position);

CREATE INDEX IF NOT EXISTS idx_report_lines_item_id
ON report_lines(item_id);
"""


@dataclass(slots=True)
class Item:
    """A catalog item."""

    id: int
    name: str


@dataclass(slots=True)
class Report:
    """A saved report."""

    id: int
    title: str
    report_date: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ReportLine:
    """A line item inside a report."""

    id: int
    report_id: int
    item_id: int
    item_name: str
    in_qty: int
    out_qty: int
    position: int


@dataclass(slots=True)
class StockSummary:
    """Aggregated stock totals for a single item."""

    item_id: int
    item_name: str
    total_in: int
    total_out: int
    current_stock: int


class Database:
    """Thin wrapper around a SQLite connection."""

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        self.db_path = Path(db_path)
        self.read_only = read_only
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = self._connect()
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the active connection."""
        return self._connection

    def initialize(self) -> None:
        """Create the application schema if needed."""
        if self.read_only:
            raise RuntimeError("Cannot initialize a read-only database connection.")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self.connection.close()

    def _connect(self) -> sqlite3.Connection:
        if not self.read_only:
            return sqlite3.connect(str(self.db_path))
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file does not exist: {self.db_path}")
        try:
            return sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.OperationalError as exc:
            raise OSError(f"Could not open database in read-only mode: {self.db_path}") from exc


class StockTrackerRepository:
    """Repository methods for reports, items, and stock summaries."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the current SQLite connection."""
        return self.database.connection

    def initialize(self) -> None:
        """Initialize the schema."""
        self.database.initialize()

    def list_items(self) -> list[Item]:
        """Return every known item ordered by name."""
        rows = self.connection.execute(
            "SELECT id, name FROM items ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        return [Item(id=row["id"], name=row["name"]) for row in rows]

    def upsert_item_by_name(self, name: str) -> Item:
        """Create an item when needed and return the catalog row."""
        cursor = self.connection.execute(
            """
            INSERT INTO items (name)
            VALUES (?)
            ON CONFLICT(name) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, name
            """,
            (name,),
        )
        row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            raise RuntimeError("Failed to create or fetch item.")
        return Item(id=row["id"], name=row["name"])

    def create_report(self, title: str, report_date: str) -> Report:
        """Insert and return a new report."""
        cursor = self.connection.execute(
            """
            INSERT INTO reports (title, report_date)
            VALUES (?, ?)
            RETURNING id, title, report_date, created_at, updated_at
            """,
            (title, report_date),
        )
        row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            raise RuntimeError("Failed to create report.")
        return self._report_from_row(row)

    def update_report(self, report_id: int, title: str, report_date: str) -> Report:
        """Update and return a report."""
        cursor = self.connection.execute(
            """
            UPDATE reports
            SET title = ?, report_date = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            RETURNING id, title, report_date, created_at, updated_at
            """,
            (title, report_date, report_id),
        )
        row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            raise KeyError(f"Unknown report id {report_id}")
        return self._report_from_row(row)

    def get_report(self, report_id: int) -> Report | None:
        """Fetch a single report."""
        row = self.connection.execute(
            """
            SELECT id, title, report_date, created_at, updated_at
            FROM reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()
        return self._report_from_row(row) if row else None

    def list_reports(self) -> list[Report]:
        """Return reports sorted newest first."""
        rows = self.connection.execute(
            """
            SELECT id, title, report_date, created_at, updated_at
            FROM reports
            ORDER BY report_date DESC, created_at DESC, id DESC
            """
        ).fetchall()
        return [self._report_from_row(row) for row in rows]

    def create_report_line(
        self,
        report_id: int,
        item_id: int,
        in_qty: int,
        out_qty: int,
    ) -> ReportLine:
        """Insert a line item into a report."""
        next_position = self.connection.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM report_lines WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]
        cursor = self.connection.execute(
            """
            INSERT INTO report_lines (report_id, item_id, in_qty, out_qty, position)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            (report_id, item_id, in_qty, out_qty, next_position),
        )
        row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            raise RuntimeError("Failed to create report line.")
        line = self.get_report_line(int(row["id"]))
        if line is None:
            raise RuntimeError("Created line could not be fetched.")
        return line

    def update_report_line(
        self,
        line_id: int,
        item_id: int,
        in_qty: int,
        out_qty: int,
    ) -> ReportLine:
        """Update an existing report line."""
        cursor = self.connection.execute(
            """
            UPDATE report_lines
            SET item_id = ?, in_qty = ?, out_qty = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            RETURNING id
            """,
            (item_id, in_qty, out_qty, line_id),
        )
        row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            raise KeyError(f"Unknown line id {line_id}")
        line = self.get_report_line(int(row["id"]))
        if line is None:
            raise RuntimeError("Updated line could not be fetched.")
        return line

    def delete_report_line(self, line_id: int) -> None:
        """Delete a line from a report."""
        cursor = self.connection.execute(
            "DELETE FROM report_lines WHERE id = ?",
            (line_id,),
        )
        self.connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Unknown line id {line_id}")

    def get_report_line(self, line_id: int) -> ReportLine | None:
        """Fetch one line item by id."""
        row = self.connection.execute(
            """
            SELECT
                report_lines.id,
                report_lines.report_id,
                report_lines.item_id,
                items.name AS item_name,
                report_lines.in_qty,
                report_lines.out_qty,
                report_lines.position
            FROM report_lines
            JOIN items ON items.id = report_lines.item_id
            WHERE report_lines.id = ?
            """,
            (line_id,),
        ).fetchone()
        return self._line_from_row(row) if row else None

    def list_report_lines(self, report_id: int) -> list[ReportLine]:
        """Return lines for a report ordered by insertion position."""
        rows = self.connection.execute(
            """
            SELECT
                report_lines.id,
                report_lines.report_id,
                report_lines.item_id,
                items.name AS item_name,
                report_lines.in_qty,
                report_lines.out_qty,
                report_lines.position
            FROM report_lines
            JOIN items ON items.id = report_lines.item_id
            WHERE report_lines.report_id = ?
            ORDER BY report_lines.position ASC, report_lines.id ASC
            """,
            (report_id,),
        ).fetchall()
        return [self._line_from_row(row) for row in rows]

    def get_stock_summary(self) -> list[StockSummary]:
        """Return aggregated stock totals per item."""
        rows = self.connection.execute(
            """
            SELECT
                items.id AS item_id,
                items.name AS item_name,
                COALESCE(SUM(report_lines.in_qty), 0) AS total_in,
                COALESCE(SUM(report_lines.out_qty), 0) AS total_out,
                COALESCE(SUM(report_lines.in_qty - report_lines.out_qty), 0) AS current_stock
            FROM items
            LEFT JOIN report_lines ON report_lines.item_id = items.id
            GROUP BY items.id, items.name
            ORDER BY items.name COLLATE NOCASE ASC
            """
        ).fetchall()
        return [
            StockSummary(
                item_id=row["item_id"],
                item_name=row["item_name"],
                total_in=row["total_in"],
                total_out=row["total_out"],
                current_stock=row["current_stock"],
            )
            for row in rows
        ]

    @staticmethod
    def _report_from_row(row: sqlite3.Row) -> Report:
        return Report(
            id=row["id"],
            title=row["title"],
            report_date=row["report_date"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _line_from_row(row: sqlite3.Row) -> ReportLine:
        return ReportLine(
            id=row["id"],
            report_id=row["report_id"],
            item_id=row["item_id"],
            item_name=row["item_name"],
            in_qty=row["in_qty"],
            out_qty=row["out_qty"],
            position=row["position"],
        )
