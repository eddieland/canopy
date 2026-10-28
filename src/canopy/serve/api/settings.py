"""The limits and trust settings the settings page edits in the workspace's private config (DESIGN §12, §22, M41).

Only the keys `GET /config` lists, within their bounds, and trust settings only toward stricter (TRUST_MODEL T8). A
save writes the private file alone, keeping its comments, and then asks the loop to read its config again, as Reload
does. Each agent's and chore's model the page shows and never changes: the operator chooses them in the file alone.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Final

from fastapi import APIRouter

from canopy.core import agent_models, chore_view, config, conversation
from canopy.infra import logs
from canopy.serve import config_edit
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError
from canopy.serve.schema import ConfigChange, ConfigKey, ConfigPatch, ConfigReload, ConfigSaved, ConfigSettings
from canopy.serve.schema.model import ChoreModel, ConfigModels, ConfiguredModel

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.runtime.agents import Model

TAG: Final = "config"
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


@router.get("/config/models", operation_id="getConfigModels", summary="Get each agent's and chore's model")
def read_models(backend: BackendDep) -> ConfigModels:
    """The model config chooses for each of canopy's agents and each chore, as the loop runs on it, read only.

    Each file named is the one its tables come from as the files say now, so the page can say where to edit them.
    """
    with backend.open() as ctx:
        cfg, ws, root = ctx.config, ctx.ws, ctx.repo_root
    origin: dict[str, Path] = {}
    # A file that cannot be read now names none; the models are still those the loop runs on.
    with contextlib.suppress(config.ConfigError):
        origin = config.origins(root, backend.user_file)
    agents = [
        ConfiguredModel(
            agent=role,
            model=_id(chosen.model),
            variant=_variant(chosen.model),
            source="config" if chosen.model is not None else "default",
        )
        for role, chosen in agent_models.configured(cfg).items()
    ]
    chores = [
        ChoreModel(
            chore=name,
            model=_id(chosen.model),
            variant=_variant(chosen.model),
            source=chosen.source,
            agent=chosen.agent,
        )
        for name, chosen in ((n, agent_models.of_chore(cfg, c)) for n, c in chore_view.defined(cfg, ws).items())
    ]
    return ConfigModels(
        agents=agents,
        chores=chores,
        models_file=_named(origin.get("runtime.models")),
        chores_file=_named(origin.get("chores")),
        user_file=str(backend.user_file),
        private_file=str(config.private_config_path(root)),
    )


def _id(model: Model | None) -> str | None:
    return model.id if model is not None else None


def _variant(model: Model | None) -> str | None:
    return model.variant if model is not None else None


def _named(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _shown(value: config_edit.Value) -> int | bool | str | list[str] | list[int] | dict[str, int] | None:
    if not isinstance(value, tuple):
        return value
    # A list of names, or the budget's alerts, a list of percentages.
    numbers = [v for v in value if isinstance(v, int)]
    return numbers if len(numbers) == len(value) else [str(v) for v in value]
