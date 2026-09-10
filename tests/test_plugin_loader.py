import sys
import os
import textwrap
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.loader import PluginLoader


def _write_plugin(directory, filename, contents):
    with open(os.path.join(directory, filename), "w") as f:
        f.write(textwrap.dedent(contents))


def test_loads_plugins_with_collect_function():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "hello.py", """
            PLUGIN_NAME = "hello"
            def collect():
                return {"greeting": "hi"}
        """)
        loader = PluginLoader(d)
        assert "hello" in loader.collectors
        assert loader.run_collector("hello") == {"greeting": "hi"}


def test_skips_files_without_collect():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "no_collect.py", "X = 1\n")
        loader = PluginLoader(d)
        assert "no_collect" not in loader.collectors


def test_does_not_load_itself_as_a_plugin():
    with tempfile.TemporaryDirectory() as d:
        # loader.py alongside user plugins in the same directory shouldn't
        # be scanned as a plugin, even if copied in for some reason.
        _write_plugin(d, "loader.py", "def collect():\n    return {}\n")
        _write_plugin(d, "real_plugin.py", "def collect():\n    return {'ok': True}\n")
        loader = PluginLoader(d)
        assert "loader" not in loader.collectors
        assert "real_plugin" in loader.collectors


def test_plugin_exception_is_captured_not_raised():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "broken.py", """
            def collect():
                raise ValueError("boom")
        """)
        loader = PluginLoader(d)
        result = loader.run_collector("broken")
        assert "error" in result
        assert "boom" in result["error"]


def test_interval_caches_result_between_runs():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "counter.py", """
            PLUGIN_INTERVAL = 3600
            _calls = {"n": 0}
            def collect():
                _calls["n"] += 1
                return {"calls": _calls["n"]}
        """)
        loader = PluginLoader(d)
        first = loader.run_collector("counter")
        second = loader.run_collector("counter")  # should be cached, not re-run
        assert first == {"calls": 1}
        assert second == {"calls": 1}


def test_force_bypasses_interval_cache():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "counter.py", """
            PLUGIN_INTERVAL = 3600
            _calls = {"n": 0}
            def collect():
                _calls["n"] += 1
                return {"calls": _calls["n"]}
        """)
        loader = PluginLoader(d)
        loader.run_collector("counter")
        forced = loader.run_collector("counter", force=True)
        assert forced == {"calls": 2}


def test_no_interval_runs_every_time_backward_compat():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "always.py", """
            _calls = {"n": 0}
            def collect():
                _calls["n"] += 1
                return {"calls": _calls["n"]}
        """)
        loader = PluginLoader(d)
        r1 = loader.run_collector("always")
        r2 = loader.run_collector("always")
        assert r1 == {"calls": 1}
        assert r2 == {"calls": 2}


def test_reload_picks_up_new_plugin():
    with tempfile.TemporaryDirectory() as d:
        _write_plugin(d, "a.py", "def collect():\n    return {}\n")
        loader = PluginLoader(d)
        assert set(loader.collectors.keys()) == {"a"}

        _write_plugin(d, "b.py", "def collect():\n    return {}\n")
        loader.reload()
        assert set(loader.collectors.keys()) == {"a", "b"}
