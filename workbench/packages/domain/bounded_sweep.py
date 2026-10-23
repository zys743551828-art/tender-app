"""Bounded, stable sweeps over changing eligible rows in long-running coordinators."""

from dataclasses import dataclass, field
from typing import Any

from psycopg import sql


@dataclass
class KeysetSweep:
    """Keep one fixed upper key so new arrivals cannot prevent revisiting older rows.

    Callers supply a server-owned SELECT with a WHERE clause, and a unique,
    immutable ordering key. State belongs to one coordinator loop, not the DB
    transaction. Restarting begins a fresh sweep; no work authority lives here.
    """

    columns: tuple[str, ...]
    after: tuple[Any, ...] | None = field(default=None, init=False)
    through: tuple[Any, ...] | None = field(default=None, init=False)

    def read(self, c, query: sql.Composable, parameters=(), *, limit=100):
        if not self.columns or not 1 <= limit <= 1000:
            raise ValueError("A bounded sweep requires a key and a limit between 1 and 1000")
        columns = sql.SQL(",").join(sql.Identifier(name) for name in self.columns)
        markers = sql.SQL(",").join(sql.Placeholder() for _ in self.columns)
        ascending = sql.SQL(",").join(
            sql.SQL("{} ASC").format(sql.Identifier(name)) for name in self.columns
        )
        descending = sql.SQL(",").join(
            sql.SQL("{} DESC").format(sql.Identifier(name)) for name in self.columns
        )
        if self.through is None:
            upper = c.execute(
                query + sql.SQL(" ORDER BY {} LIMIT 1").format(descending), parameters
            ).fetchone()
            if upper is None:
                return []
            self.through = tuple(upper[name] for name in self.columns)
        bounds = sql.SQL(" AND ({})<=({})").format(columns, markers)
        values = (*parameters, *self.through)
        if self.after is not None:
            bounds += sql.SQL(" AND ({})>({})").format(columns, markers)
            values += self.after
        rows = c.execute(
            query + bounds + sql.SQL(" ORDER BY {} LIMIT %s").format(ascending), (*values, limit)
        ).fetchall()
        self.after = tuple(rows[-1][name] for name in self.columns) if rows else None
        # A removed/ineligible upper row cannot keep a sweep open forever. New
        # lower rows become visible in the next sweep, including eligibility
        # changes that committed after the earlier page was read.
        if len(rows) < limit or self.after == self.through:
            self.after = self.through = None
        return rows
