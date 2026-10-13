"""Builds the web UI into canopy's wheel (D079), so an installed canopy never needs Node.

The wheel carries ui/dist as `canopy/_data/ui`, where canopy.infra.resources finds it. When npm is on PATH and node
meets ui/package.json's `engines.node` floor, the hook builds it first (`npm ci` if ui/node_modules is missing, then
`npm run build`). Without a usable npm it bundles an existing ui/dist, or builds the wheel with no UI and warns: the
server then answers every page with "not built". An older node counts as no npm, so an operator whose PATH has one
still gets canopy, without the UI, rather than a failed install.
CANOPY_UI_REQUIRED=1 turns that warning into an error; CI and the release build set it. Editable installs skip all
of this: they read ui/dist from the checkout.
"""

from __future__ import annotations

import json
import os
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
        """Run before the wheel is assembled."""
        if self.target_name != "wheel" or version == "editable":
            return
        ui = Path(self.root) / "ui"
        index = ui / "dist" / "index.html"
        npm, why = _usable_npm(ui / "package.json")
        if npm is not None:
            if not (ui / "node_modules").is_dir():
                subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=ui, check=True)
            subprocess.run([npm, "run", "build"], cwd=ui, check=True)
        if index.is_file():
            build_data["force_include"][str(ui / "dist")] = "canopy/_data/ui"
            return
        message = f"canopy: building the wheel without the web UI ({why} and ui/dist not built)"
        if os.environ.get("CANOPY_UI_REQUIRED") == "1":
            raise RuntimeError(message + "; CANOPY_UI_REQUIRED=1")
        self.app.display_warning(message)


def _usable_npm(package_json: Path) -> tuple[str | None, str]:
    """Return npm's path if it can build the UI, else None and why not."""
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None or not package_json.is_file():
        return None, "npm not found"
    floor = re.fullmatch(r">=\s*(\d+)(?:\.(\d+))?", json.loads(package_json.read_text())["engines"]["node"].strip())
    if floor is None:
        return npm, ""
    found = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    have = tuple(int(part) for part in re.findall(r"\d+", found)[:2])
    need = (int(floor[1]), int(floor[2] or 0))
    if have < need:
        return None, f"node {found} is older than the {need[0]}.{need[1]} the UI needs"
    return npm, ""
