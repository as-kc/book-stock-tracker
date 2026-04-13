"""Static GitHub Pages export for the current book stock."""

from __future__ import annotations

import argparse
import csv
from html import escape
from io import StringIO
from pathlib import Path

from .services import StockTrackerService
from .storage import Database, StockSummary, StockTrackerRepository

PAGE_TITLE = "Book Stock"
CSV_FILENAME = "stock-summary.csv"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the static export."""
    parser = argparse.ArgumentParser(
        description="Generate a read-only static site for the current book stock."
    )
    parser.add_argument(
        "--database",
        default="stock-tracker.db",
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--output-dir",
        default="build/pages",
        help="Directory where index.html will be written.",
    )
    return parser


def export_pages(database_path: Path, output_dir: Path) -> Path:
    """Write the static stock page assets and return the generated HTML path."""
    stock_rows = _load_stock_summary(database_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"
    csv_path = output_dir / CSV_FILENAME
    output_path.write_text(render_stock_page(stock_rows), encoding="utf-8")
    csv_path.write_text(render_stock_csv(stock_rows), encoding="utf-8", newline="")
    return output_path


def render_stock_page(stock_rows: list[StockSummary]) -> str:
    """Render the stock page HTML."""
    body_rows = "\n".join(_render_row(row) for row in stock_rows)
    total_books = len(stock_rows)
    if stock_rows:
        empty_state_row = (
            '        <tr id="no-matches-row" hidden>'
            '<td colspan="2" class="empty-state">No matching books found.</td>'
            "</tr>"
        )
        initial_status = f"Showing all {total_books} books."
    else:
        empty_state_row = (
            '        <tr id="empty-stock-row">'
            '<td colspan="2" class="empty-state">No books found.</td>'
            "</tr>"
        )
        initial_status = "No books available."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{PAGE_TITLE}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      background: #f6f1e8;
      color: #1f1a16;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top, rgba(173, 137, 85, 0.18), transparent 34%),
        linear-gradient(180deg, #f8f3ea 0%, #efe5d4 100%);
    }}

    main {{
      width: min(720px, calc(100vw - 2rem));
      margin: 3rem auto;
      padding: 2rem;
      background: rgba(255, 252, 246, 0.92);
      border: 1px solid rgba(91, 67, 43, 0.16);
      border-radius: 20px;
      box-shadow: 0 20px 60px rgba(91, 67, 43, 0.12);
    }}

    h1 {{
      margin: 0;
      font-size: clamp(2rem, 4vw, 3rem);
      line-height: 1.1;
      letter-spacing: 0.02em;
    }}

    .page-header {{
      display: grid;
      gap: 1.5rem;
      margin-bottom: 1.5rem;
    }}

    .page-header-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }}

    .download-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.75rem 1rem;
      border-radius: 999px;
      border: 1px solid rgba(91, 67, 43, 0.18);
      background: #5b432b;
      color: #fffaf2;
      text-decoration: none;
      font-size: 0.95rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      white-space: nowrap;
      box-shadow: 0 10px 24px rgba(91, 67, 43, 0.16);
    }}

    .download-link:hover,
    .download-link:focus-visible {{
      background: #4a3521;
    }}

    .search-panel {{
      display: grid;
      gap: 0.55rem;
      padding: 1rem;
      border: 1px solid rgba(91, 67, 43, 0.14);
      border-radius: 16px;
      background: rgba(255, 248, 237, 0.88);
    }}

    .search-label {{
      font-size: 0.95rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}

    .search-input {{
      width: 100%;
      padding: 0.85rem 1rem;
      border: 1px solid rgba(91, 67, 43, 0.2);
      border-radius: 12px;
      background: #fffdf8;
      color: inherit;
      font: inherit;
      font-size: 1rem;
    }}

    .search-input:focus-visible {{
      outline: 2px solid rgba(91, 67, 43, 0.35);
      outline-offset: 2px;
    }}

    .search-help,
    .search-status {{
      margin: 0;
      font-size: 0.95rem;
      color: rgba(31, 26, 22, 0.78);
    }}

    .search-status {{
      font-weight: 600;
      color: rgba(31, 26, 22, 0.88);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 1.05rem;
    }}

    th,
    td {{
      padding: 0.9rem 0.75rem;
      border-bottom: 1px solid rgba(91, 67, 43, 0.16);
      text-align: left;
    }}

    th:last-child,
    td:last-child {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}

    tbody tr:nth-child(even) {{
      background: rgba(138, 108, 73, 0.06);
    }}

    tbody tr:last-child td {{
      border-bottom: none;
    }}

    .empty-state {{
      text-align: center;
      color: rgba(31, 26, 22, 0.72);
    }}

    @media (max-width: 640px) {{
      main {{
        margin: 1rem auto;
        padding: 1.25rem;
      }}

      .page-header-top {{
        align-items: stretch;
        flex-direction: column;
      }}

      .download-link {{
        width: 100%;
      }}

      table {{
        font-size: 0.98rem;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="page-header">
      <div class="page-header-top">
        <h1>{PAGE_TITLE}</h1>
        <a class="download-link" href="{CSV_FILENAME}" download>Download CSV</a>
      </div>
      <div class="search-panel">
        <label class="search-label" for="book-search">Search books</label>
        <input
          id="book-search"
          class="search-input"
          type="search"
          placeholder="Try Krishna or bgi"
          autocomplete="off"
          spellcheck="false"
          aria-describedby="search-help search-status"
        >
        <p class="search-help" id="search-help">Type to filter books with fuzzy matching.</p>
        <p class="search-status" id="search-status" role="status" aria-live="polite">{initial_status}</p>
      </div>
    </div>
    <table id="stock-table">
      <thead>
        <tr>
          <th scope="col">Book</th>
          <th scope="col">Current Stock</th>
        </tr>
      </thead>
      <tbody id="stock-table-body">
        {body_rows}
{empty_state_row}
      </tbody>
    </table>
  </main>
  <script>
    const searchInput = document.getElementById("book-search");
    const statusElement = document.getElementById("search-status");
    const noMatchesRow = document.getElementById("no-matches-row");
    const bookRows = Array.from(document.querySelectorAll("[data-book-row]"));
    const totalRows = bookRows.length;

    function normalizeSearchValue(value) {{
      return value.trim().toLowerCase();
    }}

    function fuzzyScore(query, candidate) {{
      if (!query) {{
        return 1;
      }}

      if (candidate === query) {{
        return 1_000;
      }}

      const substringIndex = candidate.indexOf(query);
      if (substringIndex !== -1) {{
        return 500 - substringIndex;
      }}

      let score = 0;
      let queryIndex = 0;
      let candidateIndex = 0;
      let consecutiveBonus = 0;
      let lastMatchIndex = -1;

      while (queryIndex < query.length && candidateIndex < candidate.length) {{
        if (query[queryIndex] === candidate[candidateIndex]) {{
          score += 10;
          if (lastMatchIndex === candidateIndex - 1) {{
            consecutiveBonus += 5;
            score += consecutiveBonus;
          }} else {{
            consecutiveBonus = 0;
          }}
          lastMatchIndex = candidateIndex;
          queryIndex += 1;
        }}
        candidateIndex += 1;
      }}

      if (queryIndex !== query.length) {{
        return 0;
      }}

      return score - (candidate.length - query.length);
    }}

    function updateSearchResults() {{
      const rawQuery = searchInput.value.trim();
      const normalizedQuery = normalizeSearchValue(rawQuery);

      if (!totalRows) {{
        statusElement.textContent = "No books available.";
        return;
      }}

      if (!normalizedQuery) {{
        for (const row of bookRows) {{
          row.hidden = false;
        }}
        if (noMatchesRow) {{
          noMatchesRow.hidden = true;
        }}
        statusElement.textContent = `Showing all ${{totalRows}} books.`;
        return;
      }}

      let visibleRows = 0;

      for (const row of bookRows) {{
        const candidate = normalizeSearchValue(row.dataset.bookTitle || "");
        const matches = fuzzyScore(normalizedQuery, candidate) > 0;
        row.hidden = !matches;
        if (matches) {{
          visibleRows += 1;
        }}
      }}

      if (noMatchesRow) {{
        noMatchesRow.hidden = visibleRows > 0;
      }}

      if (!visibleRows) {{
        statusElement.textContent = `No matching books found for "${{rawQuery}}".`;
        return;
      }}

      statusElement.textContent = `Showing ${{visibleRows}} of ${{totalRows}} books for "${{rawQuery}}".`;
    }}

    searchInput.addEventListener("input", updateSearchResults);
    updateSearchResults();
  </script>
</body>
</html>
"""


def render_stock_csv(stock_rows: list[StockSummary]) -> str:
    """Render the stock page CSV."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Book", "Current Stock"])
    for row in stock_rows:
        writer.writerow([row.item_name, row.current_stock])
    return buffer.getvalue()


def _load_stock_summary(database_path: Path) -> list[StockSummary]:
    database = Database(database_path, read_only=True)
    try:
        service = StockTrackerService(StockTrackerRepository(database))
        return service.get_stock_summary()
    finally:
        database.close()


def _render_row(row: StockSummary) -> str:
    return (
        f'        <tr data-book-row data-book-title="{escape(row.item_name)}">'
        f"<td>{escape(row.item_name)}</td>"
        f"<td>{row.current_stock}</td>"
        "</tr>"
    )


def main() -> None:
    """Run the static export."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        output_path = export_pages(Path(args.database), Path(args.output_dir))
    except (FileNotFoundError, OSError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")
    print(f"Generated {output_path}")


if __name__ == "__main__":
    main()
