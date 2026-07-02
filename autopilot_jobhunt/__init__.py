try:
    from .agent import app, root_agent
except ModuleNotFoundError:  # pragma: no cover - allows tests without google-adk installed
    app = None
    root_agent = None

__all__ = ["app", "root_agent"]
