# Book Stock Tracker

A keyboard-driven Textual application for tracking stock through reports.

## Setup

```bash
uv sync
```

## Run

```bash
uv run book-stock-tracker --database stock-tracker.db
```

## GitHub Pages

The repository's GitHub Pages site is built from the committed `stock-tracker.db` file and publishes a read-only view of the current stock.

Generate the static site locally with:

```bash
uv run python -m book_stock_tracker.export_pages --database stock-tracker.db --output-dir build/pages
```

Open `build/pages/index.html` to verify the output locally. Updating `stock-tracker.db` in the repo and pushing to `main` refreshes the published Pages site.

## Test

```bash
uv run pytest
```
