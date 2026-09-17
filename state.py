"""Shared in-memory DG state. Unchanged from v1 structure."""
import threading

state_lock = threading.Lock()

dg_state = {
    "connected":    False,
    "error":        "Waiting for first Modbus poll",
    "cards":        {},
    "results":      [],
    "values":       {},
    "is_running":   False,
    "last_update":  None,
    "last_attempt": None,
}
