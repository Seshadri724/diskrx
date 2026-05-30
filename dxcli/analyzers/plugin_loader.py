import importlib.util
import logging
import os
import sys
import hashlib
from typing import List

from .base import AnalyzerPlugin

logger = logging.getLogger(__name__)

# Maximum number of plugins that will be loaded in a single invocation.
# Guards against runaway plugin directories.
MAX_PLUGINS = 20


def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def load_allowlist(allowlist_path: str) -> dict:
    allowlist = {}
    if not os.path.exists(allowlist_path):
        return allowlist
    try:
        with open(allowlist_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    sha256, filename = parts
                    allowlist[sha256.lower().strip()] = filename.strip()
    except OSError as e:
        logger.warning("Could not read allowlist: %s", e)
    return allowlist


class PluginLoader:
    """
    Loads custom analyzers from the local filesystem.

    Plugin execution is opt-in — this class must only be instantiated when
    the user has explicitly passed --enable-plugins.

    Safety:
    - os.makedirs is deferred to load_plugins() — constructing this class
      does NOT create any directories.
    - Plugin module names are scoped to avoid polluting sys.modules globally.
    - Errors in individual plugins are isolated; they do not crash the host.
    - At most MAX_PLUGINS plugins are loaded.
    """

    def __init__(self, plugin_dir: str = None):
        self.plugin_dir = plugin_dir or os.path.expanduser("~/.dx/plugins")
        # Do NOT create the directory here — defer to load_plugins()

    def load_plugins(self) -> List[AnalyzerPlugin]:
        """Load and instantiate plugins from the plugin directory.

        Returns an empty list if the directory doesn't exist or no valid
        plugins are found. Never raises.
        """
        if not os.path.exists(self.plugin_dir):
            # Create it lazily so the user sees an empty dir to place plugins in
            try:
                os.makedirs(self.plugin_dir, mode=0o700, exist_ok=True)
            except OSError as e:
                logger.warning("Could not create plugin directory %s: %s", self.plugin_dir, e)
            return []

        # Load allowlist
        from ..state import get_state_dir
        allowlist_path = os.path.join(get_state_dir(), "plugins.allowlist")
        allowlist = load_allowlist(allowlist_path)

        plugins: List[AnalyzerPlugin] = []
        py_files = [
            f for f in os.listdir(self.plugin_dir)
            if f.endswith(".py") and f != "__init__.py"
        ]

        if len(py_files) > MAX_PLUGINS:
            logger.warning(
                "Plugin directory contains %d files; only the first %d will be loaded.",
                len(py_files),
                MAX_PLUGINS,
            )
            py_files = py_files[:MAX_PLUGINS]

        for filename in py_files:
            file_path = os.path.join(self.plugin_dir, filename)
            if os.path.islink(file_path):
                logger.warning("Skipping symlinked plugin: %s", file_path)
                continue

            file_sha = compute_sha256(file_path)
            if file_sha not in allowlist or allowlist[file_sha] != filename:
                logger.warning("Skipping untrusted plugin: %s (SHA256: %s)", filename, file_sha)
                print(f"[dxcli] Plugin warning: Skipping untrusted plugin {filename} (not in allowlist).", file=sys.stderr)
                continue

            # Use a namespaced module name to avoid collisions in sys.modules
            module_name = f"_dxcli_plugin_{filename[:-3]}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    logger.warning("Could not create spec for plugin %s — skipping.", filename)
                    continue

                module = importlib.util.module_from_spec(spec)
                # Register temporarily but remove after loading to keep namespace clean
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                finally:
                    # Always clean up the module namespace injection
                    sys.modules.pop(module_name, None)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, AnalyzerPlugin)
                        and attr is not AnalyzerPlugin
                    ):
                        plugins.append(attr())
                        logger.info("Loaded plugin: %s from %s", attr_name, filename)

            except Exception as e:
                # Isolate plugin failures — surface via logger and console, not crash
                logger.warning("Plugin %s failed to load: %s", filename, e)
                # The caller (cli.py) will print this to the user
                print(f"[dxcli] Plugin warning: {filename} failed to load: {e}", file=sys.stderr)

        return plugins

