import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from triggers.engine import TriggerEngine


def test_basic_fire_and_recover():
    te = TriggerEngine([{
        "name": "cpu", "key": "cpu", "operator": ">", "threshold": 90,
        "severity": "high", "message": "cpu {value}",
    }])

    fired = te.evaluate({"cpu": 95})
    assert len(fired) == 1
    assert fired[0]["status"] == "problem"

    # Still above threshold -> no duplicate alert
    assert te.evaluate({"cpu": 96}) == []

    recovered = te.evaluate({"cpu": 50})
    assert len(recovered) == 1
    assert recovered[0]["status"] == "recovery"


def test_missing_key_is_ignored():
    te = TriggerEngine([{"name": "x", "key": "does.not.exist", "operator": ">", "threshold": 1}])
    assert te.evaluate({"system": {}}) == []


def test_unknown_operator_is_ignored_not_raised():
    te = TriggerEngine([{"name": "x", "key": "v", "operator": "~=", "threshold": 1}])
    assert te.evaluate({"v": 5}) == []


def test_duration_delays_firing():
    te = TriggerEngine([{
        "name": "sustained", "key": "cpu", "operator": ">", "threshold": 90, "for": 5,
    }])

    # First sample over threshold: shouldn't fire immediately.
    assert te.evaluate({"cpu": 95}) == []

    # Simulate 6 seconds having passed without a dip.
    te.state["sustained"]["pending_since"] -= 6
    fired = te.evaluate({"cpu": 95})
    assert len(fired) == 1
    assert fired[0]["held_for_seconds"] >= 5


def test_duration_resets_on_dip():
    te = TriggerEngine([{
        "name": "sustained", "key": "cpu", "operator": ">", "threshold": 90, "for": 5,
    }])
    assert te.evaluate({"cpu": 95}) == []
    te.state["sustained"]["pending_since"] -= 6
    # A dip below threshold before the next evaluate() call should reset
    # the pending timer instead of carrying it over.
    assert te.evaluate({"cpu": 10}) == []
    assert te.evaluate({"cpu": 95}) == []  # starts counting again, not fired yet


def test_hysteresis_prevents_flapping():
    te = TriggerEngine([{
        "name": "cpu_hyst", "key": "cpu", "operator": ">",
        "threshold": 90, "recovery_threshold": 80,
    }])

    assert len(te.evaluate({"cpu": 95})) == 1          # fires
    assert te.evaluate({"cpu": 85}) == []               # in the dead zone: no recovery
    recovered = te.evaluate({"cpu": 75})                # below recovery_threshold: recovers
    assert len(recovered) == 1
    assert recovered[0]["status"] == "recovery"


def test_hysteresis_for_less_than_operator():
    # e.g. "free disk % < 10 is bad", recovers only once back above 15.
    te = TriggerEngine([{
        "name": "low_disk", "key": "free_pct", "operator": "<",
        "threshold": 10, "recovery_threshold": 15,
    }])
    assert len(te.evaluate({"free_pct": 5})) == 1
    assert te.evaluate({"free_pct": 12}) == []          # dead zone, stays "firing"
    recovered = te.evaluate({"free_pct": 20})
    assert len(recovered) == 1


def test_message_formatting():
    te = TriggerEngine([{
        "name": "x", "key": "v", "operator": ">", "threshold": 10,
        "message": "value is {value}, limit {threshold}",
    }])
    fired = te.evaluate({"v": 42})
    assert fired[0]["message"] == "value is 42.0, limit 10"
