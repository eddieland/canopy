"""The limits and trust settings the settings page edits in the workspace's private config (DESIGN §12, §22, M41).

Only the keys `GET /config` lists, within their bounds, and trust settings only toward stricter (TRUST_MODEL T8). A
save writes the private file alone, keeping its comments, and then asks the loop to read its config again, as Reload
does.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.core import config, conversation
from canopy.infra import logs
from canopy.serve import config_edit
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError
from canopy.serve.schema import ConfigChange, ConfigKey, ConfigPatch, ConfigReload, ConfigSaved, ConfigSettings

TAG = "config"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/config", operation_id="getConfig", summary="Get the settings the web UI edits", responses=REFUSED)
def read_config(backend: BackendDep) -> ConfigSettings:
    """Each key the settings page edits: its value as the files say now, which file it comes from, and its bound.

    Files that do not load are refused `config_invalid`, naming the file.
    """
    with backend.open() as ctx:
        root, repos = ctx.repo_root, sorted(r.name for r in ctx.ws.repos)
    try:
        found = config_edit.read(root, backend.user_file)
    except config.ConfigError as e:
        raise RefusedError(conversation.Refused(config_edit.CONFIG_INVALID, str(e))) from None
    return ConfigSettings(
        keys=[
            ConfigKey(
                name=s.key.name,
                value=_shown(s.value),
                source=s.source,
                kind=s.key.kind,
                bound=s.key.bound,
                looser=s.key.looser,
            )
            for s in found.settings
        ],
        private_file=str(found.private_file),
        user_file=str(found.user_file),
        workspace_file=str(found.workspace_file),
        hash=found.hash,
        repos=repos,
        every=backend.every,
    )


@router.patch("/config", operation_id="saveConfig", summary="Change settings in the private config", responses=REFUSED)
def save_config(body: ConfigPatch, backend: BackendDep) -> ConfigSaved:
    """Write the changes to the workspace's private file, then ask the loop to read its config again, as Reload does.

    Refused, writing nothing: `inside_run`; `not_editable` for a key `GET /config` does not list; `past_bound` for a
    limit loosened past its bound; `not_stricter` for a trust setting loosened; `stale` when the file changed since
    `hash` was read; `unsafe_file` for a private file that is a symlink or not the operator's; `config_invalid` with
    the loader's message.
    """
    with backend.open() as ctx:
        root = ctx.repo_root
    try:
        saved = config_edit.save(root, backend.user_file, body.hash, body.changes)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    for change in saved.changes:
        _log.info(
            "config changed",
            extra={"channel": WEB, "key": change.name, "old": _shown(change.old), "new": _shown(change.new)},
        )
    reload, refused = None, None
    if saved.changes:
        with backend.open() as ctx:
            try:
                found = backend.reload(ctx)
            except config.ConfigError as e:
                refused = str(e)
            else:
                reload = ConfigReload(
                    changed=list(found.changed),
                    restart=list(found.restart),
                    after_tick=found.after_tick,
                )
        _log.info("config reload asked for", extra={"channel": WEB, "refused": refused})
    return ConfigSaved(
        changed=[ConfigChange(name=c.name, old=_shown(c.old), new=_shown(c.new)) for c in saved.changes],
        hash=saved.hash,
        reload=reload,
        reload_refused=refused,
        every=backend.every,
    )


def _shown(value: config_edit.Value) -> int | bool | str | list[str] | dict[str, int] | None:
    return list(value) if isinstance(value, tuple) else value
