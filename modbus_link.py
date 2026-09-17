"""
Modbus RTU-over-TCP link to the PCC1301/PS0600 controller, through the
USR-W630's transparent TCP passthrough. This replaces the original
script's ModbusSerialClient(COM port) with ModbusTcpClient using an
RTU framer - the USR-W630 carries raw RTU bytes over the TCP socket,
it does not wrap them in a Modbus-TCP (MBAP) header, so the framer
must stay RTU even though the transport is TCP.
"""

from threading import Lock

from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient

from config import USR_IP, USR_PORT, SLAVE_ID, TCP_TIMEOUT
from register_map import PARAMETERS, decode_value, numeric_value, format_value


modbus_client = None
modbus_lock = Lock()


def connect_modbus():
    global modbus_client

    close_connection()

    client = ModbusTcpClient(
        host=USR_IP,
        port=USR_PORT,
        framer=FramerType.RTU,
        timeout=TCP_TIMEOUT,
    )

    if not client.connect():
        return False, f"Connection failed: cannot reach {USR_IP}:{USR_PORT}"

    modbus_client = client
    return True, f"Connected: {USR_IP}:{USR_PORT} | Slave ID {SLAVE_ID}"


def close_connection():
    global modbus_client

    if modbus_client:
        try:
            modbus_client.close()
        except Exception:
            pass

    modbus_client = None


def is_connected():
    global modbus_client
    if modbus_client is None:
        return False
    try:
        return bool(getattr(modbus_client, "connected", False))
    except Exception:
        return False


def read_all_parameters():
    global modbus_client
    if modbus_client is None or not is_connected():
        return [], "Not connected"

    results = []

    with modbus_lock:
        for name, map_register, address, data_type, scale, unit in PARAMETERS:
            try:
                response = modbus_client.read_holding_registers(
                    address=address,
                    count=1,
                    device_id=SLAVE_ID,
                )

                if response.isError():
                    results.append({
                        "name": name,
                        "map_register": map_register,
                        "address": address,
                        "raw": "",
                        "scaled": "",
                        "numeric": None,
                        "unit": unit,
                        "status": str(response),
                    })
                    continue

                raw = response.registers[0]
                decoded = decode_value(raw, data_type, scale)

                results.append({
                    "name": name,
                    "map_register": map_register,
                    "address": address,
                    "raw": raw,
                    "scaled": format_value(decoded),
                    "numeric": numeric_value(decoded),
                    "unit": unit,
                    "status": "OK",
                })

            except Exception as exc:
                results.append({
                    "name": name,
                    "map_register": map_register,
                    "address": address,
                    "raw": "",
                    "scaled": "",
                    "numeric": None,
                    "unit": unit,
                    "status": f"Error: {exc}",
                })

    return results, "Read completed"


def extract_live_values(results):
    values = {}

    for row in results:
        if row["status"] == "OK":
            if row["numeric"] is not None:
                values[row["name"]] = row["numeric"]
            else:
                values[row["name"]] = row["scaled"]

    return values

