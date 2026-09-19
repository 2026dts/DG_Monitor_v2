"""
DG Monitoring Platform v2 configuration.

Architecture:
  - Postgres: ALL parameters (full telemetry, runtime, cost KPIs)
  - ThingsBoard: ONLY genset_state + fuel_level_pct (for email alerts via TB)
"""

import os

# =============================================================
# USR-W630 / Modbus settings
# =============================================================
USR_IP       = os.environ.get("USR_IP", "10.10.10.77")
USR_PORT     = int(os.environ.get("USR_PORT", "8899"))
SLAVE_ID     = int(os.environ.get("SLAVE_ID", "1"))
TCP_TIMEOUT  = int(os.environ.get("TCP_TIMEOUT", "20"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "2"))

# =============================================================
# Web server
# =============================================================
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "5001"))
DEVICE_NAME = os.environ.get("DEVICE_NAME", "DG Status")

# =============================================================
# PostgreSQL  (full telemetry + KPIs + alarms)
# =============================================================
DB_HOST     = os.environ.get("DB_HOST", "localhost")
DB_PORT     = int(os.environ.get("DB_PORT", "5432"))
DB_NAME     = os.environ.get("DB_NAME", "dg_monitor")
DB_USER     = os.environ.get("DB_USER", "dg_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "dg_password")

DB_DSN = (
    f"host={DB_HOST} port={DB_PORT} "
    f"dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
)

# =============================================================
# Fuel cost (for monthly KPI calculation)
# =============================================================
FUEL_COST_PER_LITRE   = float(os.environ.get("FUEL_COST_PER_LITRE", "96.0"))   # ₹
FUEL_CONSUMPTION_LPH  = float(os.environ.get("FUEL_CONSUMPTION_LPH", "8.5"))    # L/hr at full load
DASH_TZ               = os.environ.get("DASH_TZ", "Asia/Kolkata")

# =============================================================
# Alarm thresholds (all configurable via env vars)
# =============================================================
ALARM_FUEL_LOW_PCT        = float(os.environ.get("ALARM_FUEL_LOW_PCT",   "30.0"))
ALARM_FREQ_MIN_HZ         = float(os.environ.get("ALARM_FREQ_MIN_HZ",    "47.0"))
ALARM_FREQ_MAX_HZ         = float(os.environ.get("ALARM_FREQ_MAX_HZ",    "53.0"))
ALARM_BATT_LOW_V          = float(os.environ.get("ALARM_BATT_LOW_V",     "11.8"))
ALARM_COOLANT_HIGH_F      = float(os.environ.get("ALARM_COOLANT_HIGH_F", "220.0"))  # °F
ALARM_OIL_LOW_PSI         = float(os.environ.get("ALARM_OIL_LOW_PSI",   "20.0"))

# =============================================================
# ThingsBoard  (SELECTIVE: only genset_state + fuel_level_pct)
# =============================================================
TB_HOST         = os.environ.get("TB_HOST", "10.10.10.52")
TB_PORT         = int(os.environ.get("TB_PORT", "1883"))
TB_ACCESS_TOKEN = os.environ.get("TB_ACCESS_TOKEN", "yiTdu947lff9A6r755Kt")
TB_USE_TLS      = os.environ.get("TB_USE_TLS", "False").lower() in ("true", "1")

TB_TELEMETRY_TOPIC = "v1/devices/me/telemetry"

MQTT_RECONNECT_MIN_DELAY = 1
MQTT_RECONNECT_MAX_DELAY = 30

# =============================================================
# Email / SMTP alerts (company SMTP server)
# =============================================================
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.yourdomain.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "alerts@yourdomain.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS  = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
SMTP_FROM     = os.environ.get("SMTP_FROM", "DG Monitor <alerts@yourdomain.com>")

ALERT_RECIPIENTS = [
    e.strip()
    for e in os.environ.get("ALERT_RECIPIENTS", "engineer@yourdomain.com").split(",")
    if e.strip()
]

ALARM_EMAIL_COOLDOWN_SECONDS = int(os.environ.get("ALARM_EMAIL_COOLDOWN_SECONDS", "300"))
