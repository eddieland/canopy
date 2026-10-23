"""The web UI's server for `canopy loop`: uvicorn in a thread, restarted with a backoff, never ending the loop (D073).

uvicorn installs signal handlers only on the main thread, so in this one it installs none and the loop's own handle
Ctrl-C (DESIGN §6). It logs nothing to the terminal, where the loop draws its output: its warnings and errors go to
canopy's log. `stop` sets uvicorn's `should_exit`, which ends the server within `GRACEFUL_SECONDS` even with streams
open: uvicorn cancels each request still open then, and logs its `CancelledError` as an exception, which reaches
canopy's log as a line at INFO, since the server stopping as asked is no error.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, override

import uvicorn

if TYPE_CHECKING:
    from fastapi import FastAPI

    from canopy.infra import logs
    from canopy.serve.options import ServeOptions

FIRST_RETRY_SECONDS = 1.0
MAX_RETRY_SECONDS = 60.0
# A server that ran this long before it failed starts its backoff over.
HEALTHY_SECONDS = 60.0
GRACEFUL_SECONDS = 2
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
#: What uvicorn cancels a request still open with, once `GRACEFUL_SECONDS` pass. A `CancelledError` without it, in
#: itself or in the cancels it was raised while handling, such as one the app raises itself, is logged as uvicorn logs
#: it; so is this one, if uvicorn ever words it otherwise.
_SHUTDOWN_CANCEL = "Task cancelled, timeout graceful shutdown exceeded"


class _ToCanopyLog(logging.Handler):
    """Hands uvicorn's records to canopy's logger, so they reach canopy.log and never the terminal."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        error = record.exc_info[1] if record.exc_info is not None else None
        if _is_shutdown_cancel(error):
            record = _cancelled(record)
        logging.getLogger("canopy").handle(record)


class WebServer:
    """One server, run in a daemon thread from `start` until `stop`."""

    def __init__(
        self,
        app: FastAPI,
        options: ServeOptions,
        log: logs.TickAdapter,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Serve `app` as `options` say, logging to `log`."""
        self._app = app
        self._options = options
        self._log = log
        self._clock = clock
        self._stopping = threading.Event()
        self._server: uvicorn.Server | None = None
        self._thread = threading.Thread(target=self._run, name="canopy-web", daemon=True)

    @property
    def started(self) -> bool:
        """Whether the server is accepting connections now."""
        server = self._server
        return server is not None and server.started

    def start(self) -> None:
        """Start serving in the thread."""
        uvicorn_log = logging.getLogger("uvicorn")
        if not any(isinstance(h, _ToCanopyLog) for h in uvicorn_log.handlers):
            uvicorn_log.addHandler(_ToCanopyLog())
        uvicorn_log.propagate = False
        uvicorn_log.setLevel(logging.WARNING)
        self._thread.start()

    def stop(self, timeout: float = GRACEFUL_SECONDS + 3) -> None:
        """Stop serving, and wait up to `timeout` seconds for the thread to end."""
        self._stopping.set()
        server = self._server
        if server is not None:
            server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        delay = FIRST_RETRY_SECONDS
        while not self._stopping.is_set():
            config = uvicorn.Config(
                self._app,
                host=self._options.host,
                port=self._options.port,
                log_config=None,
                access_log=False,
                timeout_graceful_shutdown=GRACEFUL_SECONDS,
            )
            server = uvicorn.Server(config)
            self._server = server
            if self._stopping.is_set():
                return
            began = self._clock()
            try:
                server.run()
            # uvicorn exits with SystemExit when it cannot bind; anything else is a crash. Neither ends the loop.
            except (Exception, SystemExit) as e:  # noqa: BLE001  (logged, and the server restarted)
                self._log.error("web UI server failed", extra={"error": f"{type(e).__name__}: {e}"})
            else:
                if self._stopping.is_set():
                    return
                self._log.error("web UI server stopped on its own")
            if self._clock() - began >= HEALTHY_SECONDS:
                delay = FIRST_RETRY_SECONDS
            self._log.info("web UI server restarting", extra={"after_seconds": delay})
            self._stopping.wait(delay)
            delay = min(delay * 2, MAX_RETRY_SECONDS)


def _is_shutdown_cancel(error: BaseException | None) -> bool:
    # uvicorn's cancel can land while the anyio task group in FastAPI's event stream waits on its children, and the
    # group then raises a bare `CancelledError` of its own, with uvicorn's only as its context (#1347).
    seen: set[int] = set()
    while isinstance(error, asyncio.CancelledError) and id(error) not in seen:
        if error.args == (_SHUTDOWN_CANCEL,):
            return True
        seen.add(id(error))
        error = error.__context__
    return False


def _cancelled(record: logging.LogRecord) -> logging.LogRecord:
    # One line at INFO, without the traceback, which says only where the request was waiting.
    fields = {"levelno": logging.INFO, "levelname": "INFO", "args": (), "exc_info": None, "exc_text": None}
    return logging.makeLogRecord({**vars(record), **fields, "msg": "web UI request cancelled as the server stopped"})
