import time
import logging
import operator

logger = logging.getLogger(__name__)

OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

# For each comparison operator, the direction a "recovery_threshold" must
# move relative to "threshold" to actually add hysteresis instead of
# accidentally making the trigger fire earlier.
_RECOVERY_MUST_BE_LOOSER = {
    # ">"/">=" fire on high values, so recovery must require dropping to a
    # point at or below the fire threshold (rec <= thr) to add real hysteresis.
    ">": lambda thr, rec: rec <= thr,
    ">=": lambda thr, rec: rec <= thr,
    # "<"/"<=" fire on low values, so recovery must require rising to a
    # point at or above the fire threshold (rec >= thr).
    "<": lambda thr, rec: rec >= thr,
    "<=": lambda thr, rec: rec >= thr,
    "==": lambda thr, rec: True,
    "!=": lambda thr, rec: True,
}


def _get_nested_value(data, key_path):
    keys = key_path.split(".")
    value = data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list):
            try:
                value = value[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value


class TriggerEngine:
    """Evaluates configured triggers against a metrics payload.

    Supports two features beyond a plain threshold comparison:

    - `for`: number of seconds the condition must hold continuously before
      an alert actually fires. Prevents a single noisy sample from paging
      someone. Example: cpu > 90 "for" 60 seconds.
    - `recovery_threshold`: a separate, looser threshold used to decide
      when a firing trigger recovers. Prevents "flapping" when a metric
      hovers right at the edge of `threshold`. If omitted, `threshold` is
      used for both directions (original behavior).
    """

    def __init__(self, trigger_configs=None):
        if trigger_configs is None:
            trigger_configs = []
        self.triggers = trigger_configs
        self.state = {}
        self._validate_triggers()

    def _validate_triggers(self):
        for trigger in self.triggers:
            name = trigger.get("name", "unnamed")
            op_str = trigger.get("operator", ">")
            threshold = trigger.get("threshold", 0)
            recovery_threshold = trigger.get("recovery_threshold")
            if recovery_threshold is None:
                continue
            check = _RECOVERY_MUST_BE_LOOSER.get(op_str)
            if check and not check(threshold, recovery_threshold):
                logger.warning(
                    f"Trigger '{name}': recovery_threshold ({recovery_threshold}) does not "
                    f"loosen threshold ({threshold}) for operator '{op_str}'; this trigger "
                    f"may flap. Recovery should be on the opposite side of the fire threshold."
                )

    def evaluate(self, metrics):
        alerts = []
        now = time.time()

        for trigger in self.triggers:
            name = trigger.get("name", "unnamed")
            key_path = trigger.get("key", "")
            op_str = trigger.get("operator", ">")
            threshold = trigger.get("threshold", 0)
            recovery_threshold = trigger.get("recovery_threshold", threshold)
            severity = trigger.get("severity", "warning")
            message_template = trigger.get("message", f"{name} triggered")
            hold_seconds = trigger.get("for", 0)

            value = _get_nested_value(metrics, key_path)
            if value is None:
                continue

            try:
                value = float(value)
            except (TypeError, ValueError):
                continue

            op_func = OPERATORS.get(op_str)
            if op_func is None:
                logger.warning(f"Unknown operator '{op_str}' in trigger '{name}'")
                continue

            condition_met = op_func(value, threshold)

            st = self.state.setdefault(name, {
                "firing": False,
                "pending_since": None,
            })

            if condition_met:
                if st["pending_since"] is None:
                    st["pending_since"] = now
                held_for = now - st["pending_since"]

                if not st["firing"] and held_for >= hold_seconds:
                    st["firing"] = True
                    alert = {
                        "trigger_name": name,
                        "severity": severity,
                        "message": message_template.format(value=value, threshold=threshold),
                        "key": key_path,
                        "value": value,
                        "operator": op_str,
                        "threshold": threshold,
                        "held_for_seconds": round(held_for, 1),
                        "status": "problem",
                    }
                    alerts.append(alert)
                    logger.warning(f"TRIGGER FIRED: {name} ({severity}): {alert['message']}")
            else:
                st["pending_since"] = None
                # Only emit a recovery event if it was actually firing before,
                # and the value has crossed back past recovery_threshold.
                recovered = st["firing"] and not op_func(value, recovery_threshold)
                if recovered:
                    st["firing"] = False
                    recovery = {
                        "trigger_name": name,
                        "severity": severity,
                        "message": f"RECOVERY: {name} - value {value} is now within threshold",
                        "key": key_path,
                        "value": value,
                        "operator": op_str,
                        "threshold": threshold,
                        "status": "recovery",
                    }
                    alerts.append(recovery)
                    logger.info(f"TRIGGER RECOVERED: {name}")

        return alerts
