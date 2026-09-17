"""
Alarm engine for DG Monitor v2.
Evaluates 6 alarm conditions each poll cycle:
  1. Low fuel
  2. Control switch = Manual
  3. Frequency outside band
  4. Battery voltage low
  5. Coolant temperature high
  6. Oil pressure low

Each alarm: opens a DB record, sends a red HTML email via SMTP,
sends a green "Resolved" email when it clears.
De-duplication: one email open, one clear — no re-flooding.
"""

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
import db_store

logger = logging.getLogger(__name__)

# =============================================================
# ALARM RULE DEFINITIONS
# =============================================================
# Each rule: (alarm_type, label, severity, check_fn)
# check_fn(values) -> bool   True = alarm is ACTIVE

def _make_rules():
    return [
        (
            "low_fuel",
            "Low Fuel Level (<30%)",
            "critical",
            lambda v: (
                v.get("Fuel level") is not None
                and v["Fuel level"] < config.ALARM_FUEL_LOW_PCT
            ),
        ),
        (
            "genset_running",
            "Generator Started & Running",
            "info",
            lambda v: (
                v.get("Genset state") == "Running"
                or (v.get("Average engine speed") is not None and v["Average engine speed"] > 500)
            ),
        ),
    ]


ALARM_RULES = _make_rules()


# =============================================================
# EVALUATE (called every poll cycle)
# =============================================================

def evaluate(values: dict):
    """Check active alarm rules against the latest Modbus values."""
    for alarm_type, label, severity, check_fn in ALARM_RULES:
        try:
            active = check_fn(values)
        except Exception:
            active = False

        if active:
            _handle_active(alarm_type, label, severity, values)
        else:
            _handle_clear(alarm_type, label)


def trigger_genset_stop_event(values: dict):
    """Trigger explicit Generator Stopped event alert."""
    _handle_clear("genset_running", "Generator Started & Running")
    _handle_active("genset_stopped", "Generator Stopped", "info", values)


def _handle_active(alarm_type, label, severity, values):
    alarm_id = db_store.open_alarm(
        alarm_type, severity,
        extra={k: str(v) for k, v in values.items() if v is not None}
    )
    if alarm_id is not None:
        _send_alarm_email(alarm_id, alarm_type, label, severity, values)


def _handle_clear(alarm_type, label):
    open_list = db_store.get_open_alarms()
    was_open = any(a["alarm_type"] == alarm_type for a in open_list)
    db_store.clear_alarm(alarm_type)
    if was_open:
        _send_clear_email(alarm_type, label)


# =============================================================
# EMAIL
# =============================================================

_ALARM_ICONS = {
    "low_fuel":          "⛽",
    "genset_running":    "⚡",
    "genset_stopped":    "🛑",
    "freq_out_of_band":  "〰️",
    "battery_low_v":     "🔋",
    "high_coolant_temp": "🌡️",
    "low_oil_pressure":  "🛢️",
}

_ALARM_HINTS = {
    "low_fuel":          "Refuel the diesel generator tank immediately (Reserve is below 30%).",
    "genset_running":    "Generator is actively delivering power. Monitor voltage and engine telemetry.",
    "genset_stopped":    "Generator has stopped operating.",
    "freq_out_of_band":  "Check generator load and AVR settings.",
    "battery_low_v":     "Check the starting battery and charging circuit.",
    "high_coolant_temp": "Check coolant level, radiator, and cooling system.",
    "low_oil_pressure":  "STOP the generator and check engine oil level immediately.",
}


def _send_alarm_email(alarm_id, alarm_type, label, severity, values):
    icon    = _ALARM_ICONS.get(alarm_type, "⚠️")
    hint    = _ALARM_HINTS.get(alarm_type, "")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"🔴 DG ALARM | {label}"

    # Build a concise snapshot table
    snapshot = [
        ("Genset State",      values.get("Genset state", "—")),
        ("Control Switch",    values.get("Control switch position", "—")),
        ("Fuel Level",        f"{values.get('Fuel level', '—')} %"),
        ("Frequency",         f"{values.get('Frequency', '—')} Hz"),
        ("Battery Voltage",   f"{values.get('Battery voltage', '—')} V"),
        ("Oil Pressure",      f"{values.get('Oil pressure', '—')} psi"),
        ("Coolant Temp",      f"{values.get('Coolant temperature', '—')} °F"),
        ("Engine Speed",      f"{values.get('Average engine speed', '—')} rpm"),
        ("Total kW",          f"{values.get('Total kW', '—')} kW"),
    ]

    rows_html = "".join(
        f"""<tr>
          <td style="padding:8px 0;border-bottom:1px solid #1e3248;color:#8baac6;width:45%">{k}</td>
          <td style="padding:8px 0;border-bottom:1px solid #1e3248;color:#e8f0fe;font-weight:700">{v}</td>
        </tr>"""
        for k, v in snapshot
    )

    html_body = f"""
<html><body style="font-family:Arial,sans-serif;background:#070d17;color:#e8f0fe;margin:0;padding:20px">
<div style="max-width:580px;margin:0 auto">
  <div style="background:#111f30;border-radius:12px;overflow:hidden;border:1px solid #1e3248">
    <div style="background:linear-gradient(135deg,#7f1d1d,#b91c1c);padding:22px 28px">
      <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#fca5a5;margin-bottom:4px">DG ALARM ALERT</div>
      <div style="font-size:24px;font-weight:800;color:#fff">{icon} {label}</div>
    </div>
    <div style="padding:24px 28px">
      <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:18px">{rows_html}</table>
      <div style="background:#7f1d1d;border-radius:8px;padding:14px 18px;font-size:13px;color:#fee2e2;margin-bottom:18px">
        ⚠ <strong>Action Required:</strong> {hint}
      </div>
      <div style="font-size:11px;color:#4d6b88">Triggered: {now_str} &bull; Alarm ID: {alarm_id}</div>
    </div>
  </div>
</div></body></html>"""

    plain = f"DG ALARM: {label}\n" + "\n".join(f"{k}: {v}" for k, v in snapshot) + f"\nTime: {now_str}"

    sent = _send(subject, html_body, plain)
    if sent:
        db_store.mark_alarm_notified(alarm_id)


def _send_clear_email(alarm_type, label):
    icon    = _ALARM_ICONS.get(alarm_type, "✅")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"✅ RESOLVED | DG — {label}"
    html_body = f"""
<html><body style="font-family:Arial,sans-serif;background:#070d17;color:#e8f0fe;margin:0;padding:20px">
<div style="max-width:580px;margin:0 auto">
  <div style="background:#111f30;border-radius:12px;overflow:hidden;border:1px solid #1e3248">
    <div style="background:linear-gradient(135deg,#064e3b,#059669);padding:22px 28px">
      <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a7f3d0;margin-bottom:4px">DG ALARM RESOLVED</div>
      <div style="font-size:24px;font-weight:800;color:#fff">{icon} {label} — Cleared</div>
    </div>
    <div style="padding:24px 28px">
      <p style="font-size:14px;color:#e8f0fe;margin-bottom:16px">The alarm <strong>{label}</strong> has cleared. The generator is back to normal operating parameters.</p>
      <div style="font-size:11px;color:#4d6b88">Resolved: {now_str}</div>
    </div>
  </div>
</div></body></html>"""
    plain = f"RESOLVED: DG — {label}\nTime: {now_str}"
    _send(subject, html_body, plain)


def _send(subject: str, html_body: str, plain_body: str) -> bool:
    if not config.ALERT_RECIPIENTS:
        return False
    if config.SMTP_HOST == "smtp.yourdomain.com" or not config.SMTP_PASSWORD:
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config.SMTP_FROM
    msg["To"]      = ", ".join(config.ALERT_RECIPIENTS)
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    try:
        if config.SMTP_USE_TLS:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=5) as s:
                s.ehlo(); s.starttls(context=ctx); s.ehlo()
                if config.SMTP_USER and config.SMTP_PASSWORD:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.sendmail(config.SMTP_FROM, config.ALERT_RECIPIENTS, msg.as_string())
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=5) as s:
                s.ehlo()
                if config.SMTP_USER and config.SMTP_PASSWORD:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.sendmail(config.SMTP_FROM, config.ALERT_RECIPIENTS, msg.as_string())
        logger.info("[EMAIL] Sent: %s", subject)
        return True
    except Exception as exc:
        logger.error("[EMAIL] Failed: %s", exc)
        return False
