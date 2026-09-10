import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from remote.commands import RemoteCommandHandler


def test_disallowed_command_is_blocked():
    h = RemoteCommandHandler(allowed_commands=["hostname"])
    result = h.execute("c1", "rm", args=["-rf", "/"])
    assert result["status"] == "error"
    assert "not in the allowed list" in result["stderr"]


def test_path_cannot_bypass_allowlist():
    h = RemoteCommandHandler(allowed_commands=["hostname"])
    # A disallowed command dressed up as a full path should still be blocked
    # since matching is done on the basename either way.
    result = h.execute("c1", "/bin/rm", args=["-rf", "/"])
    assert result["status"] == "error"
    assert "not in the allowed list" in result["stderr"]


def test_allowed_command_runs_via_full_path():
    h = RemoteCommandHandler(allowed_commands=["hostname"])
    result = h.execute("c1", "/usr/bin/hostname")
    # Whether or not /usr/bin/hostname exists on this system, this must not
    # be blocked by the allowlist - it should attempt execution.
    assert result["status"] in ("success", "error")
    assert "not in the allowed list" not in (result.get("stderr") or "")


def test_empty_allowlist_blocks_everything():
    h = RemoteCommandHandler(allowed_commands=[])
    result = h.execute("c1", "hostname")
    assert result["status"] == "error"


def test_allowlist_is_case_insensitive():
    h = RemoteCommandHandler(allowed_commands=["HOSTNAME"])
    result = h.execute("c1", "hostname")
    assert result["status"] != "error" or "not in the allowed list" not in result["stderr"]


def test_rate_limiting_kicks_in():
    h = RemoteCommandHandler(allowed_commands=["hostname"], max_commands_per_minute=2)
    h.execute("c1", "hostname")
    h.execute("c2", "hostname")
    third = h.execute("c3", "hostname")
    assert third["status"] == "rejected"


def test_command_log_is_capped_and_recent():
    h = RemoteCommandHandler(allowed_commands=["hostname"], max_commands_per_minute=1000)
    for i in range(150):
        h.execute(f"c{i}", "hostname")
    assert len(h.command_log) <= 100
    recent = h.get_recent_commands(limit=5)
    assert len(recent) == 5
