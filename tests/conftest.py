from __future__ import annotations

from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from book_stock_tracker.services import StockTrackerService
from book_stock_tracker.storage import Database, StockTrackerRepository


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-stock-tracker.db"


@pytest.fixture
def service(db_path: Path) -> StockTrackerService:
    database = Database(db_path)
    repository = StockTrackerRepository(database)
    tracker_service = StockTrackerService(repository)
    tracker_service.initialize()
    yield tracker_service
    database.close()
