import os
import sys
import time
import importlib
import importlib.util
import logging
import inspect

logger = logging.getLogger(__name__)


class PluginLoader:
    def __init__(self, plugins_dir=None):
        self.plugins_dir = plugins_dir
        self.collectors = {}
        # per-plugin runtime state: last_run, last_result, last_error, last_duration_ms
        self._state = {}
        if plugins_dir:
            self._load_plugins()

    def _load_plugins(self):
        if not os.path.isdir(self.plugins_dir):
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")
            return

        for filename in sorted(os.listdir(self.plugins_dir)):
            if filename.startswith("_") or not filename.endswith(".py"):
                continue
            if filename == "loader.py":
                # The loader itself commonly lives alongside user plugins in
                # the same directory; don't try to load it as one.
                continue

            module_name = filename[:-3]
            filepath = os.path.join(self.plugins_dir, filename)

            try:
                spec = importlib.util.spec_from_file_location(f"plugins.{module_name}", filepath)
                module = importlib.util.module_from_spec(spec)
                sys.modules[f"plugins.{module_name}"] = module
                spec.loader.exec_module(module)

                if hasattr(module, "collect"):
                    collector_func = module.collect
                    sig = inspect.signature(collector_func)
                    name = getattr(module, "PLUGIN_NAME", module_name)
                    self.collectors[name] = {
                        "func": collector_func,
                        "interval": getattr(module, "PLUGIN_INTERVAL", None),
                        "description": getattr(module, "PLUGIN_DESCRIPTION", ""),
                        "params": list(sig.parameters.keys()),
                    }
                    self._state[name] = {
                        "last_run": 0,
                        "last_result": None,
                        "last_error": None,
                        "last_duration_ms": None,
                    }
                    logger.info(f"Loaded plugin: {name}")
                else:
                    logger.warning(f"Plugin {module_name} has no collect() function")
            except Exception as e:
                logger.error(f"Failed to load plugin {module_name}: {e}")

    def reload(self):
        """Re-scan the plugins directory, picking up new/changed/removed plugins."""
        logger.info("Reloading plugins...")
        self.collectors = {}
        self._state = {}
        self._load_plugins()

    def run_collector(self, name, force=False, **kwargs):
        if name not in self.collectors:
            logger.warning(f"Plugin '{name}' not found")
            return None

        info = self.collectors[name]
        state = self._state[name]
        interval = info.get("interval")

        now = time.time()
        if not force and interval and (now - state["last_run"]) < interval:
            # Not due yet; return the cached value so callers can still see
            # the last known result without re-running expensive collectors.
            return state["last_result"]

        start = time.monotonic()
        try:
            result = info["func"](**kwargs)
            state["last_result"] = result
            state["last_error"] = None
        except Exception as e:
            logger.error(f"Plugin '{name}' execution failed: {e}")
            result = {"error": str(e)}
            state["last_result"] = result
            state["last_error"] = str(e)
        finally:
            state["last_run"] = now
            state["last_duration_ms"] = round((time.monotonic() - start) * 1000, 2)

        return result

    def run_all(self):
        results = {}
        for name in self.collectors:
            value = self.run_collector(name)
            if value is not None:
                results[name] = value
        return results

    def list_plugins(self):
        return {
            name: {
                "description": info["description"],
                "interval": info["interval"],
                "params": info["params"],
                "last_run": self._state[name]["last_run"],
                "last_error": self._state[name]["last_error"],
                "last_duration_ms": self._state[name]["last_duration_ms"],
            }
            for name, info in self.collectors.items()
        }
