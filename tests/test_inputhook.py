"""
Tests for the inputhook support.

The inputhook is passed as a parameter to `Application.run()` /
`PromptSession`. The event loop with the hook installed is only created when
the application runs; nothing is bound at import or initialization time.
"""

from __future__ import annotations

import asyncio
import threading
import time

from prompt_toolkit.application import Application
from prompt_toolkit.eventloop.inputhook import (
    InputHook,
    InputHookContext,
    InputHookSelector,
    new_eventloop_with_inputhook,
)
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts import PromptSession


def _polling_inputhook(called: list[InputHookContext]) -> InputHook:
    """
    Return an inputhook that records its invocations and returns as soon as
    input is ready.
    """

    def inputhook(context: InputHookContext) -> None:
        called.append(context)
        while not context.input_is_ready():
            time.sleep(0.001)

    return inputhook


def test_new_eventloop_with_inputhook() -> None:
    """
    The inputhook should be called whenever the event loop is idle.
    """
    called: list[InputHookContext] = []
    loop = new_eventloop_with_inputhook(_polling_inputhook(called))
    try:
        assert isinstance(loop._selector, InputHookSelector)  # type: ignore[attr-defined]

        future: asyncio.Future[None] = loop.create_future()
        loop.call_later(0.05, loop.call_soon_threadsafe, future.set_result, None)
        loop.run_until_complete(future)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

    assert called


def test_application_run_with_inputhook() -> None:
    """
    `Application.run(inputhook=...)` runs the application in a fresh event
    loop that has the inputhook installed.
    """
    called: list[InputHookContext] = []

    with create_pipe_input() as inp:
        app: Application[None] = Application(
            layout=Layout(Window(FormattedTextControl("Hello"))),
            input=inp,
            output=DummyOutput(),
        )

        def pre_run() -> None:
            # Schedule the application to exit shortly after starting, so
            # that the event loop gets a chance to idle (and call the
            # inputhook).
            loop = asyncio.get_running_loop()
            loop.call_later(0.05, app.exit)

        app.run(pre_run=pre_run, inputhook=_polling_inputhook(called))

    assert called


def _prompt_with_delayed_input(
    prompt_inputhook: InputHook | None,
    session_inputhook: InputHook | None = None,
) -> str:
    """
    Run a prompt, feeding it input from another thread after a short delay,
    so that the event loop is guaranteed to idle (and call the inputhook).
    """
    with create_pipe_input() as inp:

        def send_text() -> None:
            time.sleep(0.1)
            inp.send_text("hello\r")

        thread = threading.Thread(target=send_text)
        thread.start()
        try:
            session: PromptSession[str] = PromptSession(
                input=inp,
                output=DummyOutput(),
                inputhook=session_inputhook,
            )
            return session.prompt(inputhook=prompt_inputhook)
        finally:
            thread.join()


def test_prompt_session_inputhook_from_constructor() -> None:
    """
    An inputhook passed to the `PromptSession` constructor is used when
    prompting.
    """
    called: list[InputHookContext] = []

    result = _prompt_with_delayed_input(
        prompt_inputhook=None,
        session_inputhook=_polling_inputhook(called),
    )

    assert result == "hello"
    assert called


def test_prompt_session_inputhook_argument_overrides_constructor() -> None:
    """
    An inputhook passed to `prompt()` takes precedence over the one from the
    `PromptSession` constructor.
    """
    from_constructor: list[InputHookContext] = []
    from_prompt: list[InputHookContext] = []

    result = _prompt_with_delayed_input(
        prompt_inputhook=_polling_inputhook(from_prompt),
        session_inputhook=_polling_inputhook(from_constructor),
    )

    assert result == "hello"
    assert from_prompt
    assert not from_constructor


def test_inputhook_does_not_bind_event_loop() -> None:
    """
    Neither creating a `PromptSession` with an inputhook, nor running it,
    may install an event loop in the current thread. (This is what broke
    when `asyncio.get_event_loop()` was deprecated.)
    """
    errors: list[str] = []

    def assert_no_event_loop(what: str) -> None:
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            pass  # No loop installed, as expected.
        else:
            errors.append(f"Event loop installed {what}.")

    def run() -> None:
        assert_no_event_loop("before creating the session")

        called: list[InputHookContext] = []
        result = _prompt_with_delayed_input(
            prompt_inputhook=None,
            session_inputhook=_polling_inputhook(called),
        )

        assert result == "hello"
        assert called
        assert_no_event_loop("at initialization or while running the prompt")

    # Use a fresh thread, so that no event loop is installed yet.
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    assert not errors
