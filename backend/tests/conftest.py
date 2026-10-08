import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AI_MODE"] = "demo"
os.environ["AGENT_TOKEN"] = "test-agent-token"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db, make_engine
from app.main import app
from app.models import Preference


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(Preference(id=1))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    def override():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = override
    with TestClient(app) as api:
        yield api
    app.dependency_overrides.clear()
