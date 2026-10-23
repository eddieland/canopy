"""What the tests of the Slack sink and its reader share."""

from pathlib import Path


def token_file(tmp_path: Path, token: str = "xoxb-1-2-secret", mode: int = 0o600) -> Path:  # noqa: S107
    """Write a bot token file under `tmp_path`, with `mode`.

    Returns:
        Its path.
    """
    path = tmp_path / "slack-token"
    path.write_text(token + "\n")
    path.chmod(mode)
    return path
