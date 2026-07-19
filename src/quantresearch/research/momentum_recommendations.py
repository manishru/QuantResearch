"""Pure selection rules for completed-session momentum recommendations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "12M>9M>6M>3M>0": (("ret252", "ret189"), ("ret189", "ret126"), ("ret126", "ret63"), ("ret63", "zero")),
    "12M>6M>3M>0": (("ret252", "ret126"), ("ret126", "ret63"), ("ret63", "zero")),
    "12M>9M>6M>3M>0 & 2M>0": (("ret252", "ret189"), ("ret189", "ret126"), ("ret126", "ret63"), ("ret63", "zero"), ("ret42", "zero")),
    "9M>6M>3M>0 & 2M>0": (("ret189", "ret126"), ("ret126", "ret63"), ("ret63", "zero"), ("ret42", "zero")),
    "6M>3M>0 & 2M>0": (("ret126", "ret63"), ("ret63", "zero"), ("ret42", "zero")),
    "5M>2M>0": (("ret105", "ret42"), ("ret42", "zero")),
    "5M>3M>0": (("ret105", "ret63"), ("ret63", "zero")),
    "6M>4M>0": (("ret126", "ret84"), ("ret84", "zero")),
    "4M>2M>0": (("ret84", "ret42"), ("ret42", "zero")),
    "3M>2M>0": (("ret63", "ret42"), ("ret42", "zero")),
    "7M>4M>0": (("ret147", "ret84"), ("ret84", "zero")),
    "8M>5M>0": (("ret168", "ret105"), ("ret105", "zero")),
    "9M>6M>0": (("ret189", "ret126"), ("ret126", "zero")),
}


def qualifies(candidate: dict[str, Any], rule: str) -> bool:
    """Return whether a candidate satisfies every declared momentum condition."""
    if rule not in RULES:
        raise ValueError(f"Unknown momentum rule: {rule}")
    for left_name, right_name in RULES[rule]:
        left = candidate.get(left_name)
        right = 0.0 if right_name == "zero" else candidate.get(right_name)
        if left is None or right is None or float(left) <= float(right):
            return False
    return True


def rank_qualifying(candidates: Iterable[dict[str, Any]], rule: str) -> list[dict[str, Any]]:
    """Filter and rank candidates deterministically by research ranking return."""
    qualified = [dict(candidate) for candidate in candidates if qualifies(candidate, rule)]
    qualified.sort(key=lambda item: (-float(item["ranking_return"]), str(item["ticker"])))
    for rank, candidate in enumerate(qualified, start=1):
        candidate["rank"] = rank
    return qualified
