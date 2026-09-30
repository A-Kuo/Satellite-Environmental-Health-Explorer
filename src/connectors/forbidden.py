"""Names that must never appear as a column, field or indicator.

The explorer is a descriptive screening tool: signals are never blended into a
single "risk", "priority", "harm" or "inequality" score. This is the single
source of truth; the catalog model, the load gates and the tests all use it, and
migration 001 carries the same list as a CHECK (a test keeps the two in step).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

FORBIDDEN_NAMES: tuple[str, ...] = (
    "risk_score",
    "priority_score",
    "harm_score",
    "inequality_score",
)

_PATTERN = re.compile(
    r"(?<![a-z0-9])(" + "|".join(FORBIDDEN_NAMES) + r")(?![a-z0-9])", re.IGNORECASE
)


def find_forbidden(text: str) -> list[str]:
    """Forbidden names appearing in ``text``, lower-cased and de-duplicated."""
    return sorted({m.group(1).lower() for m in _PATTERN.finditer(text)})


def forbidden_columns(columns: Iterable[str]) -> list[str]:
    """Columns whose name contains a forbidden name."""
    return sorted({c for c in columns if find_forbidden(str(c))})
