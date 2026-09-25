"""Copy every row from one database to another (SQLite -> Postgres migration).

    python -m app.dbcopy --source sqlite:///data/refract.sqlite3 \\
                         --target postgresql+psycopg://revease:…@localhost:5432/revease

Creates the schema on the target, then copies tables in foreign-key order in
batches. Refuses to run into a target that already has rows (use --force to
append) so a second run can't silently duplicate data. Stop the API and workers
first so nothing writes to the source mid-copy.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, func, insert, inspect, select

BATCH = 1000


def copy(source_url: str, target_url: str, *, force: bool = False) -> dict[str, int]:
    from app import models  # noqa: F401  (register tables)
    from app.db import Base

    src = create_engine(source_url)
    dst = create_engine(target_url)
    Base.metadata.create_all(bind=dst)
    tables = Base.metadata.sorted_tables  # parents before children

    with dst.connect() as conn:
        nonempty = [t.name for t in tables if conn.execute(select(func.count()).select_from(t)).scalar()]
    if nonempty and not force:
        raise SystemExit(f"target already has rows in {nonempty[:5]} — refusing (use --force to append)")

    # An older source database lacks columns added since (init_db adds them
    # lazily at startup). Copy the columns the source has; the rest take the
    # target's defaults.
    src_insp = inspect(src)
    src_tables = set(src_insp.get_table_names())
    counts: dict[str, int] = {}
    with src.connect() as s, dst.begin() as d:
        for t in tables:
            if t.name not in src_tables:
                counts[t.name] = 0
                continue
            have = {c["name"] for c in src_insp.get_columns(t.name)}
            cols = [c for c in t.columns if c.name in have]
            n = 0
            result = s.execute(select(*cols)).mappings()
            while True:
                rows = result.fetchmany(BATCH)
                if not rows:
                    break
                d.execute(insert(t), [dict(r) for r in rows])
                n += len(rows)
            counts[t.name] = n
    return counts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    counts = copy(a.source, a.target, force=a.force)
    for name, n in counts.items():
        print(f"{name:28s} {n}")
    print(f"copied {sum(counts.values())} rows across {len(counts)} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
