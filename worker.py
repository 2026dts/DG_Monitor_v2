"""
DG background worker v2.
- Reads all Modbus registers every POLL_INTERVAL seconds
- Writes full telemetry to PostgreSQL
- Publishes ONLY genset_state + fuel_level_pct to ThingsBoard
- Tracks run sessions (start/stop) for runtime-hours and cost KPIs
- Evaluates all 6 alarm rules after each poll
"""

import logging
import time
from datetime import datetime, timezone

import state
import db_store
import alarm_engine
import tb_mqtt
from config import POLL_INTERVAL
import modbus_link
from register_map import is_generator_running

logger = logging.getLogger(__name__)


def dg_worker():
    MAX_RETRIES = 3
    _was_running = False   # tracks generator on/off state across poll cycles

    while True:
        connected, message = modbus_link.connect_modbus()

        if not connected:
            with state.state_lock:
                state.dg_state["connected"] = False
                state.dg_state["error"] = message
                state.dg_state["last_attempt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error("[DG] %s", message)
            time.sleep(POLL_INTERVAL)
            continue

        logger.info("[DG] %s", message)
        consecutive_failures = 0

        try:
            while True:
                results, _ = modbus_link.read_all_parameters()
                values = modbus_link.extract_live_values(results)

                if not values:
                    consecutive_failures += 1
                    logger.warning("[DG] No data (fail %d/%d)", consecutive_failures, MAX_RETRIES)
                    if consecutive_failures >= MAX_RETRIES:
                        logger.error("[DG] Communication lost — triggering reconnect")
                        break
                    time.sleep(POLL_INTERVAL)
                    continue

                consecutive_failures = 0

                genset_state = values.get("Genset state")
                engine_speed = values.get("Average engine speed")
                is_running = is_generator_running(genset_state, engine_speed)

                # Build display cards
                cards = {}
                for row in results:
                    cards[row["name"]] = (
                        f"{row['scaled']} {row['unit']}".strip()
                        if row["status"] == "OK"
                        else "Read error"
                    )

                ts_now = datetime.now(timezone.utc)
                ts_str = ts_now.strftime("%Y-%m-%d %H:%M:%S")

                # Update in-memory state (Flask API reads this)
                with state.state_lock:
                    state.dg_state.update({
                        "connected":    True,
                        "error":        None,
                        "cards":        cards,
                        "results":      results,
                        "values":       values,
                        "is_running":   is_running,
                        "last_update":  ts_str,
                        "last_attempt": ts_str,
                    })

                # ── Runtime session tracking ──────────────────────────────
                if is_running and not _was_running:
                    # Generator just started
                    db_store.open_run_session(values.get("Fuel level"), ts_now)
                    db_store.clear_alarm("genset_stopped")
                    logger.info("[DG] Generator START detected — session opened")

                elif not is_running and _was_running:
                    # Generator just stopped
                    db_store.close_run_session(values.get("Fuel level"), ts_now)
                    alarm_engine.trigger_genset_stop_event(values)
                    logger.info("[DG] Generator STOP detected — session closed & alert triggered")

                _was_running = is_running

                # ── Persist full telemetry to Postgres ────────────────────
                db_store.insert_telemetry(values, is_running, ts_now)

                # ── Publish selective to ThingsBoard ────────────────────────
                tb_mqtt.publish_selective(values)


                # ── Evaluate alarm rules ───────────────────────────────────
                alarm_engine.evaluate(values)

                logger.debug(
                    "[DG] %s | Fuel:%.0f%% | Freq:%.2fHz | kW:%.1f",
                    "RUNNING" if is_running else "STOPPED",
                    values.get("Fuel level") or 0,
                    values.get("Frequency") or 0,
                    values.get("Total kW") or 0,
                )

                time.sleep(POLL_INTERVAL)

        except Exception as exc:
            with state.state_lock:
                state.dg_state["connected"] = False
                state.dg_state["error"] = f"{type(exc).__name__}: {exc}"
                state.dg_state["last_attempt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error("[DG] Exception: %s", exc)

        finally:
            modbus_link.close_connection()
            time.sleep(POLL_INTERVAL)
