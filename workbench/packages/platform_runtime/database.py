"""One owned connection per context; no ambient connection, pool or session singleton."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from packages.platform_runtime.configuration import required


@contextmanager
def transaction(
    worker: bool = False,
    *,
    lookup: Callable[[str], str] = required,
    connector: Callable[..., Any] | None = None,
) -> Iterator[Any]:
    # Resolve configuration and open only on context entry, matching the old API.
    key = "WORKER_DATABASE_DSN" if worker else "API_DATABASE_DSN"
    connect = psycopg.connect if connector is None else connector
    with connect(lookup(key), row_factory=dict_row) as connection:
        connection.execute("SET LOCAL search_path=design,public")
        yield connection
