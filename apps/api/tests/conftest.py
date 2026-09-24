"""Isolate API tests onto a temp SQLite DB + media dir BEFORE any app import, so
tests never touch (or depend on the schema of) the local dev database."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="refract-api-test-")
os.environ["REFRACT_DATA_DIR"] = _tmp
os.environ["REFRACT_MEDIA_DIR"] = os.path.join(_tmp, "media")
# REFRACT_TEST_DATABASE_URL runs the suite against another database (e.g. a
# throwaway Postgres) to prove dialect compatibility; default is a temp SQLite.
os.environ["REFRACT_DATABASE_URL"] = os.environ.get("REFRACT_TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.sqlite3"
os.environ["REFRACT_ADMIN_EMAILS"] = "admin@example.com"  # bootstrap admin for test_roles
os.environ["REFRACT_USAGE_REPORT_KEY"] = "test-report-key"  # for test_usage
os.environ["REFRACT_AUTH_ALLOWED_EMAIL_DOMAIN"] = ""  # allow mock test domains

from app.db import init_db  # noqa: E402

init_db()
