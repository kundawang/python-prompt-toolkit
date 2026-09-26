from __future__ import annotations

import asyncio
import time

from prompt_toolkit.application import Application
from prompt_toolkit.input import DummyInput, create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts import PromptSession


def test_application_run_inputhook_does_not_use_global_event_loop(monkeypatch):
    """
    `Application.run(inputhook=...)` creates its own loop and must not install
    or query a global event loop.
    """
    app = Application(input=DummyInput(), output=DummyOutput())

    def inputhook(context):
        pass

    def get_event_loop():
        raise AssertionError("get_event_loop() should not be called")

    def set_event_loop(loop):
        raise AssertionError("set_event_loop() should not be called")

    monkeypatch.setattr(asyncio, "get_event_loop", get_event_loop)
    monkeypatch.setattr(asyncio, "set_event_loop", set_event_loop)

    result = app.run(
        pre_run=lambda: app.exit(result="done"),
        handle_sigint=False,
        inputhook=inputhook,
    )

    assert result == "done"


def test_prompt_session_inputhook(monkeypatch):
    """
    An inputhook passed to `PromptSession` is used when the prompt runs,
    without binding an event loop during initialization.
    """
    contexts = []

    def get_event_loop():
        raise AssertionError("get_event_loop() should not be called")

    def set_event_loop(loop):
        raise AssertionError("set_event_loop() should not be called")

    monkeypatch.setattr(asyncio, "get_event_loop", get_event_loop)
    monkeypatch.setattr(asyncio, "set_event_loop", set_event_loop)

    with create_pipe_input() as inp:
        input_sent = False

        def inputhook(context):
            nonlocal input_sent
            contexts.append(context)

            if not input_sent:
                inp.send_text("hello\r")
                input_sent = True

            # Wait until the selector running in the other thread is ready.
            deadline = time.monotonic() + 5
            while not context.input_is_ready():
                if time.monotonic() > deadline:
                    raise TimeoutError("Input was not ready in time.")
                time.sleep(0.001)

        session = PromptSession(
            input=inp,
            output=DummyOutput(),
            inputhook=inputhook,
        )

        assert session.prompt(handle_sigint=False) == "hello"

    assert contexts


def test_prompt_inputhook_overrides_session_inputhook(monkeypatch):
    def session_inputhook(context):
        pass

    def prompt_inputhook(context):
        pass

    session = PromptSession(
        input=DummyInput(),
        output=DummyOutput(),
        inputhook=session_inputhook,
    )
    run_calls = []

    def run(**kwargs):
        run_calls.append(kwargs)
        return "done"

    monkeypatch.setattr(session.app, "run", run)

    assert session.prompt(inputhook=prompt_inputhook) == "done"
    assert run_calls[0]["inputhook"] is prompt_inputhook
