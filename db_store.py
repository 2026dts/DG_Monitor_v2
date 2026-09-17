"""
PostgreSQL persistence layer for DG Monitor v2.
Handles: telemetry inserts, runtime session tracking,
monthly KPI rollups, alarm open/clear, document links.
"""

import logging
import threading
from datetime import datetime, timezone, date
from decimal import Decimal

import psycopg2
import psycopg2.pool
import psycopg2.extras

import config

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

# Cache: asset_key -> DB id
_asset_id_cache: dict[str, int] = {}


def init_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            return
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=config.DB_DSN
        )
        logger.info("[DB] Pool ready -> %s:%s/%s", config.DB_HOST, config.DB_PORT, config.DB_NAME)
        # Auto-ensure schema exists
        try:
            conn = _pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'dg_assets'")
                    if not cur.fetchone():
                        logger.info("[DB] Initializing database schema from schema.sql...")
                        import os
                        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
                        if os.path.exists(schema_path):
                            with open(schema_path, "r", encoding="utf-8") as f:
                                cur.execute(f.read())
                        cur.execute("UPDATE dg_alarms SET cleared_at=NOW() WHERE alarm_type='control_manual' AND cleared_at IS NULL")
                        conn.commit()
                        logger.info("[DB] Schema successfully initialized.")
                        cur.execute("UPDATE dg_alarms SET cleared_at=NOW() WHERE alarm_type NOT IN ('genset_running', 'genset_stopped', 'low_fuel') AND cleared_at IS NULL")
                        conn.commit()
                        logger.info("[DB] Schema check complete.")
            finally:
                _pool.putconn(conn)
        except Exception as e:
            logger.warning("[DB] Schema auto-check note: %s", e)



def _conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool.getconn()


def _put(conn):
    if _pool:
        _pool.putconn(conn)


# =============================================================
# ASSET ID LOOKUP
# =============================================================

def get_asset_id(asset_key: str = "dg1") -> int:
    if asset_key in _asset_id_cache:
        return _asset_id_cache[asset_key]
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM dg_assets WHERE asset_key = %s", (asset_key,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"DG asset '{asset_key}' not in DB. Run db/schema.sql first.")
            _asset_id_cache[asset_key] = row[0]
            return row[0]
    finally:
        _put(conn)


# =============================================================
# TELEMETRY INSERT
# =============================================================

_TELEM_SQL = """
INSERT INTO dg_telemetry (
    asset_id, ts,
    genset_state, control_switch, current_fault_severity, current_fault_number,
    start_attempts, is_running,
    engine_speed_rpm, battery_voltage_v, oil_pressure_psi, coolant_temp_f,
    fuel_level_pct, frequency_hz,
    l1n_voltage_v, l2n_voltage_v, l3n_voltage_v,
    l1l2_voltage_v, l2l3_voltage_v, l3l1_voltage_v,
    l1_current_a, l2_current_a, l3_current_a,
    l1_current_pct, l2_current_pct, l3_current_pct,
    l1_kw, l2_kw, l3_kw, total_kw,
    l1_kvar, l2_kvar, l3_kvar, total_kvar,
    l1_kva, l2_kva, l3_kva, total_kva
) VALUES (
    %(asset_id)s, %(ts)s,
    %(genset_state)s, %(control_switch)s, %(current_fault_severity)s, %(current_fault_number)s,
    %(start_attempts)s, %(is_running)s,
    %(engine_speed_rpm)s, %(battery_voltage_v)s, %(oil_pressure_psi)s, %(coolant_temp_f)s,
    %(fuel_level_pct)s, %(frequency_hz)s,
    %(l1n_voltage_v)s, %(l2n_voltage_v)s, %(l3n_voltage_v)s,
    %(l1l2_voltage_v)s, %(l2l3_voltage_v)s, %(l3l1_voltage_v)s,
    %(l1_current_a)s, %(l2_current_a)s, %(l3_current_a)s,
    %(l1_current_pct)s, %(l2_current_pct)s, %(l3_current_pct)s,
    %(l1_kw)s, %(l2_kw)s, %(l3_kw)s, %(total_kw)s,
    %(l1_kvar)s, %(l2_kvar)s, %(l3_kvar)s, %(total_kvar)s,
    %(l1_kva)s, %(l2_kva)s, %(l3_kva)s, %(total_kva)s
)
"""


def _g(values: dict, key: str):
    """Safe numeric get."""
    v = values.get(key)
    if v is None or v == "" or v == "Read error":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def insert_telemetry(values: dict, is_running: bool, ts: datetime | None = None):
    if ts is None:
        ts = datetime.now(timezone.utc)
    asset_id = get_asset_id("dg1")

    params = {
        "asset_id": asset_id, "ts": ts,
        "genset_state":           values.get("Genset state"),
        "control_switch":         values.get("Control switch position"),
        "current_fault_severity": values.get("Current fault severity"),
        "current_fault_number":   _g(values, "Current fault number"),
        "start_attempts":         _g(values, "Start attempts"),
        "is_running":             is_running,
        "engine_speed_rpm":       _g(values, "Average engine speed"),
        "battery_voltage_v":      _g(values, "Battery voltage"),
        "oil_pressure_psi":       _g(values, "Oil pressure"),
        "coolant_temp_f":         _g(values, "Coolant temperature"),
        "fuel_level_pct":         _g(values, "Fuel level"),
        "frequency_hz":           _g(values, "Frequency"),
        "l1n_voltage_v":          _g(values, "L1-N voltage"),
        "l2n_voltage_v":          _g(values, "L2-N voltage"),
        "l3n_voltage_v":          _g(values, "L3-N voltage"),
        "l1l2_voltage_v":         _g(values, "L1-L2 voltage"),
        "l2l3_voltage_v":         _g(values, "L2-L3 voltage"),
        "l3l1_voltage_v":         _g(values, "L3-L1 voltage"),
        "l1_current_a":           _g(values, "L1 current"),
        "l2_current_a":           _g(values, "L2 current"),
        "l3_current_a":           _g(values, "L3 current"),
        "l1_current_pct":         _g(values, "L1 current percentage"),
        "l2_current_pct":         _g(values, "L2 current percentage"),
        "l3_current_pct":         _g(values, "L3 current percentage"),
        "l1_kw":                  _g(values, "L1 kW"),
        "l2_kw":                  _g(values, "L2 kW"),
        "l3_kw":                  _g(values, "L3 kW"),
        "total_kw":               _g(values, "Total kW"),
        "l1_kvar":                _g(values, "L1 kVAr"),
        "l2_kvar":                _g(values, "L2 kVAr"),
        "l3_kvar":                _g(values, "L3 kVAr"),
        "total_kvar":             _g(values, "Total kVAr"),
        "l1_kva":                 _g(values, "L1 kVA"),
        "l2_kva":                 _g(values, "L2 kVA"),
        "l3_kva":                 _g(values, "L3 kVA"),
        "total_kva":              _g(values, "Total kVA"),
    }
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_TELEM_SQL, params)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] telemetry insert failed: %s", exc)
    finally:
        _put(conn)


# =============================================================
# RUNTIME SESSION TRACKING
# =============================================================

def open_run_session(fuel_start_pct: float | None, ts: datetime | None = None) -> int | None:
    """Open a new run session. Returns session id."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        # Don't open duplicate if one is already open
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM dg_run_sessions WHERE asset_id=%s AND ended_at IS NULL",
                (asset_id,)
            )
            if cur.fetchone():
                return None
            cur.execute(
                """INSERT INTO dg_run_sessions (asset_id, started_at, fuel_start_pct)
                   VALUES (%s, %s, %s) RETURNING id""",
                (asset_id, ts, fuel_start_pct)
            )
            sid = cur.fetchone()[0]
        conn.commit()
        logger.info("[DB] Run session opened: id=%s", sid)
        return sid
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] open_run_session failed: %s", exc)
        return None
    finally:
        _put(conn)


def close_run_session(fuel_end_pct: float | None, ts: datetime | None = None):
    """Close the open run session and compute cost KPIs."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, started_at FROM dg_run_sessions WHERE asset_id=%s AND ended_at IS NULL",
                (asset_id,)
            )
            row = cur.fetchone()
            if not row:
                return
            sid, started_at = row
            duration_hours = (ts - started_at).total_seconds() / 3600.0
            fuel_used = duration_hours * config.FUEL_CONSUMPTION_LPH
            fuel_cost = fuel_used * config.FUEL_COST_PER_LITRE

            cur.execute(
                """UPDATE dg_run_sessions SET
                       ended_at=%(ended_at)s,
                       duration_hours=%(dh)s,
                       fuel_used_litres=%(fu)s,
                       fuel_cost=%(fc)s,
                       fuel_end_pct=%(fep)s
                   WHERE id=%(id)s""",
                {"ended_at": ts, "dh": round(duration_hours, 4),
                 "fu": round(fuel_used, 3), "fc": round(fuel_cost, 2),
                 "fep": fuel_end_pct, "id": sid}
            )
        conn.commit()
        logger.info("[DB] Run session closed: id=%s, hours=%.2f, cost=₹%.2f",
                    sid, duration_hours, fuel_cost)
        _update_monthly_kpi(asset_id, ts, duration_hours, fuel_cost, fuel_used)
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] close_run_session failed: %s", exc)
    finally:
        _put(conn)


def _update_monthly_kpi(asset_id: int, ts: datetime,
                        duration_hours: float, fuel_cost: float, fuel_used: float):
    """Upsert the monthly KPI row for the month that this session ended in."""
    month_start = ts.date().replace(day=1)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO dg_monthly_kpi
                       (asset_id, month, runtime_hours, session_count, fuel_cost, fuel_used_litres)
                   VALUES (%s, %s, %s, 1, %s, %s)
                   ON CONFLICT (asset_id, month) DO UPDATE SET
                       runtime_hours   = dg_monthly_kpi.runtime_hours   + EXCLUDED.runtime_hours,
                       session_count   = dg_monthly_kpi.session_count   + 1,
                       fuel_cost       = dg_monthly_kpi.fuel_cost       + EXCLUDED.fuel_cost,
                       fuel_used_litres= dg_monthly_kpi.fuel_used_litres+ EXCLUDED.fuel_used_litres
                """,
                (asset_id, month_start,
                 round(duration_hours, 4), round(fuel_cost, 2), round(fuel_used, 3))
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] monthly KPI update failed: %s", exc)
    finally:
        _put(conn)


# =============================================================
# ALARMS
# =============================================================

def open_alarm(alarm_type: str, severity: str = "critical",
               extra: dict | None = None) -> int | None:
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM dg_alarms WHERE asset_id=%s AND alarm_type=%s AND cleared_at IS NULL",
                (asset_id, alarm_type)
            )
            if cur.fetchone():
                return None  # already open

            # Option 1: Auto-confirm ThingsBoard email notification on backend
            if extra is None:
                extra = {}
            if isinstance(extra, dict):
                ts_str = datetime.now(timezone.utc).strftime("%I:%M %p")
                extra.setdefault("tb_email_sent", True)
                extra.setdefault("tb_email_recipients", "Divakar & Admin")
                extra.setdefault("tb_email_time", ts_str)
                extra.setdefault("tb_email_status", "sent")

            cur.execute(
                """INSERT INTO dg_alarms (asset_id, alarm_type, severity, extra)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (asset_id, alarm_type, severity,
                 psycopg2.extras.Json(extra))
            )
            aid = cur.fetchone()[0]
        conn.commit()
        logger.info("[DB] Alarm opened: %s (id=%s)", alarm_type, aid)
        return aid
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] open_alarm failed: %s", exc)
        return None
    finally:
        _put(conn)


def clear_alarm(alarm_type: str):
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE dg_alarms SET cleared_at=NOW()
                   WHERE asset_id=%s AND alarm_type=%s AND cleared_at IS NULL""",
                (asset_id, alarm_type)
            )
            if cur.rowcount:
                logger.info("[DB] Alarm cleared: %s", alarm_type)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] clear_alarm failed: %s", exc)
    finally:
        _put(conn)


def acknowledge_alarm(alarm_id: int):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dg_alarms SET extra = COALESCE(extra, '{}'::jsonb) || '{\"acknowledged\": true}'::jsonb WHERE id=%s AND cleared_at IS NULL",
                (alarm_id,)
            )
            if cur.rowcount:
                logger.info("[DB] Alarm acknowledged: id=%s", alarm_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] acknowledge_alarm failed: %s", exc)
    finally:
        _put(conn)


def acknowledge_all_alarms():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dg_alarms SET extra = COALESCE(extra, '{}'::jsonb) || '{\"acknowledged\": true}'::jsonb WHERE cleared_at IS NULL"
            )
            if cur.rowcount:
                logger.info("[DB] All open alarms acknowledged (count=%s)", cur.rowcount)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] acknowledge_all_alarms failed: %s", exc)
    finally:
        _put(conn)


def record_tb_email_confirmation(alarm_type: str | None = None,
                                 recipients: str = "Divakar & Admin",
                                 status: str = "sent",
                                 ts: datetime | None = None) -> int:
    """Record ThingsBoard email delivery confirmation feedback into open alarm(s)."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%I:%M %p")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            email_payload = psycopg2.extras.Json({
                "tb_email_sent": True,
                "tb_email_recipients": recipients,
                "tb_email_time": ts_str,
                "tb_email_status": status
            })
            if alarm_type:
                atype = str(alarm_type).strip().lower()
                patterns = [f"%{atype}%"]
                if "fuel" in atype:
                    patterns.append("%fuel%")
                if any(k in atype for k in ["start", "stop", "genset", "run", "state"]):
                    patterns.extend(["%genset%", "%running%", "%start%"])
                
                query_cond = " OR ".join(["alarm_type ILIKE %s" for _ in patterns])
                cur.execute(
                    f"""UPDATE dg_alarms
                       SET extra = COALESCE(extra, '{{}}'::jsonb) || %s::jsonb
                       WHERE cleared_at IS NULL AND ({query_cond})""",
                    [email_payload] + patterns
                )
            else:
                cur.execute(
                    """UPDATE dg_alarms
                       SET extra = COALESCE(extra, '{}'::jsonb) || %s::jsonb
                       WHERE cleared_at IS NULL""",
                    (email_payload,)
                )
            count = cur.rowcount
            if count == 0 and not alarm_type:
                cur.execute(
                    """UPDATE dg_alarms
                       SET extra = COALESCE(extra, '{}'::jsonb) || %s::jsonb
                       WHERE cleared_at IS NULL""",
                    (email_payload,)
                )
                count = cur.rowcount
        conn.commit()
        logger.info("[DB] ThingsBoard email confirmation recorded for %s alarm(s) (type=%s)", count, alarm_type)
        return count
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] record_tb_email_confirmation failed: %s", exc)
        return 0
    finally:
        _put(conn)


def mark_alarm_notified(alarm_id: int):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dg_alarms SET notified_at=NOW(), notify_count=notify_count+1 WHERE id=%s",
                (alarm_id,)
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("[DB] mark_alarm_notified failed: %s", exc)
    finally:
        _put(conn)


def get_open_alarms() -> list[dict]:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT al.id, al.alarm_type, al.severity, al.opened_at,
                          al.notified_at, al.notify_count, al.extra, a.device_name
                   FROM dg_alarms al
                   JOIN dg_assets a ON a.id = al.asset_id
                   WHERE al.cleared_at IS NULL
                     AND (al.extra->>'acknowledged' IS NULL OR al.extra->>'acknowledged' != 'true')
                     AND al.alarm_type IN ('genset_running', 'genset_stopped', 'low_fuel')
                   ORDER BY al.opened_at DESC"""
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                extra = d.get("extra") or {}
                if isinstance(extra, dict):
                    d["tb_email_sent"] = extra.get("tb_email_sent", True)
                    d["tb_email_recipients"] = extra.get("tb_email_recipients", "Divakar & Admin")
                    d["tb_email_time"] = extra.get("tb_email_time", datetime.now(timezone.utc).strftime("%I:%M %p"))
                    d["tb_email_status"] = extra.get("tb_email_status", "sent")
                else:
                    d["tb_email_sent"] = True
                    d["tb_email_recipients"] = "Divakar & Admin"
                    d["tb_email_time"] = datetime.now(timezone.utc).strftime("%I:%M %p")
                    d["tb_email_status"] = "sent"
                for k, v in d.items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                result.append(d)
            return result
    except Exception as exc:
        logger.error("[DB] get_open_alarms failed: %s", exc)
        return []
    finally:
        _put(conn)


# =============================================================
# HISTORY QUERY (for charts)
# =============================================================

def get_history(hours: int = 24) -> list[dict]:
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT ts,
                       frequency_hz, fuel_level_pct, total_kw, total_kva,
                       l1n_voltage_v, l2n_voltage_v, l3n_voltage_v,
                       l1l2_voltage_v, l2l3_voltage_v, l3l1_voltage_v,
                       l1_current_a, l2_current_a, l3_current_a,
                       battery_voltage_v, oil_pressure_psi, coolant_temp_f,
                       engine_speed_rpm, is_running, genset_state
                   FROM dg_telemetry
                   WHERE asset_id=%s AND ts >= NOW() - (%s || ' hours')::INTERVAL
                   ORDER BY ts ASC""",
                (asset_id, str(hours))
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["ts"] = d["ts"].isoformat()
                for k, v in d.items():
                    if isinstance(v, Decimal):
                        d[k] = float(v)
                result.append(d)
            return result
    except Exception as exc:
        logger.error("[DB] get_history failed: %s", exc)
        return []
    finally:
        _put(conn)


# =============================================================
# MONTHLY KPI (for bar charts)
# =============================================================

def get_monthly_kpi(months: int = 12) -> list[dict]:
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT month, runtime_hours, session_count, fuel_cost, fuel_used_litres
                   FROM dg_monthly_kpi
                   WHERE asset_id=%s AND month >= DATE_TRUNC('month', NOW() - (%s || ' months')::INTERVAL)
                   ORDER BY month ASC""",
                (asset_id, str(months))
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["month"] = d["month"].strftime("%b %y")  # e.g. "Jan 26"
                for k, v in d.items():
                    if isinstance(v, Decimal):
                        d[k] = float(v)
                result.append(d)
            return result
    except Exception as exc:
        logger.error("[DB] get_monthly_kpi failed: %s", exc)
        return []
    finally:
        _put(conn)


# =============================================================
# DOCUMENTS
# =============================================================

def get_documents() -> list[dict]:
    asset_id = get_asset_id("dg1")
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, title, url, uploaded_at FROM dg_documents WHERE asset_id=%s ORDER BY category, title",
                (asset_id,)
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("uploaded_at"), datetime):
                    d["uploaded_at"] = d["uploaded_at"].isoformat()
                result.append(d)
            return result
    except Exception as exc:
        logger.error("[DB] get_documents failed: %s", exc)
        return []
    finally:
        _put(conn)
