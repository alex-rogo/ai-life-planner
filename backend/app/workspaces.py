"""Private SQLite workspaces for signed-in users and short-lived demos.

The original planner stores all state in one database, including its singleton preferences.
Keeping a separate database per identity preserves those invariants while preventing a visitor
from seeing or mutating another visitor's calendar. Never accept a database path from the client.
"""

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.config import Settings
from app.db import make_engine

COOKIE = "tomo_demo"
GUEST_DAYS = 7
TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_lock = threading.RLock()
_migrated: set[str] = set()
_demo_attempts: dict[str, deque[float]] = defaultdict(deque)


def _root(settings: Settings) -> Path:
    root = Path(settings.workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(settings: Settings, kind: str, identity: str) -> Path:
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return _root(settings) / kind / f"{digest}.db"


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@lru_cache(maxsize=256)
def _factory(path: str):
    return sessionmaker(make_engine(_url(Path(path))), expire_on_commit=False)


def _prepare(path: Path) -> None:
    with _lock:
        if str(path) in _migrated:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        backend = Path(__file__).resolve().parents[1]
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        config.set_main_option("sqlalchemy.url", _url(path))
        command.upgrade(config, "head")
        _migrated.add(str(path))


def _clerk_user(request: Request, settings: Settings) -> str:
    if not settings.clerk_jwt_key:
        raise HTTPException(503, "Sign-in is not configured yet.")
    parties = [value.strip() for value in settings.clerk_authorized_parties.split(",") if value.strip()]
    jwt_key = settings.clerk_jwt_key.strip().strip('"').replace("\\n", "\n")
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            jwt_key=jwt_key,
            authorized_parties=parties,
            accepts_token=["session_token"],
        ),
    )
    if not state.is_signed_in or not state.payload or not state.payload.get("sub"):
        raise HTTPException(401, "Please sign in again.")
    return str(state.payload["sub"])


def workspace_session(request: Request, settings: Settings):
    authorization = request.headers.get("Authorization", "")
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Invalid sign-in token.")
        identity = _clerk_user(request, settings)
        kind = "users"
        request.state.workspace_mode = "account"
    else:
        identity = request.cookies.get(COOKIE, "")
        if not TOKEN.fullmatch(identity):
            raise HTTPException(401, "Choose Try demo or sign in to continue.")
        kind = "demos"
        request.state.workspace_mode = "demo"
    path = _path(settings, kind, identity)
    if kind == "demos" and not path.exists():
        raise HTTPException(401, "This demo has expired. Start a fresh demo.")
    _prepare(path)
    if kind == "demos":
        path.touch()
    return _factory(str(path))


def _cleanup_demos(settings: Settings) -> None:
    directory = _root(settings) / "demos"
    if not directory.exists():
        return
    cutoff = time.time() - GUEST_DAYS * 86400
    for path in directory.glob("*.db"):
        if path.stat().st_mtime < cutoff:
            # Only old, unvisited workspaces are removed. SQLite sidecars are kept together.
            for target in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
                target.unlink(missing_ok=True)


def _template(settings: Settings) -> Path:
    """Build one dated sample plan, then copy it for each visitor."""
    from app.services import demo

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    path = _root(settings) / "templates" / f"{day}.db"
    with _lock:
        if path.exists():
            return path
        _prepare(path)
        with _factory(str(path)).begin() as db:
            demo.populate(db, settings.model_copy(update={"ai_mode": "demo"}))
        return path


def warm_demo(settings: Settings) -> None:
    if settings.workspace_root:
        _template(settings)


def start_demo(request: Request, response: Response, settings: Settings) -> dict:
    existing = request.cookies.get(COOKIE, "")
    if TOKEN.fullmatch(existing) and _path(settings, "demos", existing).exists():
        return {"mode": "demo"}
    # The Pages proxy supplies the real client IP. A separate Railway-origin request cannot
    # reach this route when the proxy shared secret is configured.
    visitor = request.headers.get("CF-Connecting-IP") or request.client.host or "unknown"
    now = time.monotonic()
    with _lock:
        attempts = _demo_attempts[visitor]
        while attempts and attempts[0] < now - 3600:
            attempts.popleft()
        if len(attempts) >= 24:
            raise HTTPException(429, "Too many demos started. Please try again later.")
        attempts.append(now)
        _cleanup_demos(settings)
    token = secrets.token_urlsafe(32)
    path = _path(settings, "demos", token)
    template = _template(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(template) as source, sqlite3.connect(path) as target:
        source.backup(target)
    with _lock:
        _migrated.add(str(path))
    response.set_cookie(
        COOKIE, token, max_age=GUEST_DAYS * 86400, path="/api", secure=request.url.scheme == "https",
        httponly=True, samesite="lax",
    )
    return {"mode": "demo"}
