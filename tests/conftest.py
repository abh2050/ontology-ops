import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "data" / "fixtures"


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """A writable copy of the authored fixture CSVs."""
    target = tmp_path / "src"
    target.mkdir()
    for csv_file in FIXTURES.glob("olist_*.csv"):
        shutil.copy(csv_file, target / csv_file.name)
    return target


def _db_up() -> bool:
    try:
        from sqlalchemy import text

        from ops.db import engine

        with engine("admin").connect() as conn:
            conn.execute(text("SELECT 1 FROM alembic_version"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db():
    if not _db_up():
        pytest.skip("local PostgreSQL not running or not migrated (docker compose up; ops migrate)")
    from ops.db import engine

    return engine
