"""
DG Monitor v2 — Flask web application.
Routes:
  /                       → Main DG dashboard (Radial Gauge, Dynamic Fuel Tank, Control Switch, Top-right Notifications)
  /api/status             → Live register values (JSON)
  /api/history?hours=N    → Time-series for charts (JSON)
  /api/monthly            → Monthly runtime + cost KPIs (JSON)
  /api/alarms             → Open alarm list (JSON)
  /api/documents          → Document links (JSON)
"""

from datetime import datetime
from flask import Flask, jsonify, request
import state
import db_store
from config import USR_IP, USR_PORT, SLAVE_ID

app = Flask(__name__)


# ── API ENDPOINTS ────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    with state.state_lock:
        data = dict(state.dg_state)
        data["usr"] = {"ip": USR_IP, "port": USR_PORT, "slave_id": SLAVE_ID}
    data.pop("results", None)
    return jsonify(data)

@app.route("/api/history")
def api_history():
    hours = max(1, min(int(request.args.get("hours", 24)), 720))
    return jsonify({"hours": hours, "rows": db_store.get_history(hours)})

@app.route("/api/monthly")
def api_monthly():
    months = max(1, min(int(request.args.get("months", 12)), 24))
    return jsonify(db_store.get_monthly_kpi(months))

@app.route("/api/alarms")
def api_alarms():
    alarms = db_store.get_open_alarms()
    for a in alarms:
        for k, v in a.items():
            if isinstance(v, datetime):
                a[k] = v.isoformat()
    return jsonify(alarms)

@app.route("/api/alarms/ack", methods=["POST"])
def api_alarms_ack():
    data = request.get_json(silent=True) or {}
    alarm_id = data.get("id")
    ack_all = data.get("all", False)
    if ack_all:
        db_store.acknowledge_all_alarms()
        return jsonify({"status": "ok", "message": "All alarms acknowledged"})
    elif alarm_id:
        try:
            db_store.acknowledge_alarm(int(alarm_id))
            return jsonify({"status": "ok", "message": f"Alarm {alarm_id} acknowledged"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "error", "message": "Invalid request"}), 400

@app.route("/api/tb/email-sent", methods=["GET", "POST"])
def api_tb_email_sent():
    """
    ThingsBoard Rule Chain REST API Call Webhook for email delivery confirmation.
    Accepts:
      - Query params: /api/tb/email-sent?alarm_type=low_fuel
      - Query params: /api/tb/email-sent?alarm_type=genset_running
      - JSON body or form/text body
    """
    data = request.get_json(silent=True) or {}
    alarm_type = request.args.get("alarm_type") or request.args.get("type") or data.get("alarm_type") or data.get("type")
    recipients = request.args.get("recipients") or data.get("recipients") or "Divakar & Admin"
    status = request.args.get("status") or data.get("status") or "sent"
    updated = db_store.record_tb_email_confirmation(alarm_type=alarm_type, recipients=recipients, status=status)
    return jsonify({
        "status": "ok",
        "message": f"Recorded ThingsBoard email confirmation for {updated} alarm(s)",
        "alarm_type": alarm_type,
        "recipients": recipients
    })

@app.route("/api/documents")
def api_documents():
    return jsonify(db_store.get_documents())

@app.route("/")
def dashboard():
    return DASHBOARD_HTML


# ── DASHBOARD HTML ───────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Diesel Generator · Command Center</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-zoom/2.0.1/chartjs-plugin-zoom.min.js"></script>
<style>
/* ── Design tokens matching modern dashboard aesthetic ────── */
:root {
  --bg:        #eef2f9;
  --surface:   #ffffff;
  --card:      #f8fafd;
  --card2:     #eaeff7;
  --border:    #e2e8f0;
  --border2:   #cbd5e1;
  --text:      #0f172a;
  --text2:     #475569;
  --text3:     #94a3b8;
  --green:     #0ea652;
  --green-dim: #dcfce7;
  --red:       #e11d3c;
  --red-dim:   #fde2e5;
  --amber:     #d97706;
  --amber-dim: #fef3c7;
  --blue:      #2563eb;
  --blue-dim:  #dbeafe;
  --cyan:      #0891b2;
  --cyan-dim:  #cffafe;
  --purple:    #7c3aed;
  --purple-dim:#f3e8ff;
  --orange:    #ea580c;
  --orange-dim:#ffedd5;
  --radius:    18px;
  --radius-sm: 12px;
  --shadow:    0 4px 20px rgba(15, 23, 42, 0.05), 0 1px 3px rgba(15, 23, 42, 0.03);
  --shadow-hover: 0 10px 30px rgba(15, 23, 42, 0.08), 0 2px 6px rgba(15, 23, 42, 0.04);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.5;
}

/* ── Header ──────────────────────────────────────────────── */
.hdr {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 28px;
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  box-shadow: 0 1px 4px rgba(15,23,42,.04);
}
.hdr-left { display: flex; align-items: center; gap: 14px; }
.unit-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--blue);
  background: rgba(37,99,235,.08);
  border: 1px solid rgba(37,99,235,.2);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 700;
}
.page-title { font-size: 18px; font-weight: 800; letter-spacing: -.3px; }
.page-sub { font-size: 12px; color: var(--text3); margin-top: 1px; }
.hdr-right { display: flex; align-items: center; gap: 14px; }

/* Notification Bell Button */
.notif-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text2);
  cursor: pointer;
  transition: all .2s;
}
.notif-btn:hover {
  background: rgba(37,99,235,.08);
  border-color: var(--blue);
  color: var(--blue);
}
.notif-btn.has-alarms {
  color: var(--red);
  border-color: rgba(225,29,60,.3);
  background: var(--red-dim);
  animation: bellRattle 2.5s infinite;
}
@keyframes bellRattle {
  0%, 100% { transform: rotate(0); }
  2%, 6% { transform: rotate(12deg); }
  4%, 8% { transform: rotate(-12deg); }
  10% { transform: rotate(0); }
}
.notif-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  background: var(--red);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: 9px;
  display: none;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 5px rgba(225,29,60,.4);
  border: 2px solid #fff;
}
.notif-badge.visible { display: flex; }

.sound-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--blue);
  background: rgba(37,99,235,.08);
  border: 1px solid var(--blue);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all .2s;
}
.sound-btn:hover { background: var(--blue); color: #fff; }
.sound-btn.off { background: var(--card); border-color: var(--border); color: var(--text2); }
.clock { font-size: 13px; color: var(--text2); font-variant-numeric: tabular-nums; font-weight: 500; }

/* ── Notification Dropdown / Modal Overlay ───────────────── */
.notif-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  backdrop-filter: blur(2px);
  z-index: 250;
  display: none;
  opacity: 0;
  transition: opacity .2s ease;
}
.notif-overlay.show { display: block; opacity: 1; }

.notif-modal {
  position: absolute;
  top: 65px;
  right: 28px;
  width: 420px;
  max-width: calc(100vw - 40px);
  max-height: calc(100vh - 90px);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 20px 40px rgba(15, 23, 42, 0.16);
  z-index: 300;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transform: translateY(-8px);
  transition: transform .2s ease;
}
.notif-overlay.show .notif-modal { transform: translateY(0); }

.notif-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--card);
}
.notif-title { font-size: 15px; font-weight: 800; display: flex; align-items: center; gap: 8px; }
.notif-close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: var(--text3);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  line-height: 1;
}
.notif-close-btn:hover { color: var(--text); background: var(--card2); }

.notif-body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.alarm-card-item {
  background: var(--surface);
  border: 1px solid #fecdd3;
  border-left: 4px solid var(--red);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-shadow: 0 1px 3px rgba(225,29,60,.06);
}
.alarm-card-item.warn {
  border-color: #fef08a;
  border-left-color: var(--amber);
}
.aci-top { display: flex; align-items: center; justify-content: space-between; }
.aci-badge {
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--red-dim);
  color: var(--red);
}
.aci-badge.warn { background: var(--amber-dim); color: var(--amber); }
.aci-time { font-size: 11px; color: var(--text3); }
.aci-name { font-size: 13px; font-weight: 700; color: var(--text); }
.aci-detail { font-size: 12px; color: var(--text2); }
.aci-action { font-size: 11px; color: #9f1239; font-weight: 600; }

.aci-actions-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #e2e8f0;
  gap: 8px;
}
.aci-ack-btn {
  background: #0ea652;
  color: #ffffff;
  border: none;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  box-shadow: 0 2px 4px rgba(14, 166, 82, 0.25);
}
.aci-ack-btn:hover {
  background: #15803d;
  transform: translateY(-1px);
}
.aci-ack-btn:active {
  transform: translateY(0);
}

.aci-email-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 4px 8px;
  border-radius: 6px;
  margin-top: 3px;
  margin-bottom: 3px;
}
.aci-email-info.confirmed {
  color: #15803d;
  background: #f0fdf4;
  border-color: #bbf7d0;
}
.aci-email-info strong {
  color: #0284c7;
}
.aci-email-info.confirmed strong {
  color: #16a34a;
}

.notif-ack-all-btn {
  background: var(--green-dim);
  color: var(--green);
  border: 1px solid rgba(14, 166, 82, 0.3);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.notif-ack-all-btn:hover {
  background: var(--green);
  color: #fff;
}

.notif-empty {
  padding: 36px 20px;
  text-align: center;
  color: var(--text3);
}
.notif-empty-icon { font-size: 32px; margin-bottom: 6px; color: var(--green); }
.notif-empty-text { font-size: 13px; font-weight: 600; color: var(--text2); }
.notif-empty-sub { font-size: 11px; color: var(--text3); margin-top: 2px; }

/* ── Main Centered Container (Max-Width 1200px) ──────────── */
.main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

/* ── Section Titles & Chips ──────────────────────────────── */
.sec-lbl {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--text3);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
}
.ic-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  margin-right: 8px;
  flex-shrink: 0;
}
.ic-chip svg { width: 14px; height: 14px; }

.c-cyan   { background: #cffafe; color: #0e7490; }
.c-blue   { background: #dbeafe; color: #1d4ed8; }
.c-purple { background: #f3e8ff; color: #7c3aed; }
.c-pink   { background: #fce7f3; color: #db2777; }
.c-orange { background: #ffedd5; color: #c2410c; }
.c-green  { background: #dcfce7; color: #15803d; }
.c-teal   { background: #ccfbf1; color: #0f766e; }
.c-indigo { background: #e0e7ff; color: #4338ca; }
.c-red    { background: #fee2e2; color: #b91c1c; }
.c-amber  { background: #fef3c7; color: #b45309; }
.c-slate  { background: #e2e8f0; color: #334155; }
.c-dark   { background: #0f172a; color: #ffffff; }

/* ── FEATURED DYNAMIC WIDGETS GRID ───────────────────────── */
.dynamic-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1.15fr 1fr;
  gap: 16px;
}
@media (max-width: 1080px) {
  .dynamic-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .dynamic-grid { grid-template-columns: 1fr; }
}

/* Base Dynamic Card */
.dyn-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 22px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: all .25s ease;
  position: relative;
  overflow: hidden;
}
.dyn-card:hover {
  box-shadow: var(--shadow-hover);
  border-color: var(--border2);
}

.dyn-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.dyn-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dyn-title {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
}
.dyn-sub {
  font-size: 11px;
  color: var(--text3);
  margin-top: 2px;
}

/* ── 1. DYNAMIC FUEL TANK WIDGET (Screenshot 2 Match) ────── */
.fuel-tank-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 0 4px;
}
.tank-svg-wrap {
  position: relative;
  width: 100%;
  max-width: 240px;
  height: 105px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.fuel-tank-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}
.tank-pill-badge {
  position: absolute;
  top: 52%;
  left: 36%;
  transform: translate(-50%, -50%);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(4px);
  border: 1px solid var(--border);
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 800;
  color: var(--text);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  z-index: 5;
  transition: all .3s ease;
  white-space: nowrap;
}
.fuel-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text2);
}
.fuel-meta-badge {
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  text-transform: uppercase;
  background: var(--green-dim);
  color: var(--green);
}

/* ── 2. DYNAMIC CONTROL SWITCH WIDGET (Screenshot 2 Match) ─ */
.switch-state-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 10px 0;
  text-align: center;
}
.switch-big-val {
  font-size: 32px;
  font-weight: 900;
  letter-spacing: -.5px;
  color: var(--text);
  line-height: 1.1;
  transition: color .2s;
}
.switch-toggle-track {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--card2);
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 3px;
  margin-top: 12px;
  width: 100%;
  max-width: 190px;
  position: relative;
}
.switch-pos-btn {
  flex: 1;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--text3);
  padding: 5px 0;
  border-radius: 20px;
  transition: all .25s ease;
  user-select: none;
}
.switch-pos-btn.active {
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 2px 6px rgba(0,0,0,0.08);
}
.switch-pos-btn.active.sw-auto { color: var(--green); }
.switch-pos-btn.active.sw-manual { color: var(--orange); }
.switch-pos-btn.active.sw-off { color: var(--red); }

/* ── 3. DYNAMIC RADIAL TACHOMETER GAUGE FOR ENGINE RPM ───── */
.radial-gauge-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2px 0;
  width: 100%;
}
.radial-svg-wrap {
  width: 100%;
  max-width: 190px;
  height: 98px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}
.radial-gauge-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}
.needle-rotator {
  transform-origin: 100px 92px;
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.rpm-readout-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin-top: 4px;
}
.rpm-big-val {
  font-size: 22px;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  line-height: 1;
}
.rpm-unit {
  font-size: 10px;
  font-weight: 800;
  color: var(--text3);
  text-transform: uppercase;
  margin-left: 2px;
}
.engine-status-pill {
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 12px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .5px;
  background: var(--red-dim);
  color: var(--red);
  border: 1px solid rgba(225,29,60,.2);
}
.engine-status-pill.running {
  background: var(--green-dim);
  color: var(--green);
  border-color: rgba(14,166,82,.25);
}


/* ── 4. DYNAMIC OUTPUT POWER & FREQUENCY WIDGET ──────────── */
.power-kpi-wrap {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 6px 0;
  gap: 12px;
}
.power-kpi-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.p-label { font-size: 11px; font-weight: 700; color: var(--text3); text-transform: uppercase; }
.p-val { font-size: 22px; font-weight: 800; color: var(--blue); font-variant-numeric: tabular-nums; }
.power-bar-wrap {
  height: 6px;
  background: var(--card2);
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid var(--border);
  margin-top: 2px;
}
.power-bar-fill {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, #2563eb, #0891b2);
  border-radius: 4px;
  transition: width .6s ease;
}

/* ── LIVE METRIC QUICK-CARDS ─────────────────────────────── */
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(138px, 1fr));
  gap: 10px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px 15px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-shadow: 0 1px 2px rgba(15,23,42,.03);
  transition: all .2s ease;
}
.stat-card:hover {
  box-shadow: 0 4px 14px rgba(15,23,42,.08);
  border-color: var(--border2);
}
.stat-card.alarm { border-color: var(--red)!important; background: rgba(239,68,68,.05)!important; }
.stat-card.warning { border-color: var(--amber)!important; background: rgba(245,158,11,.04)!important; }
.stat-card.ok { border-color: rgba(14,166,82,.25)!important; }

.stat-lbl {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .8px;
  color: var(--text3);
  display: flex;
  align-items: center;
  gap: 4px;
}
.stat-val {
  font-size: 20px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.stat-sub { font-size: 11px; color: var(--text3); }

.stat-val.green  { color: var(--green); }
.stat-val.red    { color: var(--red); }
.stat-val.amber  { color: var(--amber); }
.stat-val.blue   { color: var(--blue); }
.stat-val.cyan   { color: var(--cyan); }
.stat-val.purple { color: var(--purple); }
.stat-val.muted  { color: var(--text2); font-size: 15px; }

/* ── STATUS FLAGS / SYSTEM HEALTH MATRIX (2 Rows x 4 Columns) ── */
.flags-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
@media (max-width: 900px) {
  .flags-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 480px) {
  .flags-grid { grid-template-columns: 1fr; }
}

.status-card-pill {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 13px 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}
.status-card-pill:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  border-color: var(--border2);
}

.status-card-pill.ok-st {
  border-color: rgba(14, 166, 82, 0.25);
  background: linear-gradient(180deg, #ffffff 0%, #f6fcf8 100%);
}
.status-card-pill.warn-st {
  border-color: rgba(217, 119, 6, 0.35);
  background: linear-gradient(180deg, #ffffff 0%, #fffbeb 100%);
}
.status-card-pill.alarm-st {
  border-color: rgba(225, 29, 60, 0.4);
  background: linear-gradient(180deg, #ffffff 0%, #fef2f2 100%);
  animation: cardAlarmGlow 2s infinite ease-in-out;
}
@keyframes cardAlarmGlow {
  0%, 100% { box-shadow: 0 0 0 rgba(225,29,60,0); }
  50% { box-shadow: 0 0 14px rgba(225,29,60,0.25); border-color: var(--red); }
}

.scp-icon-wrap {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s;
}
.scp-icon-wrap svg {
  width: 19px;
  height: 19px;
}

.scp-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.scp-title {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.9px;
  color: var(--text3);
  line-height: 1.2;
}
.scp-status-wrap {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 3px;
}
.scp-val {
  font-size: 13.5px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: 0.3px;
  line-height: 1.2;
}

/* Pulsing Status Beacons */
.fdot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  position: relative;
}
.fdot.ok {
  background: var(--green);
  box-shadow: 0 0 7px rgba(14, 166, 82, 0.8);
}
.fdot.warn {
  background: var(--amber);
  box-shadow: 0 0 7px rgba(217, 119, 6, 0.8);
}
.fdot.err {
  background: var(--red);
  box-shadow: 0 0 7px rgba(225, 29, 60, 0.8);
  animation: dotPing 1.2s infinite ease-in-out;
}
@keyframes dotPing {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: 0.6; }
}

/* ── 2-Column Electrical & Power Grid ────────────────────── */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 900px) {
  .two-col { grid-template-columns: 1fr; }
}

/* ── Chart Cards ─────────────────────────────────────────── */
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  box-shadow: var(--shadow);
}
.chart-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 10px;
}
.chart-title {
  font-size: 14px;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 8px;
}
.range-btns { display: flex; gap: 6px; }
.range-btn {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text2);
  transition: all .18s;
  text-transform: uppercase;
}
.range-btn:hover, .range-btn.active {
  background: var(--blue);
  border-color: var(--blue);
  color: #fff;
}
.chart-wrap { position: relative; height: 220px; }

/* ── Phase Voltage / Current Pie Cards (Screenshot Match) ── */
.phase-donut-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 22px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: all .2s ease;
}
.phase-donut-card:hover {
  box-shadow: var(--shadow-hover);
  border-color: var(--border2);
}
.pdc-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.pdc-title {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.pdc-expand-btn {
  color: var(--text3);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: 6px;
  transition: all .2s;
  cursor: pointer;
}
.pdc-expand-btn:hover {
  color: var(--text);
  background: var(--card2);
}
.pdc-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.pdc-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}
.pdc-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 500;
}
.pdc-item-left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text2);
}
.pdc-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}
.pdc-val {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.pdc-chart-wrap {
  width: 120px;
  height: 120px;
  min-width: 120px;
  min-height: 120px;
  position: relative;
  flex-shrink: 0;
}
.pdc-chart-wrap canvas {
  width: 120px !important;
  height: 120px !important;
}

/* ── Engine Health 4 Dynamic Visual Widgets (Images 1-4 Match) ───── */
.batt-widget-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 0;
  width: 100%;
}
.batt-cell-svg-wrap {
  width: 100%;
  max-width: 220px;
  height: 95px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.coolant-dial-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0;
  width: 100%;
}
.coolant-dial-svg-wrap {
  width: 160px;
  height: 155px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.oil-widget-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4px 0;
  width: 100%;
}
.oil-can-svg-wrap {
  width: 100%;
  max-width: 210px;
  height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fault-widget-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4px 0;
  width: 100%;
}
.fault-hud-box {
  width: 100%;
  max-width: 210px;
  height: 95px;
  background: radial-gradient(circle, rgba(15, 23, 42, 0.92) 0%, rgba(3, 7, 18, 0.98) 100%);
  border: 1.5px solid rgba(14, 166, 82, 0.4);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 0 16px;
  position: relative;
  box-shadow: inset 0 0 20px rgba(0,0,0,0.5), 0 4px 12px rgba(15,23,42,0.1);
  transition: all 0.4s ease;
  overflow: hidden;
}
.fault-hud-box.alert-active {
  border-color: rgba(239, 68, 68, 0.8);
  box-shadow: inset 0 0 25px rgba(239, 68, 68, 0.25), 0 0 15px rgba(239, 68, 68, 0.3);
}
.fault-hud-grid {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 10px 10px;
  pointer-events: none;
}
.fault-hud-corner {
  position: absolute;
  width: 6px;
  height: 6px;
  border-color: #22c55e;
  border-style: solid;
  pointer-events: none;
  transition: border-color 0.3s;
}
.fault-hud-corner.tl { top: 3px; left: 3px; border-width: 1.5px 0 0 1.5px; }
.fault-hud-corner.tr { top: 3px; right: 3px; border-width: 1.5px 1.5px 0 0; }
.fault-hud-corner.bl { bottom: 3px; left: 3px; border-width: 0 0 1.5px 1.5px; }
.fault-hud-corner.br { bottom: 3px; right: 3px; border-width: 0 1.5px 1.5px 0; }
.fault-hud-box.alert-active .fault-hud-corner { border-color: #ef4444; }

/* ── Documents Card ──────────────────────────────────────── */
.docs-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  box-shadow: var(--shadow);
}
.docs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  margin-top: 10px;
}
.doc-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
}
.doc-title {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text3);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
}
.doc-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--blue);
  text-decoration: none;
  border-bottom: 1px solid var(--border);
}
.doc-link:last-child { border-bottom: none; }
.doc-link:hover { color: var(--cyan); }
.doc-empty { font-size: 12px; color: var(--text3); font-style: italic; }

/* ── Footer ──────────────────────────────────────────────── */
.footer {
  text-align: center;
  padding: 24px 28px;
  font-size: 12px;
  color: var(--text3);
  border-top: 1px solid var(--border);
  margin-top: 20px;
}
</style>
</head>
<body>

<!-- Header -->
<header class="hdr">
  <div class="hdr-left">
    <div class="unit-badge">● DG-1</div>
    <div>
      <div class="page-title">Diesel Generator Command Center</div>
      <div class="page-sub" id="hdrSub">10.10.10.77:8899 · Cummins PS0600 / PCC1301</div>
    </div>
  </div>
  <div class="hdr-right">
    
    <!-- Notification Bell Icon in Top Right -->
    <button id="notifBellBtn" class="notif-btn" onclick="toggleNotifPanel()" title="Active System Alarms">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
      </svg>
      <span id="notifBadge" class="notif-badge">0</span>
    </button>

    <!-- Sound Toggle Button -->
    <button id="soundToggleBtn" onclick="toggleAudio()" class="sound-btn" title="Toggle audio alarms">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 0 1 0 6"/></svg>
      <span id="soundTxt">Sound: ON</span>
    </button>
    <div class="clock" id="clock"></div>
  </div>
</header>

<!-- Notification Panel Dropdown Modal -->
<div id="notifOverlay" class="notif-overlay" onclick="closeNotifPanel(event)">
  <div class="notif-modal" onclick="event.stopPropagation()">
    <div class="notif-header">
      <div class="notif-title">
        <span class="ic-chip c-red"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3 2 20h20z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".9" fill="currentColor" stroke="none"/></svg></span>
        Active Alarms & Alerts (<span id="notifModalCount">0</span>)
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <button class="notif-ack-all-btn" onclick="ackAllAlarms(event)" title="Acknowledge and silence all alarms">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span>Ack All</span>
        </button>
        <button class="notif-close-btn" onclick="closeNotifPanel(event)">✕</button>
      </div>
    </div>
    <div class="notif-body" id="notifModalBody">
      <!-- Injected via JavaScript -->
    </div>
  </div>
</div>

<!-- Centered Main Content -->
<main class="main">

  <!-- 1. FEATURED DYNAMIC INTERACTIVE WIDGETS -->
  <div class="dynamic-grid">

    <!-- A. Dynamic Fuel Level Tank Widget (Screenshot 2 Match) -->
    <div class="dyn-card" id="cardFuelTank">
      <div>
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-dark">
              <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>
            </span>
            <div>
              <div class="dyn-title">Fuel level</div>
              <div class="dyn-sub">Primary Reserve Tank</div>
            </div>
          </div>
          <span class="fuel-meta-badge" id="fuelStatusBadge">Normal</span>
        </div>

        <!-- Cylindrical Tank SVG Graphic -->
        <div class="fuel-tank-container">
          <div class="tank-svg-wrap">
            <svg class="fuel-tank-svg" viewBox="0 0 200 90" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <clipPath id="tankInnerClip">
                  <rect x="15" y="16" width="170" height="66" rx="33" />
                </clipPath>
                <linearGradient id="liquidGradNormal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#708cfa" />
                  <stop offset="100%" stop-color="#4c6ef5" />
                </linearGradient>
                <linearGradient id="liquidGradAmber" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#fcc419" />
                  <stop offset="100%" stop-color="#f59f00" />
                </linearGradient>
                <linearGradient id="liquidGradRed" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#ff8787" />
                  <stop offset="100%" stop-color="#fa5252" />
                </linearGradient>
              </defs>

              <!-- Top Filler Neck & Cap -->
              <rect x="91" y="2" width="18" height="6" rx="2" fill="#203a72" />
              <path d="M94 8h12v9H94z" fill="none" stroke="#203a72" stroke-width="2" />

              <!-- Outer Tank Outline -->
              <rect x="15" y="16" width="170" height="66" rx="33" fill="#f8fafd" stroke="#203a72" stroke-width="2.5" />

              <!-- Inner Perspective Dished Head Arc -->
              <path d="M 68 16 A 25 33 0 0 1 68 82" fill="none" stroke="#203a72" stroke-width="1.6" stroke-dasharray="3 3" opacity="0.6" />
              <path d="M 68 16 A 25 33 0 0 0 68 82" fill="none" stroke="#203a72" stroke-width="1.8" />

              <!-- Dynamic Liquid Fill inside Clip Area -->
              <g clip-path="url(#tankInnerClip)">
                <rect id="svgLiquidRect" x="0" y="49" width="200" height="60" fill="url(#liquidGradNormal)" style="transition: all 0.8s ease;" />
                <line id="svgLiquidSurface" x1="0" y1="49" x2="200" y2="49" stroke="#ffffff" stroke-width="1.5" opacity="0.6" style="transition: all 0.8s ease;" />
              </g>
            </svg>

            <!-- Floating Center Value Badge -->
            <div class="tank-pill-badge" id="tankPillBadge">50 %</div>
          </div>
        </div>
      </div>

      <div class="fuel-meta-row">
        <span>Min Threshold: <strong>20%</strong></span>
        <span id="fuelEstimatedLiters">— Litres</span>
      </div>
    </div>

    <!-- B. Dynamic Control Switch Position Widget (Screenshot 2 Match) -->
    <div class="dyn-card" id="cardControlSwitch">
      <div>
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-slate">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="8" cy="12" r="3" fill="currentColor"/></svg>
            </span>
            <div>
              <div class="dyn-title">Control Switch</div>
              <div class="dyn-sub" id="switchLastUpdate">Last update just now</div>
            </div>
          </div>
        </div>

        <div class="switch-state-display">
          <div class="switch-big-val" id="switchBigVal">Auto</div>
          
          <!-- Visual 3-Way Mode Switcher Indicator -->
          <div class="switch-toggle-track">
            <div class="switch-pos-btn" id="swBtnOff">Off</div>
            <div class="switch-pos-btn active sw-auto" id="swBtnAuto">Auto</div>
            <div class="switch-pos-btn" id="swBtnManual">Manual</div>
          </div>
        </div>
      </div>

      <div class="fuel-meta-row">
        <span>Operating Mode</span>
        <span id="switchSubStatus" style="font-weight:700;color:var(--green)">Auto Standby</span>
      </div>
    </div>

    <!-- C. Dynamic Radial Tachometer Gauge for Engine RPM -->
    <div class="dyn-card" id="cardEngineState">
      <div>
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-cyan">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            </span>
            <div>
              <div class="dyn-title">Engine Speed</div>
              <div class="dyn-sub">Radial Tachometer</div>
            </div>
          </div>
        </div>

        <div class="radial-gauge-container">
          <div class="radial-svg-wrap">
            <svg class="radial-gauge-svg" viewBox="0 0 200 110">
              <!-- Outer Base Semi-Circle Track (Center 100, 92, Radius 70) -->
              <path d="M 30 92 A 70 70 0 0 1 170 92" fill="none" stroke="#e2e8f0" stroke-width="8" stroke-linecap="round" />

              <!-- Scale Zones -->
              <path d="M 30 92 A 70 70 0 0 1 111 23" fill="none" stroke="#0891b2" stroke-width="8" stroke-linecap="round" />
              <path d="M 111 23 A 70 70 0 0 1 160 55" fill="none" stroke="#0ea652" stroke-width="8" />
              <path d="M 160 55 A 70 70 0 0 1 170 92" fill="none" stroke="#e11d3c" stroke-width="8" stroke-linecap="round" />

              <!-- Scale Labels -->
              <text x="20" y="96" font-size="9" font-weight="700" fill="#94a3b8" text-anchor="middle">0</text>
              <text x="44" y="52" font-size="9" font-weight="700" fill="#94a3b8" text-anchor="middle">500</text>
              <text x="100" y="16" font-size="9" font-weight="700" fill="#94a3b8" text-anchor="middle">1k</text>
              <text x="150" y="50" font-size="9" font-weight="800" fill="#0ea652" text-anchor="middle">1.5k</text>
              <text x="180" y="96" font-size="9" font-weight="800" fill="#e11d3c" text-anchor="middle">2k</text>

              <!-- Needle Rotator (Pivot at 100, 92) -->
              <g class="needle-rotator" id="radialNeedle" style="transform: rotate(0deg);">
                <polygon points="100,89 100,95 44,92.5 44,91.5" fill="#e11d3c" />
                <circle cx="100" cy="92" r="7" fill="#0f172a" />
                <circle cx="100" cy="92" r="3" fill="#ffffff" />
              </g>
            </svg>
          </div>

          <div class="rpm-readout-wrap">
            <div class="rpm-big-val"><span id="radialRpmNum">0</span> <span class="rpm-unit">RPM</span></div>
            <div class="engine-status-pill" id="dynGensetPill">● STOPPED</div>
          </div>
        </div>
      </div>


      <div class="fuel-meta-row">
        <span>Rated Frequency</span>
        <span><strong>1500 RPM</strong> (50.0 Hz)</span>
      </div>
    </div>

    <!-- D. Dynamic Power Output & Frequency Widget -->
    <div class="dyn-card" id="cardPowerKpi">
      <div>
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-blue">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            </span>
            <div>
              <div class="dyn-title">Output Load</div>
              <div class="dyn-sub">Active Power & Hz</div>
            </div>
          </div>
        </div>

        <div class="power-kpi-wrap">
          <div>
            <div class="power-kpi-item">
              <span class="p-label">Active Power</span>
              <span class="p-val" id="dynKwVal">0.0 kW</span>
            </div>
            <div class="power-bar-wrap">
              <div class="power-bar-fill" id="dynKwBar"></div>
            </div>
          </div>

          <div>
            <div class="power-kpi-item">
              <span class="p-label">Frequency</span>
              <span class="p-val" style="color:var(--green);font-size:18px" id="dynFreqVal">0.00 Hz</span>
            </div>
          </div>
        </div>
      </div>

      <div class="fuel-meta-row">
        <span>Apparent Power</span>
        <span id="dynKvaVal"><strong>0.0 kVA</strong></span>
      </div>
    </div>

  </div>

  <!-- 2. ENGINE HEALTH & DIAGNOSTICS - DYNAMIC VISUAL WIDGETS -->
  <div>
    <div class="sec-lbl">
      <span class="ic-chip c-orange"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></span>
      Engine Health & Diagnostics
    </div>
    <div class="dynamic-grid" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));">
      
      <!-- 1. BATTERY VOLTAGE WIDGET (Image 1 Match: 3D Glossy Battery Tube) -->
      <div class="dyn-card" id="sc-batt">
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-green">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/></svg>
            </span>
            <div>
              <div class="dyn-title">Battery Voltage</div>
              <div class="dyn-sub">12V DC Starter Supply</div>
            </div>
          </div>
          <span class="fuel-meta-badge" id="battStatusBadge" style="background:var(--green-dim);color:var(--green)">Healthy</span>
        </div>

        <div class="batt-widget-container">
          <div class="batt-cell-svg-wrap">
            <svg viewBox="0 0 200 80" fill="none" style="width:100%;height:100%;">
              <defs>
                <clipPath id="battBodyClip">
                  <rect x="16" y="14" width="156" height="52" rx="12" />
                </clipPath>
                <!-- Battery 3D Tube Gradient -->
                <linearGradient id="battTubeGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#475569" />
                  <stop offset="15%" stop-color="#1e293b" />
                  <stop offset="50%" stop-color="#0f172a" />
                  <stop offset="85%" stop-color="#1e293b" />
                  <stop offset="100%" stop-color="#020617" />
                </linearGradient>
                <!-- Liquid Fill Gradient Green -->
                <linearGradient id="battLiqGreen" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#4ade80" />
                  <stop offset="30%" stop-color="#22c55e" />
                  <stop offset="70%" stop-color="#16a34a" />
                  <stop offset="100%" stop-color="#14532d" />
                </linearGradient>
                <!-- Liquid Fill Gradient Red -->
                <linearGradient id="battLiqRed" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#f87171" />
                  <stop offset="30%" stop-color="#ef4444" />
                  <stop offset="70%" stop-color="#dc2626" />
                  <stop offset="100%" stop-color="#7f1d1d" />
                </linearGradient>
                <!-- Metallic Cap Gradient -->
                <linearGradient id="metalCapGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#cbd5e1" />
                  <stop offset="40%" stop-color="#f8fafc" />
                  <stop offset="70%" stop-color="#94a3b8" />
                  <stop offset="100%" stop-color="#475569" />
                </linearGradient>
              </defs>

              <!-- Positive Terminal Knob on Right -->
              <rect x="174" y="27" width="10" height="26" rx="4" fill="url(#metalCapGrad)" stroke="#475569" stroke-width="1.5" />

              <!-- Main Battery Body Casing (Metallic Rims) -->
              <rect x="12" y="11" width="164" height="58" rx="14" fill="url(#metalCapGrad)" stroke="#334155" stroke-width="1.5" />
              <!-- Inner Black Tube -->
              <rect x="16" y="14" width="156" height="52" rx="12" fill="url(#battTubeGrad)" />

              <!-- Dynamic Liquid Charge Fill -->
              <g clip-path="url(#battBodyClip)">
                <rect id="svgBattFill" x="16" y="14" width="130" height="52" fill="url(#battLiqGreen)" style="transition: width 0.8s ease, fill 0.5s ease;" />
                <!-- Glossy Glass Reflection Sheen -->
                <path d="M 16 14 L 172 14 L 172 32 Q 94 38 16 32 Z" fill="#ffffff" opacity="0.25" />
                <rect x="16" y="58" width="156" height="8" fill="#ffffff" opacity="0.1" />
              </g>

              <!-- Centered Bold Percentage Text -->
              <text x="94" y="46" font-size="18" font-weight="900" fill="#ffffff" text-anchor="middle" id="svgBattPctText" style="text-shadow: 0 2px 4px rgba(0,0,0,0.8);">85%</text>
            </svg>
          </div>
          <div style="font-size: 18px; font-weight: 900; color: var(--text); margin-top: -4px;" id="svgBattVoltsText">12.6 V</div>
        </div>

        <div class="fuel-meta-row">
          <span>Min Threshold: <strong>11.8 V</strong></span>
          <span id="sv-batt-pct">Charge: <strong>85 %</strong></span>
        </div>
      </div>

      <!-- 2. COOLANT TEMP WIDGET (Image 2 Match: Realistic Circular Dial Thermometer) -->
      <div class="dyn-card" id="sc-temp">
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-orange">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/></svg>
            </span>
            <div>
              <div class="dyn-title">Coolant Temp</div>
              <div class="dyn-sub">Circular Dial Thermometer</div>
            </div>
          </div>
          <span class="fuel-meta-badge" id="tempStatusBadge" style="background:var(--green-dim);color:var(--green)">Normal</span>
        </div>

        <div class="coolant-dial-container">
          <div class="coolant-dial-svg-wrap">
            <svg viewBox="0 0 200 200" style="width:100%;height:100%;">
              <defs>
                <radialGradient id="dialPlateGrad" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stop-color="#ffffff" />
                  <stop offset="85%" stop-color="#f8fafc" />
                  <stop offset="100%" stop-color="#e2e8f0" />
                </radialGradient>
                <filter id="dialShadow" x="-10%" y="-10%" width="120%" height="120%">
                  <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.1" />
                </filter>
              </defs>

              <!-- Outer Dial Bezel Rim -->
              <circle cx="100" cy="100" r="92" fill="#f1f5f9" stroke="#cbd5e1" stroke-width="3" filter="url(#dialShadow)" />
              <circle cx="100" cy="100" r="86" fill="url(#dialPlateGrad)" stroke="#e2e8f0" stroke-width="1.5" />

              <!-- Outer Color-Graded Arc (Green -> Yellow -> Orange -> Red) -->
              <path d="M 59.0 141.0 A 58 58 0 0 1 59.0 59.0" fill="none" stroke="#22c55e" stroke-width="8" stroke-linecap="round" />
              <path d="M 59.0 59.0 A 58 58 0 0 1 100.0 42.0" fill="none" stroke="#eab308" stroke-width="8" />
              <path d="M 100.0 42.0 A 58 58 0 0 1 141.0 59.0" fill="none" stroke="#f97316" stroke-width="8" />
              <path d="M 141.0 59.0 A 58 58 0 0 1 141.0 141.0" fill="none" stroke="#ef4444" stroke-width="8" stroke-linecap="round" />

              <!-- Inner Scale Arc -->
              <path d="M 68.2 131.8 A 45 45 0 0 1 100.0 55.0" fill="none" stroke="#22c55e" stroke-width="1.5" />
              <path d="M 100.0 55.0 A 45 45 0 0 1 131.8 131.8" fill="none" stroke="#ef4444" stroke-width="1.5" />

              <!-- Radial Ticks & Outer Numbers (Reference Image 2 Match) -->
              <line x1="55.5" y1="144.5" x2="50.5" y2="149.5" stroke="#94a3b8" stroke-width="1.5" />
              <text x="41.3" y="161.9" font-size="8" font-weight="600" fill="#15803d" text-anchor="middle">-60</text>
              <line x1="39.1" y1="116.3" x2="32.4" y2="118.1" stroke="#94a3b8" stroke-width="1.5" />
              <text x="19.8" y="124.7" font-size="8" font-weight="600" fill="#15803d" text-anchor="middle">-40</text>
              <line x1="39.1" y1="83.7" x2="32.4" y2="81.9" stroke="#94a3b8" stroke-width="1.5" />
              <text x="19.8" y="81.7" font-size="8" font-weight="600" fill="#15803d" text-anchor="middle">-20</text>
              <line x1="55.5" y1="55.5" x2="50.5" y2="50.5" stroke="#94a3b8" stroke-width="1.5" />
              <text x="41.3" y="44.5" font-size="8" font-weight="800" fill="#15803d" text-anchor="middle">0</text>
              <line x1="83.7" y1="39.1" x2="81.9" y2="32.4" stroke="#94a3b8" stroke-width="1.5" />
              <text x="78.5" y="23.0" font-size="8" font-weight="600" fill="#b45309" text-anchor="middle">20</text>
              <line x1="116.3" y1="39.1" x2="118.1" y2="32.4" stroke="#94a3b8" stroke-width="1.5" />
              <text x="121.5" y="23.0" font-size="8" font-weight="600" fill="#b45309" text-anchor="middle">40</text>
              <line x1="144.5" y1="55.5" x2="149.5" y2="50.5" stroke="#94a3b8" stroke-width="1.5" />
              <text x="158.7" y="44.5" font-size="8" font-weight="800" fill="#c2410c" text-anchor="middle">60</text>
              <line x1="160.9" y1="83.7" x2="167.6" y2="81.9" stroke="#94a3b8" stroke-width="1.5" />
              <text x="180.2" y="81.7" font-size="8" font-weight="600" fill="#c2410c" text-anchor="middle">80</text>
              <line x1="160.9" y1="116.3" x2="167.6" y2="118.1" stroke="#94a3b8" stroke-width="1.5" />
              <text x="180.2" y="124.7" font-size="8" font-weight="600" fill="#b91c1c" text-anchor="middle">100</text>
              <line x1="144.5" y1="144.5" x2="149.5" y2="149.5" stroke="#94a3b8" stroke-width="1.5" />
              <text x="158.7" y="161.9" font-size="8" font-weight="800" fill="#b91c1c" text-anchor="middle">120</text>

              <!-- Unit Label -->
              <text x="100" y="152" font-size="13" font-weight="800" fill="#0f172a" text-anchor="middle">°F</text>

              <!-- Pointer Needle (Pivot cx=100, cy=100) -->
              <g id="tempNeedleGroup" style="transform-origin: 100px 100px; transform: rotate(-135deg); transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);">
                <polygon points="100,34 103,100 97,100" fill="#0f172a" />
                <circle cx="100" cy="100" r="9" fill="#0f172a" stroke="#475569" stroke-width="1.5" />
                <circle cx="100" cy="100" r="3.5" fill="#ffffff" />
              </g>
            </svg>
          </div>
          <div style="font-size: 18px; font-weight: 900; color: var(--text); margin-top: -4px;" id="sv-temp-num">0.0 °F</div>
        </div>

        <div class="fuel-meta-row">
          <span>Max Safe Limit</span>
          <span><strong>220 °F</strong></span>
        </div>
      </div>

      <!-- 3. OIL PRESSURE WIDGET (Image 3 Match: Neon Glowing Automotive Oil Can) -->
      <div class="dyn-card" id="sc-oil">
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-purple">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>
            </span>
            <div>
              <div class="dyn-title">Oil Pressure</div>
              <div class="dyn-sub">Engine Lube Circuit</div>
            </div>
          </div>
          <span class="fuel-meta-badge" id="oilStatusBadge" style="background:var(--green-dim);color:var(--green)">Optimal</span>
        </div>

        <div class="oil-widget-container">
          <div class="oil-can-svg-wrap">
            <svg viewBox="0 0 200 115" fill="none" style="width:100%;height:100%;">
              <defs>
                <filter id="oilCanNeonGlow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="3.5" result="glow1" />
                  <feGaussianBlur stdDeviation="7" result="glow2" />
                  <feMerge>
                    <feMergeNode in="glow2" />
                    <feMergeNode in="glow1" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <linearGradient id="oilTileGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#1f0a0a" />
                  <stop offset="100%" stop-color="#0a0202" />
                </linearGradient>
              </defs>

              <!-- Dark Neon Display Tile -->
              <rect x="8" y="6" width="184" height="103" rx="14" fill="url(#oilTileGrad)" stroke="#451111" stroke-width="1.5" />

              <!-- Glowing Automotive Engine Oil Can Vector Path -->
              <g id="svgOilCanGroup" filter="url(#oilCanNeonGlow)">
                <!-- Handle on Left -->
                <path d="M 38 48 C 24 48 20 58 20 66 C 20 76 28 84 40 84 L 50 84 L 50 75 L 40 75 C 33 75 29 71 29 66 C 29 61 33 56 40 56 L 54 56 L 54 48 Z" fill="#ffd100" stroke="#ff9100" stroke-width="1"/>
                <!-- Top Filler Cap -->
                <path d="M 76 32 L 106 32 L 106 38 L 95 38 L 95 46 L 87 46 L 87 38 L 76 38 Z" fill="#ffd100" stroke="#ff9100" stroke-width="1"/>
                <!-- Main Can Body & Spout (Sharp Double-line glow) -->
                <path d="M 50 48 L 118 48 L 148 62 L 175 50 L 178 55 L 152 69 L 126 84 L 50 84 Z" fill="rgba(255, 209, 0, 0.15)" stroke="#ffd100" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>
                <!-- Dripping Oil Droplet -->
                <path d="M 176 68 C 176 68 168 80 168 86 C 168 91 172 95 176 95 C 180 95 184 91 184 86 C 184 80 176 68 176 68 Z" fill="#ffd100" stroke="#ff9100" stroke-width="1.2"/>
              </g>

              <!-- Sub-caption inside tile -->
              <text x="100" y="102" font-size="9" font-weight="900" fill="#fb8500" text-anchor="middle" letter-spacing="1.2" id="svgOilTileText">ENGINE OIL PRESSURE</text>
            </svg>
          </div>
          <div style="font-size: 20px; font-weight: 900; color: #d97706; font-variant-numeric: tabular-nums; margin-top: -2px;" id="sv-oil-num">0.0 psi</div>
        </div>

        <div class="fuel-meta-row">
          <span>Min Operating Pressure</span>
          <span><strong>20.0 psi</strong></span>
        </div>
      </div>

      <!-- 4. ACTIVE FAULT ALERT WIDGET (Image 4 Match: Cyberpunk Tech Alert HUD) -->
      <div class="dyn-card" id="sc-fault">
        <div class="dyn-hdr">
          <div class="dyn-title-wrap">
            <span class="ic-chip c-red">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            </span>
            <div>
              <div class="dyn-title">Active Fault</div>
              <div class="dyn-sub">Diagnostics & Alarms</div>
            </div>
          </div>
          <span class="fuel-meta-badge" id="faultStatusBadge" style="background:var(--green-dim);color:var(--green)">System Safe</span>
        </div>

        <div class="fault-widget-container">
          <div class="fault-hud-box" id="faultHudBox">
            <div class="fault-hud-grid"></div>
            <div class="fault-hud-corner tl"></div>
            <div class="fault-hud-corner tr"></div>
            <div class="fault-hud-corner bl"></div>
            <div class="fault-hud-corner br"></div>

            <!-- Glowing Triangle Alert Icon -->
            <div style="display:flex;align-items:center;justify-content:center;flex-shrink:0;">
              <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" id="svgFaultIcon" style="filter: drop-shadow(0 0 8px rgba(34, 197, 94, 0.7)); transition: all 0.4s ease;">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
                <line x1="12" y1="9" x2="12" y2="13" stroke-width="2.5"/>
                <circle cx="12" cy="17" r="1.2" fill="currentColor" stroke="none"/>
              </svg>
            </div>

            <div style="display:flex;flex-direction:column;z-index:2;">
              <span style="font-size:10px;font-weight:800;color:#94a3b8;letter-spacing:1.2px;text-transform:uppercase;">DIAGNOSTIC STATUS</span>
              <span style="font-size:18px;font-weight:900;color:#22c55e;line-height:1.2;margin-top:2px;" id="sv-fault-code">NORMAL (#0)</span>
              <span style="font-size:11px;font-weight:700;color:#64748b;margin-top:1px;" id="sv-fault-sub">Severity: None</span>
            </div>
          </div>
        </div>

        <div class="fuel-meta-row">
          <span>Fault Severity</span>
          <span id="ss-fault-sev" style="font-weight:700;color:var(--green)">None</span>
        </div>
      </div>

    </div>
  </div>


  <!-- 3. STATUS FLAGS / SYSTEM HEALTH MATRIX -->
  <div>
    <div class="sec-lbl">
      <span class="ic-chip c-indigo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/></svg></span>
      System Health & Diagnostics Matrix
    </div>
    <div class="flags-grid" id="flagsGrid">
      
      <!-- Genset State -->
      <div class="status-card-pill ok-st" id="fl-state">
        <div class="scp-icon-wrap c-green">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><circle cx="12" cy="12" r="3"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Genset</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-state-v">STOPPED</span>
          </div>
        </div>
      </div>

      <!-- Control Switch -->
      <div class="status-card-pill ok-st" id="fl-switch">
        <div class="scp-icon-wrap c-cyan">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="6" width="18" height="12" rx="6"/><circle cx="8" cy="12" r="3"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Control</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-switch-v">AUTO</span>
          </div>
        </div>
      </div>

      <!-- Fuel Status -->
      <div class="status-card-pill ok-st" id="fl-fuel">
        <div class="scp-icon-wrap c-amber">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 22V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v17M3 11h12M15 8h2a2 2 0 0 1 2 2v6a2 2 0 0 0 2 2h0a2 2 0 0 0 2-2V9.5a1.5 1.5 0 0 0-3-1"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Fuel Level</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-fuel-v">NORMAL</span>
          </div>
        </div>
      </div>

      <!-- Battery Status -->
      <div class="status-card-pill ok-st" id="fl-batt">
        <div class="scp-icon-wrap c-green">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Battery</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-batt-v">HEALTHY</span>
          </div>
        </div>
      </div>

      <!-- Oil Pressure -->
      <div class="status-card-pill ok-st" id="fl-oil">
        <div class="scp-icon-wrap c-orange">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 14c1.66 0 3-1.34 3-3 0-2-3-6-3-6s-3 4-3 6c0 1.66 1.34 3 3 3z"/><path d="M5 6h9v12H5z"/><path d="M2 10h3M2 14h3"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Oil Press</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-oil-v">OPTIMAL</span>
          </div>
        </div>
      </div>

      <!-- Coolant Temp -->
      <div class="status-card-pill ok-st" id="fl-temp">
        <div class="scp-icon-wrap c-blue">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Coolant</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-temp-v">NORMAL</span>
          </div>
        </div>
      </div>

      <!-- Frequency Band -->
      <div class="status-card-pill ok-st" id="fl-freq">
        <div class="scp-icon-wrap c-purple">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h3l3-7 4 14 4-10 2 5 2-2h4"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Frequency</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-freq-v">IN BAND</span>
          </div>
        </div>
      </div>

      <!-- Modbus Link -->
      <div class="status-card-pill ok-st" id="fl-link">
        <div class="scp-icon-wrap c-teal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/></svg>
        </div>
        <div class="scp-body">
          <span class="scp-title">Modbus Link</span>
          <div class="scp-status-wrap">
            <span class="fdot ok"></span>
            <span class="scp-val" id="fl-link-v">ONLINE</span>
          </div>
        </div>
      </div>

    </div>
  </div>

  <!-- 4. THREE-PHASE ELECTRICAL & POWER MEASUREMENTS -->
  <div>
    <div class="sec-lbl">
      <span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>
      Three-Phase Electrical & Power Analysis
    </div>

    <!-- Featured 3-Card Grid for Phase Voltages, Phase Currents & Power -->
    <div class="dynamic-grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); margin-bottom: 20px;">
      
      <!-- Phase Voltages Pie Card (Screenshot Exact Match) -->
      <div class="phase-donut-card">
        <div class="pdc-hdr">
          <div class="pdc-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
              <path d="M12 9v4"/><path d="M12 17h.01"/>
            </svg>
            Phase Voltages
          </div>
          <div class="pdc-expand-btn" title="Expand view">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
            </svg>
          </div>
        </div>
        <div class="pdc-body">
          <div class="pdc-list">
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#0ea652"></span>
                <span>L1-N</span>
              </div>
              <span class="pdc-val" id="pieL1NVal">0 V</span>
            </div>
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#ff4d4f"></span>
                <span>L2-N</span>
              </div>
              <span class="pdc-val" id="pieL2NVal">0 V</span>
            </div>
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#fadb14"></span>
                <span>L3-N</span>
              </div>
              <span class="pdc-val" id="pieL3NVal">0 V</span>
            </div>
          </div>
          <div class="pdc-chart-wrap">
            <canvas id="phaseVoltPie"></canvas>
          </div>
        </div>
      </div>

      <!-- Phase Currents Pie Card -->
      <div class="phase-donut-card">
        <div class="pdc-hdr">
          <div class="pdc-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
            </svg>
            Phase Currents
          </div>
          <div class="pdc-expand-btn" title="Expand view">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
            </svg>
          </div>
        </div>
        <div class="pdc-body">
          <div class="pdc-list">
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#d97706"></span>
                <span>L1 Current</span>
              </div>
              <span class="pdc-val" id="pieL1CurrVal">0.0 A</span>
            </div>
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#e11d3c"></span>
                <span>L2 Current</span>
              </div>
              <span class="pdc-val" id="pieL2CurrVal">0.0 A</span>
            </div>
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#2563eb"></span>
                <span>L3 Current</span>
              </div>
              <span class="pdc-val" id="pieL3CurrVal">0.0 A</span>
            </div>
          </div>
          <div class="pdc-chart-wrap">
            <canvas id="phaseCurrPie"></canvas>
          </div>
        </div>
      </div>

      <!-- Line Voltages Pie Card (Screenshot 2 Match) -->
      <div class="phase-donut-card">
        <div class="pdc-hdr">
          <div class="pdc-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
              <path d="M12 9v4"/><path d="M12 17h.01"/>
            </svg>
            Line Voltages
          </div>
          <div class="pdc-expand-btn" title="Expand view">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
            </svg>
          </div>
        </div>
        <div class="pdc-body">
          <div class="pdc-list">
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#0ea652"></span>
                <span>L1-L2</span>
              </div>
              <span class="pdc-val" id="cardL1L2">0 V</span>
            </div>
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#ff4d4f"></span>
                <span>L2-L3</span>
              </div>
              <span class="pdc-val" id="cardL2L3">0 V</span>
            </div>
            <div class="pdc-item">
              <div class="pdc-item-left">
                <span class="pdc-dot" style="background:#fadb14"></span>
                <span>L3-L1</span>
              </div>
              <span class="pdc-val" id="cardL3L1">0 V</span>
            </div>
          </div>
          <div class="pdc-chart-wrap">
            <canvas id="lineVoltPie"></canvas>
          </div>
        </div>
      </div>

    </div>
  </div>

  <div class="two-col" style="margin-bottom: 20px;">
    <!-- Phase & Line Voltages -->
    <div>
      <div class="sec-lbl">
        <span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>
        Phase & Line Voltages / Currents Detailed Breakdown
      </div>
      <div class="status-grid" id="elecGrid"></div>
    </div>

    <!-- Power Measurements -->
    <div>
      <div class="sec-lbl">
        <span class="ic-chip c-teal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></span>
        Active, Apparent & Reactive Power Breakdown
      </div>
      <div class="status-grid" id="powerGrid"></div>
    </div>
  </div>

  <!-- 5. VOLTAGE HISTORY CHART -->
  <div class="chart-card">
    <div class="chart-hdr">
      <div class="chart-title">
        <span class="ic-chip c-green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg></span>
        Line-to-Neutral Voltage History (L1-N, L2-N, L3-N)
      </div>
      <div class="range-btns">
        <button class="range-btn" onclick="setActiveRangeBtn(this); loadVoltChart(1)">1h</button>
        <button class="range-btn active" onclick="setActiveRangeBtn(this); loadVoltChart(6)">6h</button>
        <button class="range-btn" onclick="setActiveRangeBtn(this); loadVoltChart(24)">24h</button>
        <button class="range-btn" onclick="setActiveRangeBtn(this); loadVoltChart(72)">3d</button>
        <button class="range-btn" onclick="setActiveRangeBtn(this); loadVoltChart(168)">7d</button>
      </div>
    </div>
    <div class="chart-wrap"><canvas id="voltChart"></canvas></div>
  </div>

  <!-- 6. 2-COLUMN MONTHLY KPIS -->
  <div class="two-col">
    <div class="chart-card">
      <div class="chart-hdr">
        <div class="chart-title">
          <span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></span>
          Monthly Runtime Hours
        </div>
        <div class="range-btns">
          <button class="range-btn active" onclick="setActiveRangeBtn(this); loadKpi(6,'runtime')">6 mo</button>
          <button class="range-btn" onclick="setActiveRangeBtn(this); loadKpi(12,'runtime')">12 mo</button>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="runtimeChart"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-hdr">
        <div class="chart-title">
          <span class="ic-chip c-orange"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3h12M6 8h12M6 13l7 8M6 13h3a5 5 0 0 0 0-10"/></svg></span>
          Monthly Estimated Fuel Cost (₹)
        </div>
        <div class="range-btns">
          <button class="range-btn active" onclick="setActiveRangeBtn(this); loadKpi(6,'cost')">6 mo</button>
          <button class="range-btn" onclick="setActiveRangeBtn(this); loadKpi(12,'cost')">12 mo</button>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="costChart"></canvas></div>
    </div>
  </div>

  <!-- 8. YAHOO FINANCE STYLE RUNNING TIME & COST TREND CHART -->
  <div class="chart-card">
    <div class="chart-hdr">
      <div class="chart-title">
        <span class="ic-chip c-purple"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></span>
        Running Time & Cost Trend (Yahoo Finance Style)
      </div>
      <div class="range-btns" style="display:flex;align-items:center;gap:6px;">
        <button class="range-btn" onclick="setActiveRangeBtn(this); loadTrend(24)">1D</button>
        <button class="range-btn active" onclick="setActiveRangeBtn(this); loadTrend(168)">1W</button>
        <button class="range-btn" onclick="setActiveRangeBtn(this); loadTrend(720)">1MO</button>
        <button class="range-btn reset-zoom-btn" onclick="resetTrendZoom()" title="Reset Zoom View" style="padding:4px 9px;font-size:11px;font-weight:700;background:#e2e8f0;color:#334155;border:none;border-radius:6px;cursor:pointer;margin-left:4px;transition:all 0.2s;">🔍 Reset Zoom</button>
      </div>
    </div>
    <div class="chart-wrap" style="height:280px"><canvas id="trendChart"></canvas></div>
  </div>

  <!-- 9. DOCUMENTS & MANUALS -->
  <div class="docs-card">
    <div class="sec-lbl">
      <span class="ic-chip c-blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></span>
      Technical Manuals & Documents
    </div>
    <div class="docs-grid" id="docsGrid">
      <div style="color:var(--text3);font-size:13px">Loading documents…</div>
    </div>
  </div>

</main>

<footer class="footer">
  Diesel Generator Monitoring Platform v2 · Cummins PS0600 / PCC1301 · PostgreSQL Backend · Real-time Modbus Link
</footer>

<script>
// ── Helpers ────────────────────────────────────────────────
const el = id => document.getElementById(id);
const fmt = (v, u='', d=1) => v != null ? Number(v).toFixed(d) + (u ? ' ' + u : '') : '—';

function setActiveRangeBtn(btn) {
  if (!btn) return;
  const parent = btn.closest ? btn.closest('.range-btns') : btn.parentElement;
  if (parent) {
    parent.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
}

let _voltPieChart = null;
let _currPieChart = null;
let _lastVolts = [0, 0, 0];
let _lastCurrs = [0, 0, 0];

function initPhasePieCharts() {
  const vCtx = el('phaseVoltPie');
  if (vCtx && !_voltPieChart) {
    _voltPieChart = new Chart(vCtx.getContext('2d'), {
      type: 'pie',
      data: {
        labels: ['L1-N', 'L2-N', 'L3-N'],
        datasets: [{
          data: [1, 1, 1],
          backgroundColor: ['#0ea652', '#ff4d4f', '#fadb14'],
          borderWidth: 1.5,
          borderColor: '#ffffff',
          hoverOffset: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#ffffff',
            titleColor: '#0f172a',
            bodyColor: '#475569',
            borderColor: '#e2e8f0',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: function(ctx) {
                const label = ctx.label || '';
                const val = _lastVolts[ctx.dataIndex];
                return ` ${label}: ${val != null && val > 0 ? Number(val).toFixed(1) + ' V' : '0 V'}`;
              }
            }
          }
        }
      }
    });
  }

  const cCtx = el('phaseCurrPie');
  if (cCtx && !_currPieChart) {
    _currPieChart = new Chart(cCtx.getContext('2d'), {
      type: 'pie',
      data: {
        labels: ['L1 Current', 'L2 Current', 'L3 Current'],
        datasets: [{
          data: [1, 1, 1],
          backgroundColor: ['#d97706', '#e11d3c', '#2563eb'],
          borderWidth: 1.5,
          borderColor: '#ffffff',
          hoverOffset: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#ffffff',
            titleColor: '#0f172a',
            bodyColor: '#475569',
            borderColor: '#e2e8f0',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: function(ctx) {
                const label = ctx.label || '';
                const val = _lastCurrs[ctx.dataIndex];
                return ` ${label}: ${val != null && val > 0 ? Number(val).toFixed(1) + ' A' : '0.0 A'}`;
              }
            }
          }
        }
      }
    });
  }
}

let _lineVoltPieChart = null;
let _lastLineVolts = [0, 0, 0];

function initLineVoltPie() {
  const lCtx = el('lineVoltPie');
  if (lCtx && !_lineVoltPieChart) {
    _lineVoltPieChart = new Chart(lCtx.getContext('2d'), {
      type: 'pie',
      data: {
        labels: ['L1-L2', 'L2-L3', 'L3-L1'],
        datasets: [{
          data: [1, 1, 1],
          backgroundColor: ['#0ea652', '#ff4d4f', '#fadb14'],
          borderWidth: 1.5,
          borderColor: '#ffffff',
          hoverOffset: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#ffffff',
            titleColor: '#0f172a',
            bodyColor: '#475569',
            borderColor: '#e2e8f0',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: function(ctx) {
                const label = ctx.label || '';
                const val = _lastLineVolts[ctx.dataIndex];
                return ` ${label}: ${val != null && val > 0 ? Number(val).toFixed(1) + ' V' : '0 V'}`;
              }
            }
          }
        }
      }
    });
  }
}

function updateClock() {
  el('clock').textContent = new Date().toLocaleString('en-IN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    day: '2-digit', month: 'short', year: 'numeric'
  });
}

// ── Notification Dropdown Panel Controls ───────────────────
let _alarmsCache = [];

function toggleNotifPanel() {
  const overlay = el('notifOverlay');
  if (overlay.classList.contains('show')) {
    overlay.classList.remove('show');
  } else {
    renderNotifModalBody();
    overlay.classList.add('show');
  }
}

function closeNotifPanel(e) {
  if (e) e.stopPropagation();
  el('notifOverlay').classList.remove('show');
}

let _silencedAlarmIds = new Set(JSON.parse(localStorage.getItem('dg_silenced_alarms') || '[]'));

async function ackAlarm(alarmId, event) {
  if (event) event.stopPropagation();
  if (!alarmId) return;
  _silencedAlarmIds.add(Number(alarmId));
  localStorage.setItem('dg_silenced_alarms', JSON.stringify([..._silencedAlarmIds]));
  
  // Optimistically remove from cache
  _alarmsCache = _alarmsCache.filter(a => Number(a.id) !== Number(alarmId));
  renderNotifModalBody();
  
  const notifBadge = el('notifBadge');
  const notifBtn = el('notifBellBtn');
  if (_alarmsCache.length > 0) {
    if (notifBadge) notifBadge.textContent = _alarmsCache.length;
  } else {
    if (notifBtn) notifBtn.classList.remove('has-alarms');
    if (notifBadge) notifBadge.classList.remove('visible');
  }

  try {
    await fetch('/api/alarms/ack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: alarmId })
    });
  } catch(e) {}
}

async function ackAllAlarms(event) {
  if (event) event.stopPropagation();
  _alarmsCache.forEach(a => { if (a.id) _silencedAlarmIds.add(Number(a.id)); });
  localStorage.setItem('dg_silenced_alarms', JSON.stringify([..._silencedAlarmIds]));
  
  _alarmsCache = [];
  renderNotifModalBody();

  const notifBadge = el('notifBadge');
  const notifBtn = el('notifBellBtn');
  if (notifBtn) notifBtn.classList.remove('has-alarms');
  if (notifBadge) notifBadge.classList.remove('visible');

  try {
    await fetch('/api/alarms/ack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ all: true })
    });
  } catch(e) {}
}

function renderNotifModalBody() {
  const container = el('notifModalBody');
  const countSpan = el('notifModalCount');
  if (countSpan) countSpan.textContent = _alarmsCache.length;

  if (!_alarmsCache || _alarmsCache.length === 0) {
    container.innerHTML = `
      <div class="notif-empty">
        <div class="notif-empty-icon">✓</div>
        <div class="notif-empty-text">All Systems Nominal</div>
        <div class="notif-empty-sub">No active alarms or critical events detected. Generator is operating safely.</div>
      </div>
    `;
    return;
  }

  const alarmHelp = {
    'GENSET_RUNNING': 'Generator engine started & running. Telemetry is being logged.',
    'GENSET_STOPPED': 'Generator engine has stopped operating.',
    'LOW_FUEL': 'Immediate action: Refuel primary diesel storage tank (Reserve is below 30%).'
  };

  const alarmTitles = {
    'genset_running': 'Generator Started & Running',
    'genset_stopped': 'Generator Stopped',
    'low_fuel': 'Low Fuel Level (<30%)'
  };

  container.innerHTML = _alarmsCache.map(a => {
    const typeKey = (a.alarm_type || '').toUpperCase();
    const isInfo = a.severity === 'info' || typeKey.includes('RUNNING') || typeKey.includes('STOPPED');
    const isCritical = a.severity === 'critical' || typeKey.includes('LOW_FUEL');
    const badgeType = isCritical ? 'CRITICAL ALARM' : isInfo ? 'EVENT' : 'WARNING';
    const badgeClass = isCritical ? '' : isInfo ? 'info' : 'warn';
    const title = alarmTitles[a.alarm_type] || (a.alarm_type || 'Safety Alert').replace(/_/g, ' ');
    const triggerVal = a.trigger_value != null ? Number(a.trigger_value).toFixed(1) : '—';
    const threshVal = a.threshold_value != null ? Number(a.threshold_value).toFixed(1) : '—';
    const timeStr = a.opened_at ? new Date(a.opened_at).toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'}) : 'Active';
    const advice = alarmHelp[typeKey] || 'Verify operational parameters and safety interlocks.';

    return `
      <div class="alarm-card-item ${isCritical ? '' : isInfo ? 'info' : 'warn'}">
        <div class="aci-top">
          <span class="aci-badge ${badgeClass}">${badgeType}</span>
          <span class="aci-time">${timeStr}</span>
        </div>
        <div class="aci-name">${title}</div>
        <div class="aci-detail">Reading: <strong>${triggerVal}</strong> (Safe threshold: ${threshVal})</div>
        ${a.tb_email_sent ? `
        <div class="aci-email-info confirmed">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span>ThingsBoard: Email delivered to <strong>${a.tb_email_recipients || 'Divakar & Admin'}</strong></span>
        </div>
        ` : `
        <div class="aci-email-info">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
          <span>Email alert configured for: <strong>${a.tb_email_recipients || 'Divakar & Admin'}</strong></span>
        </div>
        `}
        <div class="aci-actions-row">
          <div class="aci-action">⚠ ${advice}</div>
          <button class="aci-ack-btn" onclick="ackAlarm(${a.id}, event)" title="Acknowledge & Silence this alarm">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
            <span>Acknowledge</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

// ── Audio Alarm System ─────────────────────────────────────
let _audioCtx = null;
let _audioEnabled = localStorage.getItem('dg_audio_enabled') === '1'; // Persisted in browser localStorage
let _lastBeep = 0;
let _playedAlarmIds = new Set();

function initAudioUI() {
  const btn = el('soundToggleBtn');
  if (!btn) return;
  if (_audioEnabled) {
    btn.classList.remove('off');
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>
      <span id="soundTxt">Sound: ON</span>`;
  } else {
    btn.classList.add('off');
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>
      <span id="soundTxt">Sound: OFF</span>`;
  }
}

function toggleAudio() {
  _audioEnabled = !_audioEnabled;
  localStorage.setItem('dg_audio_enabled', _audioEnabled ? '1' : '0');
  initAudioUI();
}

function checkAndTriggerAlarmAudio() {
  if (!_audioEnabled || !_alarmsCache || _alarmsCache.length === 0) return;
  
  // Filter only un-silenced active alarms
  const unAckAlarms = _alarmsCache.filter(a => !a.id || !_silencedAlarmIds.has(Number(a.id)));
  if (unAckAlarms.length === 0) return;

  // Only trigger audio for critical severity alarms or on first detection of an alarm
  const hasCritical = unAckAlarms.some(a => (a.severity || '').toLowerCase() === 'critical');
  const hasNewAlert = unAckAlarms.some(a => a.id && !_playedAlarmIds.has(a.id));
  
  if (hasCritical || hasNewAlert) {
    playAlarmBeep();
    unAckAlarms.forEach(a => { if (a.id) _playedAlarmIds.add(a.id); });
  }
}

function playAlarmBeep() {
  if (!_audioEnabled) return;
  const now = Date.now();
  if (now - _lastBeep < 15000) return; // Cooldown between beeps
  _lastBeep = now;

  try {
    if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (_audioCtx.state === 'suspended') _audioCtx.resume();

    const osc = _audioCtx.createOscillator();
    const gain = _audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, _audioCtx.currentTime);
    osc.frequency.setValueAtTime(660, _audioCtx.currentTime + 0.15);

    gain.gain.setValueAtTime(0.2, _audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, _audioCtx.currentTime + 0.35);

    osc.connect(gain);
    gain.connect(_audioCtx.destination);
    osc.start();
    osc.stop(_audioCtx.currentTime + 0.35);
  } catch(e) {}
}

function metricCard(label, value, color='cyan', iconSvg='', sub='') {
  return `<div class="stat-card">
    <div class="stat-lbl">${iconSvg}${label}</div>
    <div class="stat-val ${color}">${value}</div>
    ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
  </div>`;
}

// ── Live Status Update ─────────────────────────────────────
async function updateStatus() {
  try {
    const [sRes, aRes] = await Promise.all([
      fetch('/api/status', { cache: 'no-store' }),
      fetch('/api/alarms', { cache: 'no-store' })
    ]);
    const data = await sRes.json();
    const alarms = await aRes.json();
    _alarmsCache = alarms || [];
    const v = data.values || {};

    if (data.usr) {
      el('hdrSub').textContent = `${data.usr.ip}:${data.usr.port} · Slave ${data.usr.slave_id} · Cummins PS0600`;
    }

    // ── Update Notification Bell & Badge in Header ─────────
    const notifBtn = el('notifBellBtn');
    const notifBadge = el('notifBadge');
    if (_alarmsCache.length > 0) {
      notifBtn.classList.add('has-alarms');
      notifBadge.textContent = _alarmsCache.length;
      notifBadge.classList.add('visible');
      checkAndTriggerAlarmAudio();
    } else {
      notifBtn.classList.remove('has-alarms');
      notifBadge.classList.remove('visible');
    }

    // If modal is currently open, refresh its content live
    if (el('notifOverlay').classList.contains('show')) {
      renderNotifModalBody();
    }

    // ── 1. DYNAMIC FUEL TANK WIDGET UPDATE ──────────────────
    const fuel = v['Fuel level'];
    const fuelPct = fuel != null ? Math.max(0, Math.min(100, Number(fuel))) : 0;
    
    // Position of liquid rectangle inside 66px inner height (from Y=16 to Y=82)
    const liquidTopY = 82 - (fuelPct / 100) * 66;
    const liquidH = (fuelPct / 100) * 66;

    const svgRect = el('svgLiquidRect');
    const svgSurface = el('svgLiquidSurface');
    if (svgRect && svgSurface) {
      svgRect.setAttribute('y', liquidTopY);
      svgRect.setAttribute('height', liquidH);
      svgSurface.setAttribute('y1', liquidTopY);
      svgSurface.setAttribute('y2', liquidTopY);

      if (fuelPct < 30) {
        svgRect.setAttribute('fill', 'url(#liquidGradRed)');
      } else if (fuelPct < 50) {
        svgRect.setAttribute('fill', 'url(#liquidGradAmber)');
      } else {
        svgRect.setAttribute('fill', 'url(#liquidGradNormal)');
      }
    }

    // Pill badge & meta
    el('tankPillBadge').textContent = fuel != null ? `${fuelPct.toFixed(0)} %` : '— %';
    const fuelBadge = el('fuelStatusBadge');
    if (fuelPct < 30) {
      fuelBadge.textContent = 'Critical Low (<30%)';
      fuelBadge.style.background = 'var(--red-dim)';
      fuelBadge.style.color = 'var(--red)';
    } else if (fuelPct < 50) {
      fuelBadge.textContent = 'Low Reserve';
      fuelBadge.style.background = 'var(--amber-dim)';
      fuelBadge.style.color = 'var(--amber)';
    } else {
      fuelBadge.textContent = 'Normal';
      fuelBadge.style.background = 'var(--green-dim)';
      fuelBadge.style.color = 'var(--green)';
    }
    el('fuelEstimatedLiters').innerHTML = fuel != null ? `Reserve: <strong>${(fuelPct * 10).toFixed(0)} L</strong>` : '— Litres';

    // ── 2. DYNAMIC CONTROL SWITCH WIDGET UPDATE ────────────
    let sw = v['Control switch position'];
    if (!sw || sw === 'Unknown (124)' || sw === '124') sw = 'Auto';
    if (sw === '123') sw = 'Off';
    if (sw === '125') sw = 'Manual';

    const swVal = el('switchBigVal');
    swVal.textContent = sw;

    const btnOff = el('swBtnOff');
    const btnAuto = el('swBtnAuto');
    const btnManual = el('swBtnManual');
    const swSub = el('switchSubStatus');

    btnOff.className = 'switch-pos-btn';
    btnAuto.className = 'switch-pos-btn';
    btnManual.className = 'switch-pos-btn';

    if (sw.toLowerCase() === 'auto') {
      btnAuto.className = 'switch-pos-btn active sw-auto';
      swVal.style.color = 'var(--green)';
      swSub.textContent = 'Auto Standby Ready';
      swSub.style.color = 'var(--green)';
    } else if (sw.toLowerCase() === 'manual') {
      btnManual.className = 'switch-pos-btn active sw-manual';
      swVal.style.color = 'var(--orange)';
      swSub.textContent = 'Manual Operator Control';
      swSub.style.color = 'var(--orange)';
    } else {
      btnOff.className = 'switch-pos-btn active sw-off';
      swVal.style.color = 'var(--red)';
      swSub.textContent = 'Generator Switched Off';
      swSub.style.color = 'var(--red)';
    }
    el('switchLastUpdate').textContent = data.last_update ? `Poll: ${data.last_update.split(' ')[1] || data.last_update}` : 'Live';

    // ── 3. DYNAMIC RADIAL TACHOMETER GAUGE UPDATE ──────────
    const rpm = v['Average engine speed'];
    const rpmVal = rpm != null ? Number(rpm) : 0;
    el('radialRpmNum').textContent = rpmVal.toFixed(0);

    // Needle rotation: 0 RPM = 0deg (left), 1000 RPM = 90deg (top), 2000 RPM = 180deg (right)
    const rpmClamped = Math.max(0, Math.min(2000, rpmVal));
    const needleDeg = (rpmClamped / 2000) * 180;
    const needleEl = el('radialNeedle');
    if (needleEl) {
      needleEl.style.transform = `rotate(${needleDeg.toFixed(1)}deg)`;
    }

    let gs = v['Genset state'] || (data.is_running ? 'Running' : 'Stopped');
    if (gs === 'Unknown (124)' || gs === '124') gs = 'Stopped';
    if (gs === '123') gs = 'Off';
    if (gs === '125') gs = 'Ready';
    if (gs === '128') gs = 'Running';

    const pill = el('dynGensetPill');
    if (data.is_running) {
      pill.className = 'engine-status-pill running';
      pill.textContent = `● RUNNING (${gs.toUpperCase()})`;
    } else {
      pill.className = 'engine-status-pill';
      pill.textContent = `● ${gs.toUpperCase()}`;
    }


    // ── 4. DYNAMIC OUTPUT POWER & FREQUENCY WIDGET UPDATE ──
    const kw = v['Total kW'];
    const kwNum = kw != null ? Number(kw) : 0;
    el('dynKwVal').textContent = kwNum.toFixed(1) + ' kW';
    const kwBar = el('dynKwBar');
    if (kwBar) {
      kwBar.style.width = Math.min(100, Math.max(0, (kwNum / 50) * 100)) + '%';
    }

    const freq = v['Frequency'];
    const freqVal = freq != null ? Number(freq) : 0;
    const freqBad = freq != null && data.is_running && (freqVal < 47.0 || freqVal > 53.0);
    el('dynFreqVal').textContent = fmt(freq, 'Hz', 2);
    const kva = v['Total kVA'];
    el('dynKvaVal').innerHTML = `<strong>${fmt(kva, 'kVA', 1)}</strong>`;

    // ── 5. ENGINE HEALTH & DIAGNOSTICS DYNAMIC WIDGETS UPDATE ──
    // A. Battery Voltage 3D Glossy Cell Widget (Image 1 Match)
    const batt = v['Battery voltage'];
    const battVolts = batt != null ? Number(batt) : 0;
    const battLow = batt != null && batt < 11.8;
    const battPct = Math.max(0, Math.min(100, ((battVolts - 10.0) / (14.5 - 10.0)) * 100));
    
    const svgBattFill = el('svgBattFill');
    if (svgBattFill) {
      svgBattFill.setAttribute('width', Math.max(6, (battPct / 100) * 156));
      svgBattFill.setAttribute('fill', battLow && battVolts > 0 ? 'url(#battLiqRed)' : 'url(#battLiqGreen)');
    }
    if (el('svgBattPctText')) el('svgBattPctText').textContent = battVolts > 0 ? `${battPct.toFixed(0)}%` : '0%';
    if (el('svgBattVoltsText')) el('svgBattVoltsText').textContent = battVolts > 0 ? `${battVolts.toFixed(1)} V` : '0 V';
    if (el('sv-batt-pct')) el('sv-batt-pct').innerHTML = `Charge: <strong>${battPct.toFixed(0)} %</strong>`;
    
    const battBadge = el('battStatusBadge');
    if (battBadge) {
      if (battLow && battVolts > 0) {
        battBadge.textContent = 'Low Voltage';
        battBadge.style.background = 'var(--red-dim)';
        battBadge.style.color = 'var(--red)';
      } else {
        battBadge.textContent = 'Healthy';
        battBadge.style.background = 'var(--green-dim)';
        battBadge.style.color = 'var(--green)';
      }
    }

    // B. Coolant Temperature Circular Dial Thermometer Widget (Image 2 Match)
    const temp = v['Coolant temperature'];
    const tempVal = temp != null ? Number(temp) : 0;
    const tempHigh = temp != null && temp > 220;
    if (el('sv-temp-num')) el('sv-temp-num').textContent = `${tempVal.toFixed(1)} °F`;
    
    // Needle rotation: -60°F (-135deg) to 120°F (+135deg) on dial face
    const tempClamped = Math.max(-60, Math.min(120, tempVal));
    const tempDeg = -135 + ((tempClamped + 60) / 180) * 270;
    const tempNeedle = el('tempNeedleGroup');
    if (tempNeedle) {
      tempNeedle.style.transform = `rotate(${tempDeg.toFixed(1)}deg)`;
    }
    
    const tempBadge = el('tempStatusBadge');
    if (tempBadge) {
      if (tempHigh) {
        tempBadge.textContent = 'Overheating';
        tempBadge.style.background = 'var(--red-dim)';
        tempBadge.style.color = 'var(--red)';
      } else {
        tempBadge.textContent = 'Normal';
        tempBadge.style.background = 'var(--green-dim)';
        tempBadge.style.color = 'var(--green)';
      }
    }

    // C. Oil Pressure Glowing Automotive Oil Can Widget (Image 3 Match)
    const oil = v['Oil pressure'];
    const oilVal = oil != null ? Number(oil) : 0;
    const oilLow = oil != null && data.is_running && oil < 20;
    if (el('sv-oil-num')) {
      el('sv-oil-num').textContent = `${oilVal.toFixed(1)} psi`;
      el('sv-oil-num').style.color = oilLow ? '#ef4444' : '#d97706';
    }
    
    const oilGroup = el('svgOilCanGroup');
    const oilBadge = el('oilStatusBadge');
    if (oilGroup) {
      if (oilLow) {
        oilGroup.querySelectorAll('path').forEach(p => {
          if (p.getAttribute('fill') && p.getAttribute('fill') !== 'none') p.setAttribute('fill', '#ef4444');
          if (p.getAttribute('stroke')) p.setAttribute('stroke', '#dc2626');
        });
        if (oilBadge) {
          oilBadge.textContent = 'Low Pressure';
          oilBadge.style.background = 'var(--red-dim)';
          oilBadge.style.color = 'var(--red)';
        }
      } else {
        oilGroup.querySelectorAll('path').forEach(p => {
          if (p.getAttribute('fill') && p.getAttribute('fill') !== 'none' && !p.getAttribute('fill').includes('rgba')) p.setAttribute('fill', '#ffd100');
          if (p.getAttribute('stroke')) p.setAttribute('stroke', '#ff9100');
        });
        if (oilBadge) {
          oilBadge.textContent = 'Optimal';
          oilBadge.style.background = 'var(--green-dim)';
          oilBadge.style.color = 'var(--green)';
        }
      }
    }

    // D. Active Fault Cyberpunk Tech Alert HUD (Image 4 Match)
    const faultNum = v['Current fault number'];
    const faultSev = v['Current fault severity'] || 'None';
    const faultCodeEl = el('sv-fault-code');
    const faultSubEl = el('sv-fault-sub');
    const faultSevEl = el('ss-fault-sev');
    const faultBadge = el('faultStatusBadge');
    const faultHudBox = el('faultHudBox');
    const svgFaultIcon = el('svgFaultIcon');

    if (faultNum != null && faultNum > 0) {
      if (faultCodeEl) {
        faultCodeEl.textContent = `FAULT #${faultNum}`;
        faultCodeEl.style.color = '#ef4444';
      }
      if (faultSubEl) {
        faultSubEl.textContent = `Severity: ${faultSev}`;
        faultSubEl.style.color = '#f87171';
      }
      if (faultSevEl) {
        faultSevEl.textContent = faultSev;
        faultSevEl.style.color = faultSev === 'Shutdown' ? 'var(--red)' : 'var(--amber)';
      }
      if (faultBadge) {
        faultBadge.textContent = 'FAULT DETECTED';
        faultBadge.style.background = 'var(--red-dim)';
        faultBadge.style.color = 'var(--red)';
      }
      if (faultHudBox) {
        faultHudBox.classList.add('alert-active');
      }
      if (svgFaultIcon) {
        svgFaultIcon.setAttribute('stroke', '#ef4444');
        svgFaultIcon.style.filter = 'drop-shadow(0 0 10px rgba(239, 68, 68, 0.9))';
      }
    } else {
      if (faultCodeEl) {
        faultCodeEl.textContent = 'NORMAL (#0)';
        faultCodeEl.style.color = '#22c55e';
      }
      if (faultSubEl) {
        faultSubEl.textContent = 'Severity: None';
        faultSubEl.style.color = '#64748b';
      }
      if (faultSevEl) {
        faultSevEl.textContent = 'None';
        faultSevEl.style.color = 'var(--green)';
      }
      if (faultBadge) {
        faultBadge.textContent = 'System Safe';
        faultBadge.style.background = 'var(--green-dim)';
        faultBadge.style.color = 'var(--green)';
      }
      if (faultHudBox) {
        faultHudBox.classList.remove('alert-active');
      }
      if (svgFaultIcon) {
        svgFaultIcon.setAttribute('stroke', '#22c55e');
        svgFaultIcon.style.filter = 'drop-shadow(0 0 8px rgba(34, 197, 94, 0.7))';
      }
    }


    // ── 6. STATUS FLAGS / SYSTEM HEALTH MATRIX UPDATE ──────
    const flState = el('fl-state');
    const flStateV = el('fl-state-v');
    if (flState && flStateV) {
      flStateV.textContent = gs.toUpperCase();
      flState.className = 'status-card-pill ' + (data.is_running ? 'ok-st' : 'warn-st');
      flState.querySelector('.fdot').className = 'fdot ' + (data.is_running ? 'ok' : 'warn');
    }

    const flSwitch = el('fl-switch');
    const flSwitchV = el('fl-switch-v');
    if (flSwitch && flSwitchV) {
      flSwitchV.textContent = (sw || '—').toUpperCase();
      const swClass = sw === 'Auto' ? 'ok-st' : sw === 'Manual' ? 'warn-st' : 'alarm-st';
      flSwitch.className = 'status-card-pill ' + swClass;
      flSwitch.querySelector('.fdot').className = 'fdot ' + (sw === 'Auto' ? 'ok' : sw === 'Manual' ? 'warn' : 'err');
    }

    const flFuel = el('fl-fuel');
    const flFuelV = el('fl-fuel-v');
    if (flFuel && flFuelV) {
      flFuelV.textContent = fuelPct < 30 ? 'CRITICAL LOW' : fuelPct < 50 ? 'LOW RESERVE' : 'NORMAL';
      const fuelClass = fuelPct < 30 ? 'alarm-st' : fuelPct < 50 ? 'warn-st' : 'ok-st';
      flFuel.className = 'status-card-pill ' + fuelClass;
      flFuel.querySelector('.fdot').className = 'fdot ' + (fuelPct < 30 ? 'err' : fuelPct < 50 ? 'warn' : 'ok');
    }

    const flBatt = el('fl-batt');
    const flBattV = el('fl-batt-v');
    if (flBatt && flBattV) {
      flBattV.textContent = battLow ? 'LOW VOLTAGE' : 'HEALTHY';
      flBatt.className = 'status-card-pill ' + (battLow ? 'alarm-st' : 'ok-st');
      flBatt.querySelector('.fdot').className = 'fdot ' + (battLow ? 'err' : 'ok');
    }

    const flOil = el('fl-oil');
    const flOilV = el('fl-oil-v');
    if (flOil && flOilV) {
      flOilV.textContent = oilLow ? 'LOW PRESSURE' : 'OPTIMAL';
      flOil.className = 'status-card-pill ' + (oilLow ? 'alarm-st' : 'ok-st');
      flOil.querySelector('.fdot').className = 'fdot ' + (oilLow ? 'err' : 'ok');
    }

    const flTemp = el('fl-temp');
    const flTempV = el('fl-temp-v');
    if (flTemp && flTempV) {
      flTempV.textContent = tempHigh ? 'OVERHEATING' : 'NORMAL';
      flTemp.className = 'status-card-pill ' + (tempHigh ? 'alarm-st' : 'ok-st');
      flTemp.querySelector('.fdot').className = 'fdot ' + (tempHigh ? 'err' : 'ok');
    }

    const flFreq = el('fl-freq');
    const flFreqV = el('fl-freq-v');
    if (flFreq && flFreqV) {
      flFreqV.textContent = freqBad ? 'OUT OF BAND' : 'IN BAND (50Hz)';
      flFreq.className = 'status-card-pill ' + (freqBad ? 'alarm-st' : 'ok-st');
      flFreq.querySelector('.fdot').className = 'fdot ' + (freqBad ? 'err' : 'ok');
    }

    const flLink = el('fl-link');
    const flLinkV = el('fl-link-v');
    if (flLink && flLinkV) {
      flLinkV.textContent = data.connected ? 'ONLINE' : 'OFFLINE';
      flLink.className = 'status-card-pill ' + (data.connected ? 'ok-st' : 'alarm-st');
      flLink.querySelector('.fdot').className = 'fdot ' + (data.connected ? 'ok' : 'err');
    }

    // ── 7. FEATURED PHASE VOLTAGE & CURRENT PIE CHARTS ──────
    const l1n = v['L1-N voltage'];
    const l2n = v['L2-N voltage'];
    const l3n = v['L3-N voltage'];
    if (el('pieL1NVal')) el('pieL1NVal').textContent = fmt(l1n, 'V', 1);
    if (el('pieL2NVal')) el('pieL2NVal').textContent = fmt(l2n, 'V', 1);
    if (el('pieL3NVal')) el('pieL3NVal').textContent = fmt(l3n, 'V', 1);

    const v1 = l1n != null && Number(l1n) > 0 ? Number(l1n) : 0;
    const v2 = l2n != null && Number(l2n) > 0 ? Number(l2n) : 0;
    const v3 = l3n != null && Number(l3n) > 0 ? Number(l3n) : 0;
    _lastVolts = [v1, v2, v3];

    initPhasePieCharts();
    if (_voltPieChart) {
      if (v1 === 0 && v2 === 0 && v3 === 0) {
        _voltPieChart.data.datasets[0].data = [1, 1, 1];
      } else {
        _voltPieChart.data.datasets[0].data = [v1, v2, v3];
      }
      _voltPieChart.update('none');
    }

    const l1c = v['L1 current'];
    const l2c = v['L2 current'];
    const l3c = v['L3 current'];
    if (el('pieL1CurrVal')) el('pieL1CurrVal').textContent = fmt(l1c, 'A', 1);
    if (el('pieL2CurrVal')) el('pieL2CurrVal').textContent = fmt(l2c, 'A', 1);
    if (el('pieL3CurrVal')) el('pieL3CurrVal').textContent = fmt(l3c, 'A', 1);

    const c1 = l1c != null && Number(l1c) > 0 ? Number(l1c) : 0;
    const c2 = l2c != null && Number(l2c) > 0 ? Number(l2c) : 0;
    const c3 = l3c != null && Number(l3c) > 0 ? Number(l3c) : 0;
    _lastCurrs = [c1, c2, c3];

    if (_currPieChart) {
      if (c1 === 0 && c2 === 0 && c3 === 0) {
        _currPieChart.data.datasets[0].data = [1, 1, 1];
      } else {
        _currPieChart.data.datasets[0].data = [c1, c2, c3];
      }
      _currPieChart.update('none');
    }

    if (el('cardL1L2')) el('cardL1L2').textContent = fmt(v['L1-L2 voltage'], 'V', 1);
    if (el('cardL2L3')) el('cardL2L3').textContent = fmt(v['L2-L3 voltage'], 'V', 1);
    if (el('cardL3L1')) el('cardL3L1').textContent = fmt(v['L3-L1 voltage'], 'V', 1);

    // Update line voltages pie
    const lv1 = v['L1-L2 voltage'] != null && Number(v['L1-L2 voltage']) > 0 ? Number(v['L1-L2 voltage']) : 0;
    const lv2 = v['L2-L3 voltage'] != null && Number(v['L2-L3 voltage']) > 0 ? Number(v['L2-L3 voltage']) : 0;
    const lv3 = v['L3-L1 voltage'] != null && Number(v['L3-L1 voltage']) > 0 ? Number(v['L3-L1 voltage']) : 0;
    _lastLineVolts = [lv1, lv2, lv3];
    initLineVoltPie();
    if (_lineVoltPieChart) {
      _lineVoltPieChart.data.datasets[0].data = (lv1 === 0 && lv2 === 0 && lv3 === 0) ? [1, 1, 1] : [lv1, lv2, lv3];
      _lineVoltPieChart.update('none');
    }

    // ── 8. ELECTRICAL & POWER GRIDS ────────────────────────
    const eg = el('elecGrid');
    if (eg) {
      eg.innerHTML = [
        metricCard('L1-N', fmt(v['L1-N voltage'], 'V', 1), 'cyan', '<span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>', 'Phase 1'),
        metricCard('L2-N', fmt(v['L2-N voltage'], 'V', 1), 'cyan', '<span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>', 'Phase 2'),
        metricCard('L3-N', fmt(v['L3-N voltage'], 'V', 1), 'cyan', '<span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>', 'Phase 3'),
        metricCard('L1-L2', fmt(v['L1-L2 voltage'], 'V', 1), 'blue', '<span class="ic-chip c-blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>', 'Line 1-2'),
        metricCard('L2-L3', fmt(v['L2-L3 voltage'], 'V', 1), 'blue', '<span class="ic-chip c-blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>', 'Line 2-3'),
        metricCard('L3-L1', fmt(v['L3-L1 voltage'], 'V', 1), 'blue', '<span class="ic-chip c-blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>', 'Line 3-1'),
        metricCard('L1 Current', fmt(v['L1 current'], 'A', 1), 'amber', '<span class="ic-chip c-amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>', fmt(v['L1 current percentage'], '%', 1) + ' load'),
        metricCard('L2 Current', fmt(v['L2 current'], 'A', 1), 'amber', '<span class="ic-chip c-amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>', fmt(v['L2 current percentage'], '%', 1) + ' load'),
        metricCard('L3 Current', fmt(v['L3 current'], 'A', 1), 'amber', '<span class="ic-chip c-amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>', fmt(v['L3 current percentage'], '%', 1) + ' load'),
      ].join('');
    }

    const pg = el('powerGrid');
    if (pg) {
      pg.innerHTML = [
        metricCard('Total kW', fmt(kw, 'kW', 1), 'cyan', '<span class="ic-chip c-cyan"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></span>', 'Active Power'),
        metricCard('Total kVA', fmt(v['Total kVA'], 'kVA', 1), 'blue', '<span class="ic-chip c-blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></span>', 'Apparent Power'),
        metricCard('Total kVAr', fmt(v['Total kVAr'], 'kVAr', 1), 'purple', '<span class="ic-chip c-purple"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></span>', 'Reactive Power'),
        metricCard('L1 kW', fmt(v['L1 kW'], 'kW', 1), 'muted', '<span class="ic-chip c-slate"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>', 'Phase 1 kW'),
        metricCard('L2 kW', fmt(v['L2 kW'], 'kW', 1), 'muted', '<span class="ic-chip c-slate"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>', 'Phase 2 kW'),
        metricCard('L3 kW', fmt(v['L3 kW'], 'kW', 1), 'muted', '<span class="ic-chip c-slate"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>', 'Phase 3 kW'),
      ].join('');
    }

  } catch(e) {
    console.error('Status error:', e);
  }
}

// ── Chart Configurations (Light Theme) ─────────────────────
const LIGHT_CHART_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: {
        color: '#475569',
        boxWidth: 12,
        padding: 14,
        font: { family: 'Inter, sans-serif', size: 11, weight: '600' }
      }
    },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: '#ffffff',
      titleColor: '#0f172a',
      bodyColor: '#475569',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      padding: 10,
      boxPadding: 4,
      usePointStyle: true,
    }
  },
  scales: {
    x: {
      ticks: { color: '#94a3b8', maxTicksLimit: 8, font: { size: 10 } },
      grid: { color: '#eef2f9' }
    },
    y: {
      ticks: { color: '#94a3b8', font: { size: 10 } },
      grid: { color: '#eef2f9' }
    }
  },
  interaction: { mode: 'index', intersect: false },
  elements: { point: { radius: 0, hitRadius: 8 } }
};

let _charts = {};
function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

function downsample(rows, max=400) {
  if (!rows || rows.length <= max) return rows || [];
  const step = Math.ceil(rows.length / max);
  return rows.filter((_, i) => i % step === 0);
}

function fmtTs(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' });
}

// ── Voltage Chart ──────────────────────────────────────────
async function loadVoltChart(hours) {
  try {
    const { rows } = await (await fetch(`/api/history?hours=${hours}`, { cache: 'no-store' })).json();
    const ds = downsample(rows);
    const labels = ds.map(r => fmtTs(r.ts));
    destroyChart('volt');
    _charts.volt = new Chart(el('voltChart'), {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'L1-N (V)', data: ds.map(r => r.l1n_voltage_v), borderColor: '#0ea652', backgroundColor: 'rgba(14,166,82,0.05)', borderWidth: 2, tension: .25, fill: false, pointRadius: 0 },
          { label: 'L2-N (V)', data: ds.map(r => r.l2n_voltage_v), borderColor: '#0891b2', backgroundColor: 'rgba(8,145,178,0.05)', borderWidth: 2, tension: .25, fill: false, pointRadius: 0 },
          { label: 'L3-N (V)', data: ds.map(r => r.l3n_voltage_v), borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.05)', borderWidth: 2, tension: .25, fill: false, pointRadius: 0 },
        ]
      },
      options: {
        ...LIGHT_CHART_OPTS,
        scales: {
          ...LIGHT_CHART_OPTS.scales,
          y: { ...LIGHT_CHART_OPTS.scales.y, title: { display: true, text: 'Voltage (V)', color: '#94a3b8', font: { size: 10, weight: '700' } } }
        }
      }
    });
  } catch(e) {}
}

// ── Current Chart ──────────────────────────────────────────
async function loadCurrChart(hours) {
  try {
    const { rows } = await (await fetch(`/api/history?hours=${hours}`, { cache: 'no-store' })).json();
    const ds = downsample(rows);
    const labels = ds.map(r => fmtTs(r.ts));
    destroyChart('curr');
    _charts.curr = new Chart(el('currChart'), {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'L1 (A)', data: ds.map(r => r.l1_current_a), borderColor: '#d97706', borderWidth: 2, tension: .25, fill: false, pointRadius: 0 },
          { label: 'L2 (A)', data: ds.map(r => r.l2_current_a), borderColor: '#e11d3c', borderWidth: 2, tension: .25, fill: false, pointRadius: 0 },
          { label: 'L3 (A)', data: ds.map(r => r.l3_current_a), borderColor: '#2563eb', borderWidth: 2, tension: .25, fill: false, pointRadius: 0 },
        ]
      },
      options: {
        ...LIGHT_CHART_OPTS,
        scales: {
          ...LIGHT_CHART_OPTS.scales,
          y: { ...LIGHT_CHART_OPTS.scales.y, title: { display: true, text: 'Current (A)', color: '#94a3b8', font: { size: 10, weight: '700' } } }
        }
      }
    });
  } catch(e) {}
}

// ── Monthly KPI Charts ─────────────────────────────────────
let _kpiData = [];
async function loadKpi(months, type='runtime') {
  try {
    if (!_kpiData.length || _kpiData._months !== months) {
      _kpiData = await (await fetch(`/api/monthly?months=${months}`, { cache: 'no-store' })).json();
      _kpiData._months = months;
    }
    const rows = _kpiData.filter(r => !r._months);
    const labels = rows.map(r => r.month);

    if (type === 'runtime') {
      destroyChart('runtime');
      _charts.runtime = new Chart(el('runtimeChart'), {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Runtime (hrs)',
            data: rows.map(r => r.runtime_hours || 0),
            backgroundColor: '#0891b2',
            borderColor: '#0e7490',
            borderWidth: 1,
            borderRadius: 6,
          }]
        },
        options: {
          ...LIGHT_CHART_OPTS,
          plugins: {
            ...LIGHT_CHART_OPTS.plugins,
            tooltip: {
              ...LIGHT_CHART_OPTS.plugins.tooltip,
              callbacks: { label: c => `${Number(c.raw).toFixed(1)} hrs (${rows[c.dataIndex]?.session_count || 0} runs)` }
            }
          },
          scales: {
            ...LIGHT_CHART_OPTS.scales,
            y: { ...LIGHT_CHART_OPTS.scales.y, title: { display: true, text: 'Hours', color: '#94a3b8', font: { size: 10 } }, min: 0 }
          }
        }
      });
    } else {
      destroyChart('cost');
      _charts.cost = new Chart(el('costChart'), {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Estimated Fuel Cost (₹)',
            data: rows.map(r => r.fuel_cost || 0),
            backgroundColor: '#ea580c',
            borderColor: '#c2410c',
            borderWidth: 1,
            borderRadius: 6,
          }]
        },
        options: {
          ...LIGHT_CHART_OPTS,
          plugins: {
            ...LIGHT_CHART_OPTS.plugins,
            tooltip: {
              ...LIGHT_CHART_OPTS.plugins.tooltip,
              callbacks: { label: c => `₹ ${Number(c.raw).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` }
            }
          },
          scales: {
            ...LIGHT_CHART_OPTS.scales,
            y: { ...LIGHT_CHART_OPTS.scales.y, title: { display: true, text: 'Cost (₹)', color: '#94a3b8', font: { size: 10 } }, min: 0 }
          }
        }
      });
    }
  } catch(e) {}
}

// ── Yahoo Finance-Style Running Time & Cost Trend Chart ────
async function loadTrend(hours) {
  try {
    const res = await fetch(`/api/history?hours=${hours}`, { cache: 'no-store' });
    const { rows } = await res.json();
    
    // Compute actual cumulative running time (hrs) and fuel cost (₹)
    let totalRuntimeHrs = 0;
    let totalCostRs = 0;
    
    const processedRows = (rows || []).map((r, i) => {
      if (i > 0) {
        const tPrev = new Date(rows[i-1].ts).getTime();
        const tCurr = new Date(r.ts).getTime();
        const dtHours = (tCurr - tPrev) / 3600000;
        
        const isRunning = r.is_running || r.genset_state === 'Running' || (r.engine_speed_rpm && r.engine_speed_rpm > 500);
        if (isRunning && dtHours > 0 && dtHours < 0.25) {
          totalRuntimeHrs += dtHours;
          totalCostRs += dtHours * 8.5 * 96.0; // 8.5 LPH * ₹96/L
        }
      }
      return {
        ts: r.ts,
        runtime: Number(totalRuntimeHrs.toFixed(2)),
        cost: Number(totalCostRs.toFixed(2)),
        kw: r.total_kw || 0,
        fuel: r.fuel_level_pct || 0
      };
    });

    const ds = downsample(processedRows, 600);
    const labels = ds.map(r => fmtTs(r.ts));
    destroyChart('trend');

    const canvas = el('trendChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const greenGrad = ctx.createLinearGradient(0, 0, 0, 260);
    greenGrad.addColorStop(0, 'rgba(22, 163, 74, 0.35)');
    greenGrad.addColorStop(1, 'rgba(22, 163, 74, 0.01)');

    const redGrad = ctx.createLinearGradient(0, 0, 0, 260);
    redGrad.addColorStop(0, 'rgba(220, 38, 38, 0.25)');
    redGrad.addColorStop(1, 'rgba(220, 38, 38, 0.01)');

    _charts.trend = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Running Time (hrs)',
            data: ds.map(r => r.runtime),
            borderColor: '#16a34a',
            backgroundColor: greenGrad,
            borderWidth: 2.5,
            tension: 0.3,
            fill: true,
            pointRadius: ds.length > 80 ? 0 : 2,
            pointHoverRadius: 6,
            yAxisID: 'y'
          },
          {
            label: 'Estimated Fuel Cost (₹)',
            data: ds.map(r => r.cost),
            borderColor: '#dc2626',
            backgroundColor: redGrad,
            borderWidth: 2.5,
            tension: 0.3,
            fill: true,
            pointRadius: ds.length > 80 ? 0 : 2,
            pointHoverRadius: 6,
            yAxisID: 'y2'
          }
        ]
      },
      options: {
        ...LIGHT_CHART_OPTS,
        plugins: {
          ...LIGHT_CHART_OPTS.plugins,
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: '#0f172a',
            titleColor: '#f8fafc',
            bodyColor: '#cbd5e1',
            borderColor: '#334155',
            borderWidth: 1,
            padding: 12,
            boxPadding: 6,
            usePointStyle: true,
            callbacks: {
              title: items => items[0] ? `⏱ ${items[0].label}` : '',
              label: ctx => {
                if (ctx.datasetIndex === 0) {
                  return `  Running Time: ${Number(ctx.raw).toFixed(2)} hrs`;
                } else {
                  return `  Estimated Fuel Cost: ₹ ${Number(ctx.raw).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                }
              }
            }
          },
          zoom: {
            pan: {
              enabled: true,
              mode: 'x'
            },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              mode: 'x'
            }
          }
        },
        scales: {
          x: {
            ...LIGHT_CHART_OPTS.scales.x,
            grid: { color: '#f1f5f9' }
          },
          y: {
            type: 'linear',
            display: true,
            position: 'left',
            title: { display: true, text: 'Running Time (hrs)', color: '#2563eb', font: { size: 11, weight: '700' } },
            ticks: { color: '#475569', font: { size: 10 }, callback: v => v + ' hrs' },
            grid: { color: '#f1f5f9' },
            min: 0
          },
          y2: {
            type: 'linear',
            display: true,
            position: 'right',
            title: { display: true, text: 'Fuel Cost (₹)', color: '#ea580c', font: { size: 11, weight: '700' } },
            ticks: { color: '#475569', font: { size: 10 }, callback: v => '₹' + v },
            grid: { drawOnChartArea: false },
            min: 0
          }
        }
      }
    });
  } catch(e) {
    console.error('loadTrend error:', e);
  }
}

function resetTrendZoom() {
  if (_charts.trend && typeof _charts.trend.resetZoom === 'function') {
    _charts.trend.resetZoom();
  }
}

// ── Documents Loader ───────────────────────────────────────
const DOC_ICONS = { financial: '💰', technical: '🔧', AMC: '📋', support: '📞' };

async function loadDocs() {
  try {
    const docs = await (await fetch('/api/documents', { cache: 'no-store' })).json();
    const grid = el('docsGrid');
    if (!docs || !docs.length) {
      grid.innerHTML = `
        <div class="doc-box">
          <div class="doc-title">💰 Financial & Invoices</div>
          <div class="doc-empty">No invoices attached</div>
        </div>
        <div class="doc-box">
          <div class="doc-title">🔧 Technical Manuals</div>
          <div class="doc-empty">No manuals attached</div>
        </div>
        <div class="doc-box">
          <div class="doc-title">📋 AMC & Contracts</div>
          <div class="doc-empty">No contracts attached</div>
        </div>
        <div class="doc-box">
          <div class="doc-title">📞 Vendor Contacts</div>
          <div class="doc-empty">No contacts recorded</div>
        </div>`;
      return;
    }
    const cats = {};
    docs.forEach(d => {
      const c = d.category || 'General';
      if (!cats[c]) cats[c] = [];
      cats[c].push(d);
    });
    grid.innerHTML = Object.entries(cats).map(([cat, items]) => `
      <div class="doc-box">
        <div class="doc-title">${DOC_ICONS[cat] || '📄'} ${cat}</div>
        ${items.map(d => `<a href="${d.url}" target="_blank" class="doc-link">📎 ${d.title}</a>`).join('')}
      </div>`).join('');
  } catch(e) {}
}

// ── Boot ───────────────────────────────────────────────────
updateClock();
initAudioUI();
initPhasePieCharts();
initLineVoltPie();
updateStatus();
loadVoltChart(6);
loadKpi(6, 'runtime');
loadKpi(6, 'cost');
loadTrend(168);
loadDocs();

setInterval(updateClock, 1000);
setInterval(updateStatus, 3000);
setInterval(() => loadDocs(), 60000);
</script>
</body>
</html>
"""
