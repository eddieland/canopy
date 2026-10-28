"""canopy's HTTP client for the programs it ships, against a local server that answers as each test scripts it."""

import contextlib
import json
import re
import ssl
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar, Final, override
from unittest import mock

import canopy_http
import httpx2
import pytest
from canopy_http import (
    Client,
    FailedError,
    NotSentError,
    RateLimitedError,
    RefusedError,
    Retry,
    TimedOutError,
    UntrustedError,
)

#: Set when a `slow` answer may be given: the server holds it until the test that asked for one is done with it.
RELEASED: Final = threading.Event()
#: No pause between tries, so a test that sends again takes no time over it.
QUICK: Final = Retry(pauses=(0.0, 0.0))


@dataclass
class Answer:
    """What the server does with one request: answer `status`, or `cut` its reply off, `drop` it, or answer `slow`.

    A `slow` answer waits until `RELEASED` is set, which `serving` does as it ends.
    """

    status: int = 200
    body: bytes = b'{"ok": true}'
    headers: dict[str, str] = field(default_factory=dict)
    how: str = "answer"


class _Server(BaseHTTPRequestHandler):
    #: The answers to give, in turn; the last is given to every request after it.
    script: ClassVar[list[Answer]] = []
    #: Each request heard: its method, path, and headers.
    heard: ClassVar[list[tuple[str, str, dict[str, str]]]] = []

    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._answer()

    def _answer(self) -> None:
        _Server.heard.append((self.command, self.path, dict(self.headers)))
        answer = _Server.script.pop(0) if len(_Server.script) > 1 else _Server.script[0]
        if answer.how == "drop":
            self.close_connection = True
            return
        if answer.how == "slow":
            RELEASED.wait()
        self.send_response(answer.status)
        for name, value in answer.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(answer.body)))
        self.end_headers()
        if answer.how == "cut":
            self.wfile.write(answer.body[: len(answer.body) // 2])
            self.close_connection = True
            return
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            # A client that gave up on a slow answer has closed its end.
            self.wfile.write(answer.body)

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@contextlib.contextmanager
def serving(*script: Answer) -> Generator[str]:
    """Serve `script` on a local port until the block ends. Yields its origin."""
    _Server.script = list(script)
    _Server.heard = []
    RELEASED.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        RELEASED.set()
        server.shutdown()
        server.server_close()
        thread.join()


def tries() -> int:
    return len(_Server.heard)


def test_a_reply_is_read_whole_and_the_headers_go_with_the_request() -> None:
    with serving(Answer(body=b'{"n": 1}')) as origin:
        got = Client(origin, name="Svc", headers={"Authorization": "bearer t"}).json("POST", "/api", body={"q": 1})
    assert got == {"n": 1}
    method, path, headers = _Server.heard[0]
    assert (method, path, headers["Authorization"], headers["Content-Type"]) == (
        "POST",
        "/api",
        "bearer t",
        "application/json",
    )


def test_a_url_at_another_origin_is_refused_before_anything_is_sent() -> None:
    with serving(Answer()) as origin:
        client = Client(origin, name="Svc", headers={"Authorization": "bearer t"})
        with pytest.raises(ValueError, match="is not at"):
            client.send("GET", "https://elsewhere.example/steal")
    assert tries() == 0


def test_a_redirect_is_refused_and_the_credentials_do_not_follow_it() -> None:
    elsewhere = Answer(status=302, headers={"Location": "http://127.0.0.1:1/x"})
    with serving(elsewhere) as origin, pytest.raises(RefusedError, match="HTTP 302") as refused:
        Client(origin, name="Svc", headers={"Authorization": "bearer t"}).send("GET", "/", again=True)
    assert refused.value.certain
    assert tries() == 1


@pytest.mark.parametrize(
    ("how", "message"),
    [("cut", "without sending complete message body"), ("drop", "Server disconnected")],
)
def test_a_read_whose_connection_breaks_is_sent_again(how: str, message: str) -> None:
    with serving(Answer(how=how), Answer()) as origin:
        assert Client(origin, name="Svc", retry=QUICK).json("GET", "/", again=True) == {"ok": True}
    assert tries() == 2
    with serving(Answer(how=how)) as origin, pytest.raises(FailedError, match=message) as failed:
        Client(origin, name="Svc", retry=QUICK).json("GET", "/", again=True)
    assert not failed.value.certain
    assert tries() == 3


@pytest.mark.parametrize("answer", [Answer(how="cut"), Answer(how="drop"), Answer(status=502, body=b"bad gateway")])
def test_a_write_that_may_have_been_carried_out_is_sent_once(answer: Answer) -> None:
    with serving(answer) as origin, pytest.raises(FailedError) as failed:
        Client(origin, name="Svc", retry=QUICK).send("POST", "/", body={"text": "hi"})
    assert not failed.value.certain
    assert tries() == 1


def test_a_server_error_is_quoted_and_an_error_page_named() -> None:
    with (
        serving(Answer(status=503, body=b"down for a bit")) as origin,
        pytest.raises(FailedError, match="HTTP 503: down"),
    ):
        Client(origin, name="Svc", retry=QUICK).send("GET", "/", again=True)
    assert tries() == 3
    page = Answer(status=502, body=b"<html>unicorn</html>", headers={"Content-Type": "text/html"})
    with serving(page) as origin, pytest.raises(FailedError, match=r"HTTP 502: Svc's error page$"):
        Client(origin, name="Svc", retry=QUICK).send("GET", "/", again=True)


def test_a_reply_that_is_not_json_is_a_failed_try() -> None:
    page = Answer(body=b"<html>oops</html>", headers={"Content-Type": "text/html"})
    with serving(page, Answer()) as origin:
        assert Client(origin, name="Svc", retry=QUICK).json("GET", "/", again=True) == {"ok": True}
    with serving(page) as origin, pytest.raises(FailedError, match="Svc's reply is not JSON: Svc's error page"):
        Client(origin, name="Svc", retry=QUICK).json("GET", "/")
    assert tries() == 1


def test_a_request_that_never_left_is_sent_again_even_a_write() -> None:
    with serving(Answer()) as origin:
        pass
    with (
        mock.patch.object(canopy_http.time, "sleep", autospec=True) as slept,
        pytest.raises(NotSentError, match=f"cannot reach {origin}") as failed,
    ):
        Client(origin, name="Svc").send("POST", "/", body={"text": "hi"})
    assert failed.value.certain
    assert [c.args for c in slept.call_args_list] == [(1.0,), (3.0,)]


@pytest.mark.parametrize(
    "limit",
    [Answer(status=429, headers={"Retry-After": "2"}), Answer(status=403, headers={"Retry-After": "2"})],
)
def test_a_rate_limit_is_waited_out_even_for_a_write(limit: Answer) -> None:
    with (
        serving(limit, Answer()) as origin,
        mock.patch.object(canopy_http.time, "sleep", autospec=True) as slept,
    ):
        Client(origin, name="Svc").send("POST", "/", body={"text": "hi"})
    assert [c.args for c in slept.call_args_list] == [(2.0,)]
    assert tries() == 2


def test_a_rate_limit_that_names_a_date_waits_until_it() -> None:
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    with (
        serving(Answer(status=429, headers={"Retry-After": when}), Answer()) as origin,
        mock.patch.object(canopy_http.time, "sleep", autospec=True) as slept,
    ):
        Client(origin, name="Svc", retry=Retry(longest_wait=60.0)).send("GET", "/")
    assert 25.0 < slept.call_args.args[0] <= 30.0


def test_a_rate_limit_that_asks_too_long_a_wait_is_the_refusal_it_is() -> None:
    with (
        serving(Answer(status=429, headers={"Retry-After": "3600"})) as origin,
        pytest.raises(RateLimitedError, match="HTTP 429") as limited,
    ):
        Client(origin, name="Svc", retry=QUICK).send("GET", "/", again=True)
    assert limited.value.certain
    assert limited.value.wait == 3600.0
    assert tries() == 1


def test_a_refusal_is_not_sent_again() -> None:
    with (
        serving(Answer(status=403, body=b"no")) as origin,
        pytest.raises(RefusedError, match="HTTP 403: no") as refused,
    ):
        Client(origin, name="Svc", retry=QUICK).send("GET", "/", again=True)
    assert not isinstance(refused.value, RateLimitedError)
    assert refused.value.status == 403
    assert tries() == 1


def test_a_request_that_times_out_is_not_sent_again() -> None:
    with (
        mock.patch.object(canopy_http, "TIMEOUT_SECONDS", 0.1),
        serving(Answer(how="slow")) as origin,
        pytest.raises(TimedOutError, match="Svc did not answer in time") as failed,
    ):
        Client(origin, name="Svc", retry=QUICK).send("GET", "/", again=True)
    assert not failed.value.certain
    assert tries() == 1


def test_an_origin_must_be_an_http_url() -> None:
    with pytest.raises(ValueError, match="is not an http or https URL"):
        Client("ftp://example.com", name="Svc")
    assert json.dumps(Client("https://example.com/api/graphql", name="Svc").origin) == '"https://example.com"'


def test_a_certificate_that_is_not_trusted_is_not_sent_again() -> None:
    def untrusted(*args: object, **kwargs: object) -> httpx2.Response:
        del args, kwargs
        try:
            raise ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate")
        except ssl.SSLError as e:
            raise httpx2.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]") from e

    with (
        mock.patch.object(httpx2.Client, "send", autospec=True, side_effect=untrusted) as sent,
        mock.patch.object(canopy_http.time, "sleep", autospec=True) as slept,
        pytest.raises(
            UntrustedError,
            match=re.escape("https://ghe.example.com's certificate is not trusted"),
        ) as failed,
    ):
        Client("https://ghe.example.com", name="Svc").send("GET", "/", again=True)
    assert failed.value.certain
    assert sent.call_count == 1
    assert not slept.called
