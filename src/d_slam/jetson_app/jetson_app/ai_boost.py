"""Global AI Boost entry point for the Jetson/d_slam package.

The validated deterministic Stage 3/4 algorithms remain authoritative. AI is
an advisory layer and must never fabricate unobserved rescue-map space.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, TypeVar

T = TypeVar("T")


class AiBoostModel(Protocol):
    def advise(self, operation: str, context: Mapping[str, Any]) -> Any: ...


def ai_boost(
    operation: str,
    deterministic: Callable[[], T],
    *,
    enabled: bool = False,
    model: AiBoostModel | None = None,
    context: Mapping[str, Any] | None = None,
) -> T:
    """Run a safety-preserving d_slam AI Boost operation.

    ``enabled=False`` is a deterministic pass-through. A future model can inspect
    context, but cannot replace the authoritative observed/prior/unknown result.
    """

    result = deterministic()
    if not enabled or model is None:
        return result
    try:
        model.advise(str(operation), dict(context or {}))
    except Exception:
        return result
    return result


__all__ = ["AiBoostModel", "ai_boost"]
