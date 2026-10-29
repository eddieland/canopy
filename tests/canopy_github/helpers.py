"""What the tests of canopy's GitHub programs share: a local stand-in's server, and the reader run in process."""

import contextlib
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from canopy_github import Hosts, connect

from canopy.infra import procs
from tests.conftest import invoke


@contextlib.contextmanager
def serving(handler: type[BaseHTTPRequestHandler]) -> Generator[str]:
    """Serve `handler` on a local port until the block ends. Yields its URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/graphql"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@dataclass(frozen=True)
class InProcess:
    """A runner that runs the reader in this process against the stand-in at `url`, as canopy would run it."""

    url: str

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
        on_line: Callable[[str], None] | None = None,
        stdout_to_file: bool = False,
    ) -> procs.Result:
        del cwd, env, timeout, on_start, stdout_to_file
        assert args[0] == "canopy-connect-github"
        result = invoke(connect.main, args[1:], stdin=stdin or "", obj=Hosts(lambda _: self.url, lambda _: "t"))
        for line in result.stdout.splitlines(keepends=True):
            if on_line is not None:
                on_line(line)
        return procs.Result(tuple(args), result.exit_code, result.stdout, result.stderr)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        raise AssertionError(f"a connector is run, never spawned: {args}, {cwd}, {log_path}")
