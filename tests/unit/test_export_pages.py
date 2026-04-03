from __future__ import annotations

from pathlib import Path

import pytest

from book_stock_tracker.export_pages import export_pages


def test_export_pages_writes_minimal_stock_table(service, db_path: Path, tmp_path: Path):
    zero_item = service.upsert_item_by_name("Archive Copy")
    inbound = service.create_report("Inbound", "2026-04-03")
    outbound = service.create_report("Outbound", "2026-04-04")

    service.create_report_line(inbound.id, "Zen and the Art", 7, 0)
    service.create_report_line(outbound.id, "Zen and the Art", 0, 2)
    service.create_report_line(outbound.id, "Negative Example", 0, 3)
    assert zero_item.name == "Archive Copy"

    output_dir = tmp_path / "pages"
    output_path = export_pages(db_path, output_dir)
    html = output_path.read_text(encoding="utf-8")

    assert output_path == output_dir / "index.html"
    assert "<title>Book Stock</title>" in html
    assert "<th scope=\"col\">Book</th>" in html
    assert "<th scope=\"col\">Current Stock</th>" in html
    assert "Archive Copy" in html
    assert "Zen and the Art" in html
    assert "Negative Example" in html
    assert ">0<" in html
    assert ">5<" in html
    assert ">-3<" in html
    assert "Total In" not in html
    assert "Total Out" not in html
    assert "Reports" not in html
    assert html.index("Archive Copy") < html.index("Negative Example") < html.index("Zen and the Art")


def test_export_pages_requires_existing_database(tmp_path: Path):
    missing_db = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="Database file does not exist"):
        export_pages(missing_db, tmp_path / "pages")
