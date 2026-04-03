"""CLI entrypoint for the book stock tracker."""

from __future__ import annotations

import argparse
from pathlib import Path

from .app import BookStockTrackerApp


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Run the book stock tracker app.")
    parser.add_argument(
        "--database",
        default="stock-tracker.db",
        help="Path to the SQLite database file.",
    )
    return parser


def main() -> None:
    """Run the application."""
    parser = build_parser()
    args = parser.parse_args()
    app = BookStockTrackerApp(db_path=Path(args.database))
    app.run()


if __name__ == "__main__":
    main()
