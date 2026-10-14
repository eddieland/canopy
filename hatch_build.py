"""Builds the web UI into canopy's wheel (D079), so an installed canopy always has it.

The wheel carries ui/dist as `canopy/_data/ui`, where canopy.infra.resources finds it. When npm is on PATH and node
meets ui/package.json's `engines.node` floor, the hook builds it first (`npm ci` if ui/node_modules is missing, then
`npm run build`). Without a usable npm it bundles an existing ui/dist, and fails the build if there is none: a wheel
without the UI is never built. So an install from git needs Node. Editable installs skip all of this: they read ui/dist
from the checkout.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class UIBuildHook(BuildHookInterface):
    """Build ui/ with npm and force-include the result in the wheel."""

    PLUGIN_NAME = "canopy-ui"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Run before the wheel is assembled.

        Raises:
            RuntimeError: ui/dist/index.html is missing after the build, or with no usable npm to build it.
        """
        if self.target_name != "wheel" or version == "editable":
            return
        ui = Path(self.root) / "ui"
        index = ui / "dist" / "index.html"
        engines = json.loads((ui / "package.json").read_text())["engines"]["node"]
        npm, why = _usable_npm(engines)
        if npm is not None:
            if not (ui / "node_modules").is_dir():
                subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=ui, check=True)
            subprocess.run([npm, "run", "build"], cwd=ui, check=True)
        if not index.is_file():
            msg = (
                f"canopy: cannot build the web UI: {why}. Install node {engines} (with nvm: `nvm install 22`) and"
                " retry."
            )
            raise RuntimeError(msg)
        build_data["force_include"][str(ui / "dist")] = "canopy/_data/ui"


def _usable_npm(engines: str) -> tuple[str | None, str]:
    """Return npm's path if its node meets `engines` (package.json's engines.node), else None and why not."""
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        return None, "npm or node is not on PATH"
    floor = re.fullmatch(r">=\s*(\d+)(?:\.(\d+))?", engines.strip())
    if floor is None:
        return npm, ""
    found = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    have = tuple(int(part) for part in re.findall(r"\d+", found)[:2])
    need = (int(floor[1]), int(floor[2] or 0))
    if have < need:
        return None, f"node {found} is older than the {need[0]}.{need[1]} it needs"
    return npm, ""
