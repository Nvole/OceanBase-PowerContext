import os
import sys
import tempfile
from pathlib import Path

import pytest

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
test_directory = tempfile.TemporaryDirectory(prefix='qoder_pytest_')
os.environ['SEEKDB_HOST'] = ''
os.environ['QODER_SQLITE_PATH'] = str(Path(test_directory.name) / 'research.db')

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine


@pytest.fixture(autouse=True)
def reset_test_database():
    assert engine.url.drivername == 'sqlite'
    assert Path(engine.url.database).resolve().parent == Path(test_directory.name).resolve()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    test_directory.cleanup()
