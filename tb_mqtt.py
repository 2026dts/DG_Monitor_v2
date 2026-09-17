"""
ThingsBoard MQTT client — SELECTIVE publish only.
Sends ONLY two parameters: Genset state + Fuel level.
All other telemetry goes to PostgreSQL via db_store.

This is the minimal ThingsBoard footprint requested:
  - genset_state  → for TB email alert rule chains
  - fuel_level_pct → for TB low-fuel rule chain
"""

import json
import socket
import ssl
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import (
    TB_HOST, TB_PORT, TB_ACCESS_TOKEN, TB_USE_TLS,
    TB_TELEMETRY_TOPIC, MQTT_RECONNECT_MIN_DELAY, MQTT_RECONNECT_MAX_DELAY,
)

import logging
logger = logging.getLogger(__name__)

mqtt_connected = False


def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    global mqtt_connected
    mqtt_connected = (reason_code == 0)
    if mqtt_connected:
        logger.info("[TB-MQTT] Connected to %s:%s", TB_HOST, TB_PORT)
        try:
            client.subscribe("v1/devices/me/rpc/request/+")
            client.subscribe("v1/devices/me/attributes")
            # Also subscribe to attributes push from server-side rule chain
            client.subscribe("v1/devices/me/attributes/response/+")
        except Exception as e:
            logger.warning("[TB-MQTT] Subscribe error: %s", e)
    else:
        logger.warning("[TB-MQTT] Connect failed, code: %s", reason_code)


def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str) if payload_str else {}
        logger.info("[TB-MQTT] Received on %s: %s", topic, data)
        import db_store

        # --- Handle tb_email_confirmed field (from ThingsBoard Save Timeseries / Save Attrs node) ---
        # ThingsBoard Rule Chain sends: {"tb_email_confirmed": "genset_running", "tb_email_time": "..."}
        tb_confirmed_type = data.get("tb_email_confirmed")
        if tb_confirmed_type:
            ts = data.get("tb_email_time", "")
            logger.info("[TB-MQTT] Email confirmation received via MQTT for alarm_type=%s", tb_confirmed_type)
            db_store.record_tb_email_confirmation(
                alarm_type=tb_confirmed_type,
                recipients="Divakar & Admin",
                status="sent",
                ts=ts,
            )
            return

        # --- Handle RPC / generic alarm_type field ---
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        alarm_type = (
            data.get("alarm_type")
            or data.get("type")
            or data.get("method")
            or params.get("alarm_type")
            or params.get("type")
        )
        recipients = data.get("recipients") or params.get("recipients") or "Divakar & Admin"
        status = data.get("status") or params.get("status") or "sent"
        db_store.record_tb_email_confirmation(alarm_type=alarm_type, recipients=recipients, status=status)
    except Exception as exc:
        logger.error("[TB-MQTT] Error handling incoming MQTT message: %s", exc)


def on_mqtt_disconnect(client, userdata, flags, reason_code, properties=None):
    global mqtt_connected
    mqtt_connected = False
    logger.warning("[TB-MQTT] Disconnected, code: %s", reason_code)


import time

_mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"dg_mon_{int(time.time())}",
    protocol=mqtt.MQTTv311,
)
_mqtt_client.username_pw_set(TB_ACCESS_TOKEN)

if TB_USE_TLS:
    _mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

_mqtt_client.on_connect = on_mqtt_connect
_mqtt_client.on_disconnect = on_mqtt_disconnect
_mqtt_client.on_message = on_mqtt_message
_mqtt_client.reconnect_delay_set(
    min_delay=MQTT_RECONNECT_MIN_DELAY,
    max_delay=MQTT_RECONNECT_MAX_DELAY,
)


def start_mqtt():
    """Connect to ThingsBoard and start background loop."""
    try:
        _mqtt_client.loop_start()
        _mqtt_client.connect_async(TB_HOST, TB_PORT, keepalive=60)
    except Exception as exc:
        logger.warning("[TB-MQTT] Initial connect failed: %s", exc)


def publish_selective(values: dict):
    """
    Publish ONLY genset_state and fuel_level_pct to ThingsBoard.
    Called by the worker once per poll cycle.
    """
    if not mqtt_connected:
        return

    payload = {
        "Genset state":    values.get("Genset state", "Unknown"),
        "Fuel level":      values.get("Fuel level"),
        "genset_state":    values.get("Genset state", "Unknown"),
        "fuel_level_pct":  values.get("Fuel level"),
    }

    try:
        _mqtt_client.publish(
            TB_TELEMETRY_TOPIC,
            json.dumps(payload),
            qos=0,
        )
        logger.debug("[TB-MQTT] Published selective telemetry (genset_state + fuel_level)")
    except Exception as exc:
        logger.error("[TB-MQTT] Publish failed: %s", exc)
