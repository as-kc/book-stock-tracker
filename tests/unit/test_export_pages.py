from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

import pytest

from book_stock_tracker.export_pages import CSV_FILENAME, export_pages


def test_export_pages_writes_minimal_stock_table(service, db_path: Path, tmp_path: Path):
    zero_item = service.upsert_item_by_name("Archive Copy")
    inbound = service.create_report("Inbound", "2026-04-03")
    outbound = service.create_report("Outbound", "2026-04-04")

    service.create_report_line(inbound.id, "Zen and the Art", 7, 0)
    service.create_report_line(outbound.id, "Zen and the Art", 0, 2)
    service.create_report_line(outbound.id, "Negative Example", 0, 3)
    service.create_report_line(inbound.id, 'Comma, Quote "Book"', 1, 0)
    assert zero_item.name == "Archive Copy"

    output_dir = tmp_path / "pages"
    output_path = export_pages(db_path, output_dir)
    html = output_path.read_text(encoding="utf-8")
    csv_path = output_dir / CSV_FILENAME
    csv_rows = list(csv.reader(StringIO(csv_path.read_text(encoding="utf-8"))))

    assert output_path == output_dir / "index.html"
    assert csv_path.exists()
    assert "<title>Book Stock</title>" in html
    assert 'href="stock-summary.csv"' in html
    assert "Download CSV" in html
    assert 'for="book-search"' in html
    assert 'id="book-search"' in html
    assert 'aria-describedby="search-status"' in html
    assert "placeholder=" not in html
    assert 'id="search-status"' in html
    assert "Showing all 4 books." in html
    assert 'id="no-matches-row"' in html
    assert 'data-book-row data-book-title="Archive Copy"' in html
    assert 'data-book-row data-book-title="Comma, Quote &quot;Book&quot;"' in html
    assert "function fuzzyScore" in html
    assert 'searchInput.addEventListener("input", updateSearchResults);' in html
    assert "<th scope=\"col\">Book</th>" in html
    assert "<th scope=\"col\">Current Stock</th>" in html
    assert "Archive Copy" in html
    assert "Comma, Quote" in html
    assert "Zen and the Art" in html
    assert "Negative Example" in html
    assert ">0<" in html
    assert ">1<" in html
    assert ">5<" in html
    assert ">-3<" in html
    assert "Total In" not in html
    assert "Total Out" not in html
    assert "Reports" not in html
    assert html.index("Archive Copy") < html.index("Comma, Quote") < html.index("Negative Example") < html.index("Zen and the Art")
    assert csv_rows == [
        ["Book", "Current Stock"],
        ["Archive Copy", "0"],
        ['Comma, Quote "Book"', "1"],
        ["Negative Example", "-3"],
        ["Zen and the Art", "5"],
    ]


def test_export_pages_writes_csv_header_when_stock_is_empty(service, db_path: Path, tmp_path: Path):
    output_dir = tmp_path / "pages"

    output_path = export_pages(db_path, output_dir)
    html = output_path.read_text(encoding="utf-8")

    csv_path = output_dir / CSV_FILENAME
    csv_rows = list(csv.reader(StringIO(csv_path.read_text(encoding="utf-8"))))

    assert 'id="book-search"' in html
    assert "No books available." in html
    assert "No books found." in html
    assert 'id="empty-stock-row"' in html
    assert csv_rows == [["Book", "Current Stock"]]


def test_export_pages_requires_existing_database(tmp_path: Path):
    missing_db = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="Database file does not exist"):
        export_pages(missing_db, tmp_path / "pages")
