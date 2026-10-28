import sys
from pathlib import Path
from typing import Final

import pytest

from canopy.infra import lock
from canopy.infra.procs import SubprocessRunner

# Try the lock from another process, the way a second `canopy tick` would.
TRY_LOCK: Final = """
import sys
from pathlib import Path
from canopy.infra import lock
try:
    with lock.hold(Path(sys.argv[1])):
        print("acquired")
except lock.LockBusyError:
    print("busy")
"""


def try_from_other_process(tmp_path: Path, path: Path) -> str:
    script = tmp_path / "try_lock.py"
    script.write_text(TRY_LOCK)
    result = SubprocessRunner().run([sys.executable, str(script), str(path)])
    assert result.ok, result.stderr
    return result.stdout.strip()


def test_second_holder_is_refused_and_lock_is_reusable(tmp_path: Path) -> None:
    path = tmp_path / "state" / "lock"
    with lock.hold(path):
        with pytest.raises(lock.LockBusyError), lock.hold(path):
            pass
        assert path.read_text().strip().isdigit()
    with lock.hold(path):
        pass


def test_other_process_is_refused_while_held(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    with lock.hold(path):
        assert try_from_other_process(tmp_path, path) == "busy"
    assert try_from_other_process(tmp_path, path) == "acquired"
