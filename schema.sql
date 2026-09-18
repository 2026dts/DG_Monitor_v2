-- =============================================================
-- DG Monitoring Platform v2 — PostgreSQL Schema
-- Covers: telemetry, runtime tracking, fuel cost KPIs,
--         alarm episodes, ThingsBoard selective publishing
-- =============================================================

-- =============================================================
-- ASSETS — one row per DG unit (extend later for multi-DG)
-- =============================================================
CREATE TABLE IF NOT EXISTS dg_assets (
    id                  SERIAL PRIMARY KEY,
    asset_key           TEXT NOT NULL UNIQUE DEFAULT 'dg1',
    device_name         TEXT NOT NULL DEFAULT 'DG Status',
    model               TEXT DEFAULT 'Cummins PS0600 / PCC1301',
    usr_ip              TEXT,
    usr_port            INTEGER DEFAULT 8899,
    slave_id            INTEGER DEFAULT 1,
    fuel_cost_per_litre NUMERIC(10,2) DEFAULT 0,   -- ₹ per litre, set once
    fuel_consumption_lph NUMERIC(8,3) DEFAULT 0,   -- litres per hour at rated load
    installed_on        DATE DEFAULT CURRENT_DATE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default DG unit
INSERT INTO dg_assets (asset_key, device_name, model, usr_ip, usr_port, slave_id)
VALUES ('dg1', 'DG Status', 'Cummins PS0600 / PCC1301', '10.10.10.77', 8899, 1)
ON CONFLICT (asset_key) DO NOTHING;

-- =============================================================
-- TELEMETRY — every Modbus register sweep (high-frequency)
-- =============================================================
CREATE TABLE IF NOT EXISTS dg_telemetry (
    id                      BIGSERIAL,
    asset_id                INTEGER NOT NULL REFERENCES dg_assets(id) ON DELETE CASCADE,
    ts                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Status / enums (stored as text for readability)
    genset_state            TEXT,       -- 'Running', 'Stop', 'Off', …
    control_switch          TEXT,       -- 'Auto', 'Manual', 'Off'
    current_fault_severity  TEXT,       -- 'None', 'Warning', 'Shutdown'
    current_fault_number    NUMERIC(6),
    start_attempts          NUMERIC(6),
    is_running              BOOLEAN DEFAULT FALSE,

    -- Engine
    engine_speed_rpm        NUMERIC(10,3),
    battery_voltage_v       NUMERIC(10,3),
    oil_pressure_psi        NUMERIC(10,3),
    coolant_temp_f          NUMERIC(10,3),

    -- Fuel
    fuel_level_pct          NUMERIC(6,2),

    -- Frequency
    frequency_hz            NUMERIC(8,3),

    -- Phase voltages (L-N)
    l1n_voltage_v           NUMERIC(8,2),
    l2n_voltage_v           NUMERIC(8,2),
    l3n_voltage_v           NUMERIC(8,2),

    -- Line voltages (L-L)
    l1l2_voltage_v          NUMERIC(8,2),
    l2l3_voltage_v          NUMERIC(8,2),
    l3l1_voltage_v          NUMERIC(8,2),

    -- Currents
    l1_current_a            NUMERIC(8,2),
    l2_current_a            NUMERIC(8,2),
    l3_current_a            NUMERIC(8,2),
    l1_current_pct          NUMERIC(6,2),
    l2_current_pct          NUMERIC(6,2),
    l3_current_pct          NUMERIC(6,2),

    -- Power
    l1_kw                   NUMERIC(10,3),
    l2_kw                   NUMERIC(10,3),
    l3_kw                   NUMERIC(10,3),
    total_kw                NUMERIC(10,3),
    l1_kvar                 NUMERIC(10,3),
    l2_kvar                 NUMERIC(10,3),
    l3_kvar                 NUMERIC(10,3),
    total_kvar              NUMERIC(10,3),
    l1_kva                  NUMERIC(10,3),
    l2_kva                  NUMERIC(10,3),
    l3_kva                  NUMERIC(10,3),
    total_kva               NUMERIC(10,3),

    PRIMARY KEY (id, ts)
);

CREATE INDEX IF NOT EXISTS idx_dg_telem_asset_ts
    ON dg_telemetry (asset_id, ts DESC);

-- Partial index: quick lookup of running periods
CREATE INDEX IF NOT EXISTS idx_dg_telem_running
    ON dg_telemetry (asset_id, ts DESC)
    WHERE is_running = TRUE;

-- =============================================================
-- RUNTIME SESSIONS — one row per generator run (start → stop)
-- Used for per-session runtime hours and fuel cost calculation
-- =============================================================
CREATE TABLE IF NOT EXISTS dg_run_sessions (
    id              SERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES dg_assets(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,               -- NULL while still running
    duration_hours  NUMERIC(10,4),             -- computed on close
    fuel_used_litres NUMERIC(10,3),            -- duration_hours × fuel_consumption_lph
    fuel_cost       NUMERIC(12,2),             -- fuel_used × cost_per_litre
    fuel_start_pct  NUMERIC(6,2),              -- fuel level at start
    fuel_end_pct    NUMERIC(6,2),              -- fuel level at end
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_dg_sessions_asset
    ON dg_run_sessions (asset_id, started_at DESC);

-- =============================================================
-- MONTHLY KPI ROLLUP — pre-computed monthly stats
-- Updated by the worker after each session closes
-- =============================================================
CREATE TABLE IF NOT EXISTS dg_monthly_kpi (
    asset_id        INTEGER NOT NULL REFERENCES dg_assets(id) ON DELETE CASCADE,
    month           DATE NOT NULL,             -- always 1st of the month
    runtime_hours   NUMERIC(10,2) DEFAULT 0,
    session_count   INTEGER DEFAULT 0,
    fuel_cost       NUMERIC(12,2) DEFAULT 0,
    fuel_used_litres NUMERIC(10,3) DEFAULT 0,
    PRIMARY KEY (asset_id, month)
);

-- =============================================================
-- ALARMS — open/clear episodes
-- =============================================================
CREATE TABLE IF NOT EXISTS dg_alarms (
    id              SERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES dg_assets(id) ON DELETE CASCADE,
    alarm_type      TEXT NOT NULL,
    -- 'low_fuel' | 'control_manual' | 'freq_out_of_band' |
    -- 'battery_low_v' | 'high_coolant_temp' | 'low_oil_pressure'
    severity        TEXT NOT NULL DEFAULT 'critical',
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cleared_at      TIMESTAMPTZ,
    read_at         TIMESTAMPTZ,
    notified_at     TIMESTAMPTZ,
    notify_count    INTEGER DEFAULT 0,
    extra           JSONB
);

CREATE INDEX IF NOT EXISTS idx_dg_alarms_open
    ON dg_alarms (asset_id, opened_at DESC)
    WHERE cleared_at IS NULL;

-- =============================================================
-- DOCUMENTS — links to AMC / financial / technical / support
-- =============================================================
CREATE TABLE IF NOT EXISTS dg_documents (
    id          SERIAL PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES dg_assets(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,   -- 'financial' | 'technical' | 'AMC' | 'support'
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- USEFUL VIEWS
-- =============================================================

-- Latest reading per asset
CREATE OR REPLACE VIEW dg_latest AS
SELECT DISTINCT ON (asset_id)
    t.*,
    a.device_name,
    a.usr_ip,
    a.usr_port
FROM dg_telemetry t
JOIN dg_assets a ON a.id = t.asset_id
ORDER BY asset_id, ts DESC;

-- Open alarms with device name
CREATE OR REPLACE VIEW dg_open_alarms AS
SELECT al.*, a.device_name
FROM dg_alarms al
JOIN dg_assets a ON a.id = al.asset_id
WHERE al.cleared_at IS NULL
ORDER BY al.opened_at DESC;

-- Active run session (generator currently running)
CREATE OR REPLACE VIEW dg_active_session AS
SELECT s.*, a.device_name
FROM dg_run_sessions s
JOIN dg_assets a ON a.id = s.asset_id
WHERE s.ended_at IS NULL
ORDER BY s.started_at DESC
LIMIT 1;
