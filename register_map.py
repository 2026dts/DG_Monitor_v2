"""
Cummins PS0600 (PCC1301 controller family) Modbus register map and
pure decode helpers. Registers verified against the official Cummins
"Modbus Register Mapping" doc (A029X159, Issue 26), chapter 15
(PS0600 Modbus Register Map, addresses 400009-400069 confirmed exact
match including multipliers). The fuel level register (zero-based
address 3744) matches PS0600's own native "Fuel Level Percent"
register (map address 403745, multiplier 1, unit Percent) - the
original inline comment calling it a "PCC1301 AUX101" register was
a mislabel, but the numeric address and scale are correct.
"""

# PCC1301 AUX101 Fuel Level
# Map register: 43745
# Pymodbus zero-based address: 43745 - 40001 = 3744
FUEL_MAP_REGISTER = 43745
FUEL_REGISTER_ADDRESS = 3744
FUEL_SCALE = 1.0
FUEL_DATA_TYPE = "uint16"
FUEL_UNIT = "%"

# ============================================================
# Parameter format:
# (title, map_register, zero_based_address, type, scale, unit)
# ============================================================

PARAMETERS = [
    # Status
    ("Application device type", 400009, 8, "uint16", 1.0, ""),
    ("Control switch position", 400010, 9, "enum_switch", 1.0, ""),
    ("Genset state", 400011, 10, "enum_state", 1.0, ""),
    ("Current fault number", 400012, 11, "uint16", 1.0, ""),
    ("Current fault severity", 400013, 12, "enum_fault", 1.0, ""),

    # Voltage
    ("L1-N voltage", 400018, 17, "uint16", 1.0, "V"),
    ("L2-N voltage", 400019, 18, "uint16", 1.0, "V"),
    ("L3-N voltage", 400020, 19, "uint16", 1.0, "V"),

    ("L1-L2 voltage", 400022, 21, "uint16", 1.0, "V"),
    ("L2-L3 voltage", 400023, 22, "uint16", 1.0, "V"),
    ("L3-L1 voltage", 400024, 23, "uint16", 1.0, "V"),

    # Current
    ("L1 current", 400026, 25, "uint16", 1.0, "A"),
    ("L2 current", 400027, 26, "uint16", 1.0, "A"),
    ("L3 current", 400028, 27, "uint16", 1.0, "A"),

    # Power
    ("L1 kW", 400031, 30, "int16", 1.0, "kW"),
    ("L2 kW", 400032, 31, "int16", 1.0, "kW"),
    ("L3 kW", 400033, 32, "int16", 1.0, "kW"),
    ("Total kW", 400034, 33, "int16", 1.0, "kW"),

    ("L1 kVAr", 400035, 34, "int16", 1.0, "kVAr"),
    ("L2 kVAr", 400036, 35, "int16", 1.0, "kVAr"),
    ("L3 kVAr", 400037, 36, "int16", 1.0, "kVAr"),
    ("Total kVAr", 400038, 37, "int16", 1.0, "kVAr"),

    ("L1 kVA", 400040, 39, "uint16", 1.0, "kVA"),
    ("L2 kVA", 400041, 40, "uint16", 1.0, "kVA"),
    ("L3 kVA", 400042, 41, "uint16", 1.0, "kVA"),
    ("Total kVA", 400043, 42, "uint16", 1.0, "kVA"),

    ("Frequency", 400044, 43, "uint16", 0.01, "Hz"),

    # Engine
    ("L1 current percentage", 400058, 57, "uint16", 0.1, "%"),
    ("L2 current percentage", 400059, 58, "uint16", 0.1, "%"),
    ("L3 current percentage", 400060, 59, "uint16", 0.1, "%"),

    ("Battery voltage", 400061, 60, "uint16", 0.001, "V"),
    ("Oil pressure", 400062, 61, "uint16", 0.1, "psi"),
    ("Coolant temperature", 400064, 63, "int16", 0.1, "°F"),
    ("Average engine speed", 400068, 67, "uint16", 0.125, "rpm"),
    ("Start attempts", 400069, 68, "uint16", 1.0, ""),

    # Fuel
    ("Fuel level", FUEL_MAP_REGISTER, FUEL_REGISTER_ADDRESS,
     FUEL_DATA_TYPE, FUEL_SCALE, FUEL_UNIT),
]


CONTROL_SWITCH = {
    0: "Off",
    1: "Auto",
    2: "Manual",
    123: "Off",
    124: "Auto",
    125: "Manual",
}


GENSET_STATE = {
    0: "Off",
    1: "Stop",
    2: "Preheat",
    3: "Precrank",
    4: "Crank",
    5: "Starter Disconnect",
    6: "PreRamp",
    7: "Ramp",
    8: "Running",
    9: "Fault Shutdown",
    10: "Prerun Setup",
    11: "Runtime Setup",
    12: "Factory Test",
    13: "Waiting For Powerdown",
    123: "Off",
    124: "Stop",
    125: "Ready",
    128: "Running",
}


FAULT_SEVERITY = {
    0: "None",
    1: "Warning",
    2: "Shutdown",
}



# ============================================================
# DECODE HELPERS
# ============================================================

def signed16(value):
    return value - 65536 if value >= 32768 else value


def decode_value(raw, data_type, scale):
    if data_type == "int16":
        return signed16(raw) * scale

    if data_type == "enum_switch":
        return CONTROL_SWITCH.get(raw, f"Unknown ({raw})")

    if data_type == "enum_state":
        return GENSET_STATE.get(raw, f"Unknown ({raw})")

    if data_type == "enum_fault":
        return FAULT_SEVERITY.get(raw, f"Unknown ({raw})")

    return raw * scale


def numeric_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    return None


def format_value(value):
    if value is None:
        return ""

    if isinstance(value, float):
        if abs(value) < 10:
            return f"{value:.3f}"
        if abs(value) < 100:
            return f"{value:.2f}"
        return f"{value:.1f}"

    return str(value)


def is_generator_running(genset_state, engine_speed):
    if genset_state == "Running":
        return True

    if engine_speed is not None and engine_speed > 500:
        return True

    return False
