"""Offscreen smoke tests for the smart laptop pad build (no network/OAuth/display)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

passed = failed = 0


def check(name, fn):
    global passed, failed
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    else:
        passed += 1
        print(f"ok   {name}")


def _echo(x):
    return f"got:{x}"


def test_registry_roundtrip():
    from agentic_workspace.tools import Tool, ToolRegistry

    reg = ToolRegistry()
    reg.register(Tool("echo", "echo", {"type": "object"}, _echo))
    assert reg.call("echo", {"x": 1}) == "got:1"


def test_gated_confirmation_flow_real_gmail_send():
    """Use the REAL gmail_send: first call raises NeedsConfirmation with the
    full draft; the confirmed re-call must reach gmail_send with _confirmed=True
    (it then reports missing credentials instead of looping)."""
    from agentic_workspace.tools import NeedsConfirmation, Tool, ToolRegistry
    from agentic_workspace.tools.gmail import gmail_send

    reg = ToolRegistry()
    reg.register(
        Tool("gmail_send", "Send an email", {"type": "object"}, gmail_send, gated=True)
    )

    draft = {"to": "a@example.com", "subject": "Hi", "body": "hello"}
    try:
        reg.call("gmail_send", draft)
    except NeedsConfirmation as nc:
        assert nc.tool_name == "gmail_send"
        assert nc.draft["to"] == "a@example.com"
        assert nc.draft["body"] == "hello"
    else:
        raise AssertionError("first call must raise NeedsConfirmation")

    # Confirmed re-call: flag must propagate into gmail_send (the bug made it
    # raise NeedsConfirmation a second time). Without credentials it returns
    # the credential-setup error instead of looping or sending.
    result = reg.call("gmail_send", {**draft, "_confirmed": True})
    assert isinstance(result, str), f"unexpected: {result!r}"
    assert any(
        w in result.lower() for w in ("credential", "client", "not connected")
    ), result
    assert "Sent email" not in result  # nothing was actually sent


def test_notes_roundtrip():
    import agentic_workspace.tools.notes as notes_mod
    from agentic_workspace.tools.notes import save_note, search_notes

    db = os.path.join(os.path.dirname(__file__), "smoke_test_tmp.db")
    notes_mod.DB_PATH = db
    try:
        save_note("Test note", "canvas annotation about circles")
        hits = search_notes("circles")
        assert "circles" in hits
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_config_and_imports():
    from agentic_workspace import config

    assert config.REPO_ROOT.exists()
    from agentic_workspace import agent, ai, canvas, screen, tools, ui, voice  # noqa: F401


def test_main_window_offscreen():
    from PySide6.QtWidgets import QApplication
    from agentic_workspace.app import MainWindow
    from agentic_workspace.config import load_config

    app = QApplication.instance() or QApplication([])
    w = MainWindow(load_config())
    w.show()
    assert w.windowTitle()
    w.close()


if __name__ == "__main__":
    for name, fn in sorted(
        {k: v for k, v in globals().items() if k.startswith("test_")}.items()
    ):
        check(name, fn)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
