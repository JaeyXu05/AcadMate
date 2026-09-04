from importlib import import_module
from types import SimpleNamespace


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _statement):
        return None


class _Engine:
    def connect(self):
        return _Connection()


def test_deterministic_mentor_readiness_does_not_require_chat(monkeypatch):
    app_module = import_module("backend.api.app")
    monkeypatch.setattr(app_module, "engine", _Engine())
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: SimpleNamespace(mentor_workflow_model_reasoning_enabled=False),
    )
    monkeypatch.setattr(app_module, "_chat_readiness", lambda: (False, "not_configured"))

    payload = app_module._mentor_readiness_payload()

    assert payload["ready"] is True
    assert payload["mode"] == "deterministic"
    assert payload["dependencies"]["chat_required"] is False
