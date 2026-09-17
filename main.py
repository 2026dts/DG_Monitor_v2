"""
DG Monitor v2 — Entry point.
  - Postgres: full telemetry + KPIs + alarms
  - ThingsBoard: selective (genset_state + fuel_level only)
"""

import logging
import sys
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from config import USR_IP, USR_PORT, SLAVE_ID, WEB_HOST, WEB_PORT, DB_HOST, DB_PORT, DB_NAME, DEVICE_NAME
import db_store
import tb_mqtt
from worker import dg_worker
from web_app import app


if __name__ == "__main__":
    print()
    print("=" * 70)
    print("  DG MONITORING SYSTEM  v2  —  Cummins PS0600 / PCC1301")
    print("=" * 70)
    print(f"  USR-W630    : {USR_IP}:{USR_PORT}  Slave ID={SLAVE_ID}")
    print(f"  Protocol    : Modbus RTU over TCP")
    print(f"  Database    : {DB_HOST}:{DB_PORT}/{DB_NAME}  (PostgreSQL)")
    print(f"  Web         : http://127.0.0.1:{WEB_PORT}")
    print(f"  ThingsBoard : selective (genset_state + fuel_level only)")
    print("=" * 70)
    print()

    # Init Postgres pool
    try:
        db_store.init_pool()
    except Exception as exc:
        logger.critical("Cannot connect to PostgreSQL: %s", exc)
        sys.exit(1)

    # Start ThingsBoard selective MQTT
    tb_mqtt.start_mqtt()


    # Start worker thread
    t = threading.Thread(target=dg_worker, daemon=True, name="dg-worker")
    t.start()
    logger.info("Worker thread started")

    # Start Flask
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, threaded=True)
