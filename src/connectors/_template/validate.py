"""Source-specific gates, run after the shared ones in ``Connector.validate``."""

from __future__ import annotations

import pandas as pd

from src.connectors.gates import GateResult


def domain_gates(df: pd.DataFrame) -> list[GateResult]:
    """Example: a published value must sit inside its own published interval."""
    present = df.dropna(subset=["value", "moe_or_ci_low", "moe_or_ci_high"])
    outside = ~present["value"].between(present["moe_or_ci_low"], present["moe_or_ci_high"])
    count = int(outside.sum())
    return [
        GateResult(
            "value_within_interval",
            count == 0,
            f"{count} value(s) fall outside their own interval" if count else "",
        )
    ]
