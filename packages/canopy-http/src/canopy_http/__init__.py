"""canopy's HTTP client for the programs it ships: the GitHub programs, the Jira connector, and the Slack sink (D130).

Each holds a credential the harness never does (TRUST_MODEL T2) and talks to one service. This is the one way they
talk to it: a client bound to one origin that follows no redirect, so a credential goes nowhere else; the system's
certificates, so an Enterprise host's own CA works; and one account of what went wrong, which says whether the request
may have been carried out, so a caller knows whether sending it again could do it twice.

A request is sent again, after each of `Retry.pauses`, when that cannot do it twice: when it never left, or when the
service refused it and said how long to wait (a 429, or a refusal naming `Retry-After`) for no longer than
`Retry.longest_wait`. A request its caller marks `again`, as a read is, is also sent again when it may have been
carried out: a server error, or a reply that broke off or is not JSON when JSON was asked for. A request that timed out
is never sent again: it has spent its timeout once already, which a connector's run cannot spend many times over.

It honors the environment's proxy (`HTTPS_PROXY`) and certificates (`SSL_CERT_FILE`), as urllib did: an operator
behind a proxy reaches the service through it, which sees the request as it would any other of theirs.

httpx2 for the transport, and nothing from canopy.
"""

from __future__ import annotations

import email.utils
import json
import ssl
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import httpx2

#: How long a request waits on its reply, between reads of it.
TIMEOUT_SECONDS: Final = 30.0
#: How long it waits to connect: a host that has not answered by then is not going to.
CONNECT_SECONDS: Final = 10.0
#: How much of a reply an error quotes.
MAX_QUOTE: Final = 500
#: The refusals that ask for a wait, when they name one: a rate limit, and GitHub's secondary rate limit, a 403.
_WAIT_STATUSES: Final = frozenset({403, 429})
_TOO_MANY: Final = 429
#: How far down the errors one was raised from `_untrusted` looks: httpx2's wraps its transport's, which wraps TLS's.
_MAX_CHAIN: Final = 10


class HttpError(Exception):
    """A request that failed.

    `certain` is whether it is known not to have been carried out: it never left, or the service refused it. A request
    that broke off, timed out, or got a server error may have been carried out.
    """

    def __init__(
        self,
        message: str,
        *,
        certain: bool,
        status: int | None = None,
        wait: float | None = None,
    ) -> None:
        """Make the error; `certain` as the class says, `status` the HTTP status the service answered, if it did.

        `wait` is how long its reply asked to be left before the next try, from its `Retry-After`, if it named one.
        """
        super().__init__(message)
        self.certain = certain
        self.status = status
        self.wait = wait


class RefusedError(HttpError):
    """The service refused it: a 4xx, or a redirect, which is never followed. It is `certain`."""


class RateLimitedError(RefusedError):
    """The service refused it for now: a 429, or a 403 naming `Retry-After`, as GitHub's secondary rate limit is."""


class NotSentError(HttpError):
    """The request never left: no connection could be made to the service. It is `certain`."""


class UntrustedError(HttpError):
    """No connection was made: the service's certificate is not one the system trusts. It is `certain`.

    Sending again would not change that, so it is not sent again.
    """


class FailedError(HttpError):
    """The service may have carried it out: it answered with a server error, or its reply broke off or is not JSON."""


class TimedOutError(HttpError):
    """The service did not answer in time. It may have carried the request out."""


@dataclass(frozen=True)
class Retry:
    """When a request is sent again."""

    #: The pause before each new try: one try, then one more for each pause.
    pauses: Sequence[float] = (1.0, 3.0)
    #: The longest `Retry-After` a refusal may ask for and be waited out; one asking longer is the refusal it is.
    longest_wait: float = 10.0


@dataclass(frozen=True)
class Reply:
    """The service's answer to one request, a 2xx."""

    status: int
    #: The whole reply, decoded, with what is not UTF-8 replaced.
    text: str
    #: Whether it is a web page (HTML), as a service's error pages are: naming one says more than quoting it.
    page: bool


class Client:
    """A service at one origin, with the headers each request carries, its credentials among them.

    A request goes to that origin alone: a URL naming another is refused before it is sent, and a redirect is never
    followed. Each request opens a connection of its own, so one the service closed while idle is never reused.
    """

    def __init__(
        self,
        origin: str,
        *,
        name: str,
        headers: Mapping[str, str] | None = None,
        retry: Retry | None = None,
    ) -> None:
        """Talk to `origin`, a URL whose path is ignored, as `name`, such as `GitHub`, in what errors say.

        Raises:
            ValueError: `origin` is not an http or https URL.
        """
        parts = urllib.parse.urlsplit(origin)
        if parts.scheme not in {"https", "http"} or not parts.netloc:
            raise ValueError(f"{origin!r} is not an http or https URL")
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.name = name
        self._headers = dict(headers or {})
        self._retry = retry or Retry()
        self._ssl: ssl.SSLContext = httpx2.create_ssl_context()

    def send(
        self,
        method: str,
        url: str,
        *,
        body: object = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        again: bool = False,
    ) -> Reply:
        """Send one request to `url`, a path or a URL at the client's origin, with `body` as JSON if it is given.

        `again` is whether it may be sent again though the service may have carried it out, as a read may be.

        Returns:
            The service's 2xx reply.

        Raises:
            ValueError: `url` is at another origin.
            HttpError: The request failed, each time it was sent.
        """
        request = self._request(method, url, body=body, params=params, headers=headers, defaults={})
        return self._retrying(request, again=again, read=lambda reply: reply)

    def json(
        self,
        method: str,
        url: str,
        *,
        body: object = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        again: bool = False,
    ) -> object:
        """Send one request as `send` does, whose reply must be JSON: one that is not fails the try, as a page does.

        Returns:
            The reply, parsed.

        Raises:
            ValueError: `url` is at another origin.
            HttpError: The request failed, or its reply was not JSON, each time it was sent.
        """
        request = self._request(
            method,
            url,
            body=body,
            params=params,
            headers=headers,
            defaults={"Accept": "application/json"},
        )
        return self._retrying(request, again=again, read=self._parse)

    def _retrying[T](self, request: httpx2.Request, *, again: bool, read: Callable[[Reply], T]) -> T:
        """Send `request` and `read` its reply, and again after each pause while what went wrong allows it.

        Returns:
            What `read` makes of the service's 2xx reply.

        Raises:
            HttpError: It failed, or `read` raised one, each time it was sent.
        """
        pauses = list(self._retry.pauses)
        while True:
            try:
                return read(self._once(request))
            except HttpError as e:
                wait = self._wait(e, pauses, again=again)
                if wait is None:
                    raise
                time.sleep(wait)

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: object,
        params: Mapping[str, str] | None,
        headers: Mapping[str, str] | None,
        defaults: Mapping[str, str],
    ) -> httpx2.Request:
        """Build the request, refusing a URL at another origin, so a credential in its headers goes nowhere else.

        Its headers are `defaults`, then the client's, then `headers`, each overriding the one before.

        Returns:
            The request.

        Raises:
            ValueError: `url` is at another origin.
        """
        target = urllib.parse.urljoin(self.origin + "/", url)
        parts = urllib.parse.urlsplit(target)
        if f"{parts.scheme}://{parts.netloc}" != self.origin:
            raise ValueError(f"{url!r} is not at {self.origin}")
        merged = {"User-Agent": "canopy", **defaults, **self._headers, **(headers or {})}
        content = None if body is None else json.dumps(body).encode()
        if content is not None:
            merged.setdefault("Content-Type", "application/json")
        return httpx2.Request(method, target, params=dict(params or {}), headers=merged, content=content)

    def _once(self, request: httpx2.Request) -> Reply:
        """Send `request` once, on a connection of its own.

        Returns:
            The service's 2xx reply.

        Raises:
            RefusedError: It answered with a refusal or a redirect.
            RateLimitedError: It refused it for now, as a rate limit does.
            NotSentError: No connection could be made.
            UntrustedError: The service's certificate is not trusted.
            FailedError: It answered with a server error, or the connection broke before its reply came whole.
            TimedOutError: It did not answer in time.
        """
        timeout = httpx2.Timeout(TIMEOUT_SECONDS, connect=CONNECT_SECONDS)
        try:
            with httpx2.Client(verify=self._ssl, timeout=timeout, follow_redirects=False) as client:
                response = client.send(request)
        except (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.ProxyError) as e:
            if _untrusted(e):
                raise UntrustedError(f"{self.origin}'s certificate is not trusted: {e}", certain=True) from e
            raise NotSentError(f"cannot reach {self.origin}: {e}", certain=True) from e
        except httpx2.TimeoutException as e:
            raise TimedOutError(f"{self.name} did not answer in time: {e!r}", certain=False) from e
        except httpx2.TransportError as e:
            # A reply cut off, a connection reset or closed with no reply, or one that is not HTTP.
            raise FailedError(f"the connection to {self.origin} broke: {e!r}", certain=False) from e
        page = "html" in response.headers.get("Content-Type", "")
        text = response.content.decode(errors="replace")
        if response.is_success:
            return Reply(response.status_code, text, page)
        quote = f"{self.name}'s error page" if page else text[:MAX_QUOTE]
        message = f"HTTP {response.status_code}: {quote}"
        status, wait = response.status_code, _retry_after(response)
        if status >= 500:  # noqa: PLR2004
            # A server error may come after the request was carried out; a refusal comes before.
            raise FailedError(message, certain=False, status=status, wait=wait)
        if status == _TOO_MANY or (status in _WAIT_STATUSES and wait is not None):
            raise RateLimitedError(message, certain=True, status=status, wait=wait)
        raise RefusedError(message, certain=True, status=status)

    def _parse(self, reply: Reply) -> object:
        """`reply` as JSON.

        Returns:
            It, parsed.

        Raises:
            FailedError: It is not JSON, as a service's error page answered with a 200 is not.
        """
        try:
            return json.loads(reply.text)
        except json.JSONDecodeError as e:
            quote = f"{self.name}'s error page" if reply.page else reply.text[:MAX_QUOTE]
            raise FailedError(f"{self.name}'s reply is not JSON: {quote}", certain=False, status=reply.status) from e

    def _wait(self, error: HttpError, pauses: list[float], *, again: bool) -> float | None:
        """How long to wait before sending again after `error`, taking a pause from `pauses`; None to send no more.

        Returns:
            The seconds to wait, or None.
        """
        if not pauses or (error.wait is not None and error.wait > self._retry.longest_wait):
            return None
        # Sent again whatever it asks: it cannot have been carried out. A timeout is never sent again.
        harmless = isinstance(error, NotSentError | RateLimitedError)
        if not harmless and not (again and isinstance(error, FailedError)):
            return None
        return max(pauses.pop(0), error.wait or 0.0)


def _untrusted(error: BaseException) -> bool:
    """Whether `error` came of a certificate the system does not trust, as the TLS error it was raised from says.

    Returns:
        Whether it did.
    """
    seen: BaseException | None = error
    for _ in range(_MAX_CHAIN):
        if seen is None:
            return False
        if isinstance(seen, ssl.SSLCertVerificationError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _retry_after(response: httpx2.Response) -> float | None:
    """The wait a reply's `Retry-After` names, in seconds or as a date; None when it names none.

    Returns:
        The seconds, never below zero, or None.
    """
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)
