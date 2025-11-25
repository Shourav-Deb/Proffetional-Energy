from pathlib import Path
from datetime import datetime, timedelta, time as dtime

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.express as px

from devices import load_devices, save_devices, get_device_by_id, group_devices_by_floor
from get_power_data import fetch_and_log_once
from tuya_api import control_device, get_token
from tuya_api_mongo import latest_docs, range_docs, get_client, MONGODB_URI
from billing import (
    daily_monthly_for,
    aggregate_totals_all_devices,
    aggregate_timeseries_24h,
    aggregate_timeseries_for_day,
)
from schedules import (
    list_schedules,
    create_schedule,
    update_schedule_active,
    delete_schedule,
    run_due_schedules,
)

# Page setup

st.set_page_config(
    page_title="Deb IoT Analyzer",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DATA_DIR = Path("data")


st.markdown(
    """
    <style>
    :root {
        --accent: #22c55e;
        --accent-soft: rgba(34,197,94,0.16);
        --bg-main: #020617;
        --bg-elevated: rgba(15,23,42,0.96);
        --border-subtle: rgba(148,163,184,0.18);
    }

    body {
        background: radial-gradient(circle at top, #111827 0, #020617 40%, #020617 100%);
    }

    .main .block-container {
        padding-top: 0.5rem;
        padding-bottom: 1.5rem;
        max-width: 1200px;
    }

    .top-shell {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.6rem 0.3rem 0.9rem;
        border-radius: 1rem;
        margin-bottom: 0.6rem;
    }

    .app-brand {
        display: flex;
        align-items: center;
        gap: 0.7rem;
    }

    .logo-dot {
        width: 32px;
        height: 32px;
        border-radius: 999px;
        background: radial-gradient(circle at 30% 20%, #22c55e, #16a34a, #15803d);
        box-shadow: 0 0 18px rgba(34,197,94,0.5);
    }

    .app-title {
        font-size: 1.4rem;
        font-weight: 700;
        letter-spacing: 0.03em;
    }

    .app-subtitle {
        font-size: 0.8rem;
        color: #9ca3af;
    }

    .top-tagline {
        font-size: 0.82rem;
        color: #9ca3af;
        padding: 0.25rem 0.75rem;
        border-radius: 999px;
        border: 1px solid var(--border-subtle);
        background: rgba(15,23,42,0.9);
    }

    .big-title {
        font-size: 1.5rem;
        font-weight: 650;
        margin-bottom: 0.1rem;
    }

    .subtitle {
        color: #9ca3af;
        font-size: 0.9rem;
        margin-bottom: 1.2rem;
    }

    .card {
        padding: 0.9rem 1.1rem;
        border-radius: 1rem;
        background: linear-gradient(
            135deg,
            rgba(15,23,42,0.98),
            rgba(15,23,42,0.9)
        );
        border: 1px solid var(--border-subtle);
        box-shadow:
            0 18px 40px rgba(15,23,42,0.8),
            0 0 0 1px rgba(15,23,42,0.4);
    }

    .card h3 {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.13em;
        color: #9ca3af;
        margin-bottom: 0.2rem;
    }

    .card .value {
        font-size: 1.35rem;
        font-weight: 650;
    }

    .pill {
        display: inline-flex;
        align-items: center;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        border: 1px solid var(--border-subtle);
        font-size: 0.78rem;
        color: #9ca3af;
        gap: 0.4rem;
        background: rgba(15,23,42,0.9);
    }

    .floor-badge {
        font-size: 0.8rem;
        padding: 0.15rem 0.65rem;
        border-radius: 999px;
        background: rgba(15,23,42,0.96);
        border: 1px solid var(--border-subtle);
        color: #9ca3af;
    }

    .stButton>button {
        border-radius: 999px;
        border: 1px solid var(--border-subtle);
        background: rgba(15,23,42,0.95);
        color: #e5e7eb;
        font-size: 0.85rem;
        padding: 0.25rem 0.9rem;
    }
    .stButton>button:hover {
        border-color: rgba(34,197,94,0.7);
        box-shadow: 0 0 0 1px rgba(34,197,94,0.4);
    }

    .top-nav-label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: #6b7280;
        margin-bottom: 0.1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Session state defaults
if "page" not in st.session_state:
    st.session_state.page = "home"
if "current_device_id" not in st.session_state:
    st.session_state.current_device_id = None
if "current_device_name" not in st.session_state:
    st.session_state.current_device_name = None


def go(page: str):
    """Programmatic navigation to a main page."""
    st.session_state.page = page


def go_device(device_id: str, device_name: str):
    """Go to per-device dashboard."""
    st.session_state.current_device_id = device_id
    st.session_state.current_device_name = device_name
    st.session_state.page = "device_detail"


# Sidebar: system status

try:
    _client = get_client()
    mongo_ok = _client is not None
except Exception as _e:
    mongo_ok = False
    mongo_err = str(_e)
else:
    mongo_err = ""

with st.sidebar:
    st.markdown("### System status")
    st.write("Mongo URI set:", bool(MONGODB_URI))
    st.write("Connected:", mongo_ok)
    if not mongo_ok:
        st.caption("Check MONGODB_URI in secrets / .env")
    st.markdown("---")
    st.caption("FUB BEMS · Realtime Tuya + MongoDB")


run_due_schedules()

# Top header + navigation

def render_top_nav():
    st.markdown(
        """
        <div class="top-shell">
          <div class="app-brand">
            <div class="logo-dot"></div>
            <div>
              <div class="app-title">FUB Monitor System </div>
              <div class="app-subtitle">Realtime Energy Monitoring For The FUB Building</div>
            </div>
          </div>
          <div class="top-tagline">
            Powered by Shourav Deb
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="top-nav-label">MAIN SECTIONS</div>', unsafe_allow_html=True)

    cols = st.columns([1, 1, 1, 1, 1, 2])
    nav_items = [
        ("home", "Overview"),
        ("devices", "Devices"),
        ("add_device", "Add device"),
        ("manage_devices", "Manage"),
        ("reports", "Analytics"),
        
    ]
    current = st.session_state.get("page", "home")

    for idx, (page_key, label) in enumerate(nav_items):
        is_active = (current == page_key) or (current == "device_detail" and page_key == "devices")
        btn_label = f"● {label}" if is_active else label
        with cols[idx]:
            if st.button(btn_label, key=f"topnav_{page_key}"):
                go(page_key)
                st.rerun()

    # Help button aligned right
    with cols[-1]:
        if st.button("Help / Manual", key="topnav_help"):
            go("help")
            st.rerun()


# Pages

def home_page():
    devices = load_devices()

    st.markdown('<div class="big-title">Building overview</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Live status and historical profile of the FUB building with billing info.</div>',
        unsafe_allow_html=True,
    )

    if not devices:
        st.info("No devices yet. Use **Add device** from the top navigation to register at least one Tuya plug.")
        return

    tabs = st.tabs(["Today (live)", "History by day"])

    # -------------------- TODAY TAB --------------------
    with tabs[0]:
        (
            total_power_now,
            present_voltage,
            today_kwh,
            today_bill,
            month_kwh,
            month_bill,
        ) = aggregate_totals_all_devices(devices)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("<h3>Instant Load</h3>", unsafe_allow_html=True)
            st.markdown(f'<div class="value">{total_power_now:.1f} W</div>', unsafe_allow_html=True)
            st.caption(f"Max phase voltage: {present_voltage:.1f} V")
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("<h3>Today Usage</h3>", unsafe_allow_html=True)
            st.markdown(
                f'<div class="value">{today_kwh:.3f} kWh</div>', unsafe_allow_html=True
            )
            st.caption(f"Estimated bill today: **{today_bill:.2f} BDT** (domestic slab)")
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("<h3>This month</h3>", unsafe_allow_html=True)
            st.markdown(
                f'<div class="value">{month_kwh:.3f} kWh</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"Projected bill so far: **{month_bill:.2f} BDT**")
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("")

        # Floor aggregation tiles
        st.markdown("#### Floors summary")
        floors = group_devices_by_floor()
        if not floors:
            st.caption("No floor metadata yet. Use device mapping (building/floor/room) to enable this.")
        else:
            for key, floor_devs in floors.items():
                building, floor = key.split("-", 1)
                (
                    f_power,
                    f_voltage,
                    f_today_kwh,
                    f_today_bill,
                    f_month_kwh,
                    f_month_bill,
                ) = aggregate_totals_all_devices(floor_devs)
                with st.expander(f"{building} · Floor {floor}", expanded=False):
                    fc1, fc2, fc3 = st.columns(3)
                    with fc1:
                        st.metric("Instant load", f"{f_power:.1f} W")
                        st.caption(f"Voltage: {f_voltage:.1f} V")
                    with fc2:
                        st.metric("Today (kWh)", f"{f_today_kwh:.3f}")
                        st.caption(f"Today bill: {f_today_bill:.2f} BDT")
                    with fc3:
                        st.metric("Month (kWh)", f"{f_month_kwh:.3f}")
                        st.caption(f"Month bill: {f_month_bill:.2f} BDT")

        st.markdown("")
        col_l, col_r = st.columns([3, 1])
        with col_l:
            st.markdown("#### Last 24 hours (building profile)")
            ts = aggregate_timeseries_24h(devices, resample_rule="5T")
            if ts.empty:
                st.info(
                    "No historical data in MongoDB yet.\n\n"
                    "- Open a device page and wait a few refreshes, or\n"
                    "- Run `data_collector.py`."
                )
            else:
                fig = px.line(
                    ts,
                    x="timestamp",
                    y=["power_sum_W", "voltage_avg_V"],
                    labels={"value": "Value", "variable": "Metric"},
                )
                fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), legend_title_text="")
                st.plotly_chart(fig, use_container_width=True)

        with col_r:
            st.markdown("#### Quick actions")
            if st.button("View devices list"):
                go("devices")
                st.rerun()
            if st.button("Add new plug"):
                go("add_device")
                st.rerun()
            st.markdown("---")
            st.markdown(
                '<span class="pill">Connected plugs: '
                f'{len(devices)}</span>',
                unsafe_allow_html=True,
            )

    # -------------------- HISTORY TAB --------------------
    with tabs[1]:
        today = datetime.now().date()
        hist_date = st.date_input(
            "Select date",
            value=today,
            max_value=today,
        )
        st.caption("Data will be cleared while extra load.")

        h_ts = aggregate_timeseries_for_day(devices, hist_date, resample_rule="15T")
        if h_ts.empty:
            st.info("No data recorded for this day yet.")
        else:
            h_fig = px.line(
                h_ts,
                x="timestamp",
                y=["power_sum_W", "voltage_avg_V"],
                labels={"value": "Value", "variable": "Metric"},
                title=f"Building profile for {hist_date.isoformat()}",
            )
            h_fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), legend_title_text="")
            st.plotly_chart(h_fig, use_container_width=True)


def devices_page():
    st.markdown('<div class="big-title">Devices</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Each card represents a Tuya smart plug mapped to a FUB room.</div>',
        unsafe_allow_html=True,
    )

    devs = load_devices()
    if not devs:
        st.info("No devices found. Use **Add device** from the top navigation.")
        return

    for d in devs:
        building = d.get("building", "FUB")
        floor = d.get("floor", "?")
        room = d.get("room", "?")
        with st.container():
            col1, col2, col3 = st.columns([4, 3, 2])
            with col1:
                st.markdown(
                    f"**{d.get('name','(no name)')}**  \n"
                    f"`{d.get('id')}`  \n"
                    f"<span class='floor-badge'>{building} · Floor {floor} · Room {room}</span>",
                    unsafe_allow_html=True,
                )
            with col2:
                df_recent = latest_docs(d["id"], n=1)
                if not df_recent.empty:
                    row = df_recent.iloc[-1]
                    st.caption(
                        f"Last: {row.get('power', 0):.1f} W @ "
                        f"{row.get('voltage', 0):.1f} V"
                    )
                else:
                    st.caption("No readings stored yet.")
            with col3:
                if st.button("Open dashboard", key=f"view_{d['id']}"):
                    go_device(d["id"], d.get("name", "Device"))
                    st.rerun()
        st.markdown("---")


def add_device_page():
    st.markdown('<div class="big-title">Add device</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Register a Tuya plug with its device ID and map it to the FUB building layout.</div>',
        unsafe_allow_html=True,
    )

    with st.form("add_device_form"):
        name = st.text_input("Friendly Name (e.g., FUB 402 - Lab AC)")
        device_id = st.text_input("Tuya Device ID")
        building = st.text_input("Building Code", value="FUB")
        floor = st.text_input("Floor (e.g., 4)")
        room = st.text_input("Room (e.g., 401)")
        capacity = st.number_input("Room Capacity (optional)", min_value=0, value=0, step=1)
        submitted = st.form_submit_button("Add device")

    if submitted:
        if not device_id.strip():
            st.error("Device ID is required.")
        else:
            devs = load_devices()
            devs.append(
                {
                    "name": name or device_id,
                    "id": device_id.strip(),
                    "building": building.strip() or "FUB",
                    "floor": floor.strip() or "?",
                    "room": room.strip() or "?",
                    "capacity": int(capacity),
                }
            )
            save_devices(devs)
            st.success("Device added successfully.")
            st.info("Now open **Devices** and click the new device to start logging data.")


def manage_devices_page():
    st.markdown('<div class="big-title">Manage devices</div>', unsafe_allow_html=True)
    devs = load_devices()
    if not devs:
        st.info("No devices to manage yet.")
        return

    to_keep = []
    for d in devs:
        col1, col2 = st.columns([5, 1])
        with col1:
            st.write(
                f"**{d.get('name','(no name)')}** – `{d.get('id')}` "
                f"({d.get('building','FUB')} · Floor {d.get('floor','?')} · Room {d.get('room','?')})"
            )
        with col2:
            keep = not st.checkbox("Delete", key=f"del_{d['id']}")
        if keep:
            to_keep.append(d)

    if st.button("Save changes"):
        save_devices(to_keep)
        st.success("Device list updated.")


def _render_schedule_editor(device_id: str, dev_meta: dict):
    st.markdown("### Schedule control (auto ON/OFF)")
    st.caption(
        "Create one-time or weekly schedules. On each refresh, the app checks due schedules and "
        "sends ON/OFF commands to the plug."
    )

    existing = list_schedules(device_id)
    if existing:
        st.markdown("#### Existing schedules")
        for s in existing:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            with col1:
                kind = s.get("kind", "once")
                action = s.get("action", "off")
                label = "One-time" if kind == "once" else "Weekly"
                st.write(f"**{label} · {action.upper()}**")
                if kind == "once":
                    st.caption(f"On {s.get('date')} at {s.get('time_str')}")
                else:
                    days = s.get("weekdays", [])
                    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    names = [day_names[i] for i in days if 0 <= i < 7]
                    st.caption(f"{', '.join(names)} at {s.get('time_str')}")
            with col2:
                st.caption(f"Active: {s.get('is_active', True)}")
            with col3:
                st.caption(f"Last run: {s.get('last_run_at')}")
            with col4:
                sid = str(s.get("_id"))
                toggle = st.checkbox(
                    "Active",
                    value=s.get("is_active", True),
                    key=f"sch_active_{sid}",
                )
                update_schedule_active(sid, toggle)
                if st.button("🗑", key=f"sch_del_{sid}"):
                    delete_schedule(sid)
                    st.experimental_rerun()

    st.markdown("#### Add new schedule")

    with st.form("schedule_form"):
        kind = st.selectbox("Type", ["Once", "Weekly"])
        action = st.selectbox("Action", ["Turn ON", "Turn OFF"])
        time_value = st.time_input("Time of day", value=dtime(hour=9, minute=0))

        date_value = None
        weekdays = None
        if kind == "Once":
            date_value = st.date_input("Date")
        else:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            weekdays_sel = st.multiselect("Weekdays", day_names, default=["Sun", "Mon", "Tue", "Wed", "Thu"])
            weekdays = [day_names.index(d) for d in weekdays_sel]

        submitted = st.form_submit_button("Create schedule")

    if submitted:
        kind_key = "once" if kind == "Once" else "weekly"
        action_key = "on" if "ON" in action else "off"
        building = dev_meta.get("building", "FUB")
        floor = dev_meta.get("floor", "?")
        room = dev_meta.get("room", "?")
        sid = create_schedule(
            device_id=device_id,
            device_name=dev_meta.get("name", device_id),
            building=building,
            floor=floor,
            room=room,
            action=action_key,
            kind=kind_key,
            date_value=date_value,
            time_value=time_value,
            weekdays=weekdays,
        )
        if sid:
            st.success("Schedule created.")
            st.experimental_rerun()
        else:
            st.error("Failed to create schedule. Check Mongo connection.")


def device_detail_page():
    dev_id = st.session_state.current_device_id
    dev_name = st.session_state.current_device_name or dev_id

    if not dev_id:
        st.warning("No device selected. Open **Devices** and choose one.")
        return

    dev_meta = get_device_by_id(dev_id) or {}
    building = dev_meta.get("building", "FUB")
    floor = dev_meta.get("floor", "?")
    room = dev_meta.get("room", "?")

    st_autorefresh(interval=30_000, key="device_autorefresh")

    st.markdown(
        f'<div class="big-title">Device: {dev_name}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"{dev_id} · {building} · Floor {floor} · Room {room}")

    
    try:
        fetch_and_log_once(dev_id, dev_name)
    except Exception as e:
        st.error(f"Tuya API error while logging data: {e}")

    tabs = st.tabs(["Today (live)", "History & billing", "Schedules"])

    # -------------------- TODAY TAB --------------------
    with tabs[0]:
        top1, top2 = st.columns([2, 1])

        with top1:
            st.markdown("#### Live snapshot")
            df_recent = latest_docs(dev_id, n=20)
            if not df_recent.empty:
                last = df_recent.iloc[-1]
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Power", f"{float(last.get('power', 0)):.1f} W")
                with c2:
                    st.metric("Voltage", f"{float(last.get('voltage', 0)):.1f} V")
                with c3:
                    st.metric("Current", f"{float(last.get('current', 0)):.3f} A")
            else:
                st.info("No readings stored yet for this device.")

        with top2:
            st.markdown("#### Manual control")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Turn ON"):
                    token = get_token()
                    res = control_device(dev_id, token, "switch_1", True)
                    st.json(res)
            with c2:
                if st.button("Turn OFF"):
                    token = get_token()
                    res = control_device(dev_id, token, "switch_1", False)
                    st.json(res)

        st.markdown("### Recent power (last 50 samples)")
        df_recent = latest_docs(dev_id, n=50)
        if not df_recent.empty:
            fig = px.line(df_recent, x="timestamp", y="power", title="")
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data yet. Leave this page open for a few refresh cycles.")

    # -------------------- HISTORY & BILLING TAB --------------------
    with tabs[1]:
        st.markdown("### Billing estimate (Bangladesh slabs)")
        d_units, d_cost, m_units, m_cost = daily_monthly_for(dev_id)
        b1, b2 = st.columns(2)
        with b1:
            st.metric("Today (kWh)", f"{d_units:.3f}")
            st.metric("Today (BDT)", f"{d_cost:.2f}")
        with b2:
            st.metric("This month (kWh)", f"{m_units:.3f}")
            st.metric("This month (BDT)", f"{m_cost:.2f}")
        st.caption("Billing uses Bangladesh domestic slab rates (EL-B-A).")

        st.markdown("### Historical analysis by date range")
        c1, c2, c3 = st.columns(3)
        today = datetime.now().date()
        with c1:
            start_date = st.date_input(
                "Start date", value=today - timedelta(days=1), max_value=today
            )
        with c2:
            end_date = st.date_input("End date", value=today, max_value=today)
        with c3:
            agg = st.selectbox("Aggregation", ["raw", "1-min", "5-min", "15-min"], index=2)

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        df = range_docs(dev_id, start_dt, end_dt)

        if not df.empty:
            df = df.sort_values("timestamp").set_index("timestamp")
            if agg != "raw":
                rule = {"1-min": "1T", "5-min": "5T", "15-min": "15T"}[agg]
                df = df.resample(rule).mean(numeric_only=True).dropna()

            plot_df = df.reset_index()
            fig = px.line(
                plot_df,
                x="timestamp",
                y="power",
                title=f"Power over time ({agg})",
            )
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.expander("Raw data (tail)").dataframe(plot_df.tail(200))
        else:
            st.info("No data in the selected range.")

    # -------------------- SCHEDULES TAB --------------------
    with tabs[2]:
        _render_schedule_editor(dev_id, dev_meta)


def reports_page():
    st.markdown('<div class="big-title">Analytics & reports</div>', unsafe_allow_html=True)
    st.info(
        "This section is for high-level energy analytics and exporting data for reports. "
        "You can extend this with CSV export, per-floor comparisons, or ML-based forecasts."
    )


def help_page():
    st.markdown('<div class="big-title">User manual — FUB BEMS</div>', unsafe_allow_html=True)

    st.markdown(
        """
        ### 1. What this system does

        This dashboard is a Building Energy Management System (BEMS) prototype for the FUB building.  
        It reads real-time power data from Tuya smart plugs, stores it in MongoDB, and calculates energy
        and bills using Bangladesh electricity tariffs (domestic slabs).

        **Knowledge contact:** `heyneeddev@gmail.com`
        """
    )

    st.markdown(
        """
        ### 2. Main sections

        **Overview**  
        - Shows building total power, energy and bills (today + month).
        - Floor-wise summaries (if devices are mapped with building/floor/room).
        - Live 24h chart and per-day history.

        **Devices**  
        - List of all Tuya plugs with building/floor/room mapping.
        - Last known power and voltage.
        - Open per-device dashboard for room-level analysis.

        **Add device / Manage**  
        - Register new plugs and map them to FUB rooms.
        - Remove or clean up devices.

        **Analytics**  
        - Placeholder for future advanced reports and exports.

        **Device dashboard (from Devices → Open dashboard)**  
        - **Today (live)**: latest power/voltage/current and recent power chart.  
        - **History & billing**: energy and BDT cost for today & this month, date-range chart.  
        - **Schedules**: configure one-time or weekly ON/OFF schedules.
        """
    )

    st.markdown(
        """
        ### 3. Data and billing model

        - Each plug writes records to MongoDB with:
          - timestamp, device_id, device_name
          - voltage, current, power
          - cumulative energy_kWh
        - Daily/monthly energy is computed from the difference in cumulative energy.
        - Bills are computed using Bangladesh domestic slab rates.

        ### 4. Contact

        For questions or improvements:  
        **Email:** `heyneeddev@gmail.com`
        """
    )


# ------------------------------------------------------------------------------------
# Router + render

render_top_nav()

if st.session_state.page == "home":
    home_page()
elif st.session_state.page == "devices":
    devices_page()
elif st.session_state.page == "add_device":
    add_device_page()
elif st.session_state.page == "manage_devices":
    manage_devices_page()
elif st.session_state.page == "device_detail":
    device_detail_page()
elif st.session_state.page == "reports":
    reports_page()
elif st.session_state.page == "help":
    help_page()
else:
    home_page()
