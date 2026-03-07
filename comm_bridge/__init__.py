"""comm_bridge package init

This file makes `comm_bridge` an explicit package so type checkers
and import resolution treat modules under it as `comm_bridge.*`.
"""

__all__ = ["client", "server"]
