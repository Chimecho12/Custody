"""Desktop sidecar public API; implementation is divided by responsibility."""
from .controller import Desktop
from .ipc import stdio
from .operations import AGENT_OPERATIONS, ALLOWED_OPERATIONS, DIRECT_OPERATIONS

__all__ = ["AGENT_OPERATIONS", "ALLOWED_OPERATIONS", "DIRECT_OPERATIONS", "Desktop", "stdio"]
