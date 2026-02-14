"""
Claude Code Proxy - Entry Point

Minimal entry point that imports the app from the api module.
Run with: uv run uvicorn server:app --host 0.0.0.0 --port 8082
"""

from api.app import app, create_app

__all__ = ["app", "create_app"]

if __name__ == "__main__":
    import uvicorn
    from config.settings import get_settings
    from cli.process_registry import kill_all_best_effort

    settings = get_settings()
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="debug")
    finally:
        # Safety net for Ctrl+C cases where lifespan shutdown doesn't fully run.
        kill_all_best_effort()
