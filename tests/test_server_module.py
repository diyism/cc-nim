def test_server_module_exports_app_and_create_app():
    import server

    assert server.app is not None
    assert callable(server.create_app)


def test_server_main_invokes_uvicorn_run(monkeypatch):
    import runpy
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import config.settings as settings_mod
    import uvicorn as uvicorn_mod

    # Patch settings used by server.__main__ block.
    old_get_settings = settings_mod.get_settings
    settings_mod.get_settings = lambda: SimpleNamespace(host="127.0.0.1", port=9999)

    old_run = uvicorn_mod.run
    uvicorn_mod.run = MagicMock()

    try:
        runpy.run_module("server", run_name="__main__")
        uvicorn_mod.run.assert_called_once()
        _, kwargs = uvicorn_mod.run.call_args
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 9999
        assert kwargs["log_level"] == "debug"
    finally:
        uvicorn_mod.run = old_run
        settings_mod.get_settings = old_get_settings
