"""Exercise native WinHTTP POST against an isolated API. No foreground activity is sampled."""

import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.models import ActivityEvent, Preference


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="daylight-agent-test-") as folder:
        url = f"sqlite:///{Path(folder).as_posix()}/agent.db"
        engine = make_engine(url)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(Preference(id=1, monitoring_enabled=True))
            db.commit()
        env = {
            **os.environ,
            "DATABASE_URL": url,
            "AI_MODE": "demo",
            "AGENT_TOKEN": secrets.token_hex(24),
        }
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "58001",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            for _ in range(100):
                try:
                    if httpx.get("http://127.0.0.1:58001/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Test backend did not start")
            subprocess.run(
                [str(executable), "--test-report", "--backend", "http://127.0.0.1:58001"],
                env=env,
                check=True,
                timeout=15,
            )
            with Session(engine) as db:
                event = db.scalar(select(ActivityEvent))
                assert event is not None and event.state == "unknown" and event.app_name is None
            print(
                "Native C++ -> WinHTTP -> FastAPI -> database ingestion passed with a synthetic event."
            )
        finally:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(backend.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                backend.terminate()
            backend.wait(timeout=10)
            engine.dispose()


if __name__ == "__main__":
    main()
