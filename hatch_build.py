"""Builds the web UI into canopy's wheel (D079), so an installed canopy never needs Node.

The wheel carries ui/dist as `canopy/_data/ui`, where canopy.infra.resources finds it. When npm is on PATH, the hook
builds it first (`npm ci` if ui/node_modules is missing, then `npm run build`). Without npm it bundles an existing
ui/dist, or builds the wheel with no UI and warns: the server then answers every page with "not built".
CANOPY_UI_REQUIRED=1 turns that warning into an error; CI and the release build set it. Editable installs skip all
of this: they read ui/dist from the checkout.
"""

from __future__ import annotations

import os
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
        npm = shutil.which("npm")
        if npm is not None and (ui / "package.json").is_file():
            if not (ui / "node_modules").is_dir():
                subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=ui, check=True)
            subprocess.run([npm, "run", "build"], cwd=ui, check=True)
        if index.is_file():
            build_data["force_include"][str(ui / "dist")] = "canopy/_data/ui"
            return
        message = "canopy: building the wheel without the web UI (npm not found and ui/dist not built)"
        if os.environ.get("CANOPY_UI_REQUIRED") == "1":
            raise RuntimeError(message + "; CANOPY_UI_REQUIRED=1")
        self.app.display_warning(message)
