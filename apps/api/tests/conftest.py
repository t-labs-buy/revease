"""Isolate API tests onto a temp SQLite DB + media dir BEFORE any app import, so
tests never touch (or depend on the schema of) the local dev database."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="refract-api-test-")
os.environ["REFRACT_DATA_DIR"] = _tmp
os.environ["REFRACT_MEDIA_DIR"] = os.path.join(_tmp, "media")
os.environ["REFRACT_DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite3"
os.environ["REFRACT_ADMIN_EMAILS"] = "admin@example.com"  # bootstrap admin for test_roles

from app.db import init_db  # noqa: E402

init_db()
