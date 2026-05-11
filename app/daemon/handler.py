"""
RPC method dispatch and role-based access control.

Method naming: "<domain>.<action>", e.g. "search.submit", "user.list".
Admin-only methods require context["role"] == "admin".
"""
import asyncio
from typing import Any, Callable, Awaitable

# Methods restricted to admin role
_ADMIN_METHODS = {
    "user.list", "user.get", "user.update", "user.delete",
    "gpu.admin_queue",
    "config.reload", "config.get",
    "system.stats",
    "build.delete",
    "cluster.list", "cluster.set_status", "cluster.set_hidden",
}

# Registry: method name → async handler coroutine function
_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}


def register(method: str):
    """Decorator to register an async handler for a method name."""
    def decorator(fn):
        _REGISTRY[method] = fn
        return fn
    return decorator


async def dispatch(message: dict) -> Any:
    """
    Dispatch an incoming RPC message to the appropriate handler.

    Returns a result value (to be wrapped in make_response) or raises
    a HandlerError for known error conditions.
    """
    method = message.get("method", "")
    params = message.get("params", {})
    context = message.get("context", {})

    if method in _ADMIN_METHODS and context.get("role") != "admin":
        raise HandlerError(403, f"Method '{method}' requires admin role")

    handler = _REGISTRY.get(method)
    if handler is None:
        raise HandlerError(404, f"Unknown method: '{method}'")

    return await handler(params, context)


class HandlerError(Exception):
    """Raised by handlers to signal a known error (maps to an error response)."""
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# Import all operation modules so their @register decorators run.
# Done at the bottom to avoid circular imports.
def _load_operations():
    from app.daemon.operations import (  # noqa: F401
        search_ops,
        build_ops,
        dataset_ops,
        auth_ops,
        user_ops,
        gpu_ops,
        config_ops,
        export_import_ops,
        worker_ops,
        cluster_ops,
    )
