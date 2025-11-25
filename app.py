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

# ------------------------------------------------------------------------------------
# Page setup

st.set_page_config(page_title="FUB Smart Energy Board", layout="wide")
DATA_DIR = Path("data")

# Global styles (premium-ish)
st.markdown(
    """
    <style>
    .main .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1.5rem;
        max-width: 1200px;
    }
    .big-title {
        font-size: 2.3rem;
        font-weight: 750;
        margin-bottom: 0.1rem;
    }
    .subtitle {
        color: #9ca3af;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .card {
        padding: 1rem 1.2rem;
        border-radius: 0.85rem;
        background: #020617;
        border: 1px solid #1f2937;
    }
    .card h3 {
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #9ca3af;
        margin-bottom: 0.35rem;
    }
    .card .value {
        font-size: 1.3rem;
        font-weight: 650;
    }
    .pill {
        display: inline-flex;
        align-items: center;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        border: 1px solid #1f2937;
        font-size: 0.76rem;
        color: #9ca3af;
        gap: 0.4rem;
    }
    .floor-badge {
        font-size: 0.8rem;
        padding: 0.15rem 0.5rem;
        border-radius: 999px;
        background: #0f172a;
        border: 1px solid #1f2937;
        color: #9ca3af;
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
    st.session_state.page = page


def go_device(device_id: str, device_name: str):
    st.session_state.current_device_id = device_id
    st.session_state.current_device_name = device_name
    st.session_state.page = "device_detail"


# ------------------------------------------------------------------------------------
# Sidebar: navigation + Mongo status

# Mongo health check
try:
    _client = get_client()
    mongo_ok = _client is not None
except Exception as _e:
    mongo_ok = False
    mongo_err = str(_e)
else:
    mongo_err = ""

with st.sidebar:
    st.markdown("### 🧭 Navigation")

    options = [
        "🏠 Overview",
        "📂 Devices",
        "➕ Add Device",
        "⚙️ Manage Devices",
        "📈 Reports",
        "📘 Help / User Manual",
    ]
    label_to_page = {
        "🏠 Overview": "home",
        "📂 Devices": "devices",
        "➕ Add Device": "add_device",
        "⚙️ Manage Devices": "manage_devices",
        "📈 Reports": "reports",
        "📘 Help / User Manual": "help",
    }
    page_to_label = {v: k for k, v in label_to_page.items()}

    current_page = st.session_state.page
    if current_page in page_to_label:
        default_label = page_to_label[current_page]
    else:
        default_label = "🏠 Overview"

    choice = st.radio(
        "",
        options,
        index=options.index(default_label),
        key="nav_choice",
    )

    if st.session_state.page != "device_detail":
        st.session_state.page = label_to_page[choice]

    st.markdown("---")
    st.markdown("### 🗄️ Data backend")
    st.write("Mongo URI set:", bool(MONGODB_URI))
    st.write("Connected:", mongo_ok)
    if not mongo_ok:
        st.caption("Check MONGODB_URI in secrets / .env")
    st.markdown("---")
    st.caption("FUB Building Energy Management Demo")


# ------------------------------------------------------------------------------------
# Soft scheduler (runs every app reload)

run_due_schedules()

# ------------------------------------------------------------------------------------
# Pages

def home_page():
    devices = load_devices()

    st.markdown('<div class="big-title">FUB Energy Command Center ⚡</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Real-time and historical energy view for the FUB building, '
        'with Bangladesh billing and floor-level aggregation.</div>',
        unsafe_allow_html=True,
    )

    if not devices:
        st.info("No devices yet. Use **Add Device** from the left sidebar to register at least one Tuya plug.")
        return

    tabs = st.tabs(["Today (Live)", "History by Day"])

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
            st.caption(f"Present voltage: {present_voltage:.1f} V")
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("<h3>Today (BD)</h3>", unsafe_allow_html=True)
            st.markdown(
                f'<div class="value">{today_kwh:.3f} kWh</div>', unsafe_allow_html=True
            )
            st.caption(f"Estimated bill today: **{today_bill:.2f} BDT** (BD residential slabs)")
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("<h3>This Month</h3>", unsafe_allow_html=True)
            st.markdown(
                f'<div class="value">{month_kwh:.3f} kWh</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"Projected bill so far: **{month_bill:.2f} BDT**")
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("")

        # Floor aggregation tiles (4.4 floor/building aggregation)
        st.markdown("#### Floor overview")
        floors = group_devices_by_floor()
        if not floors:
            st.caption("No floor metadata yet. Add building/floor in devices.json.")
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
                with st.expander(f"Floor {floor} · {building}", expanded=False):
                    fc1, fc2, fc3 = st.columns(3)
                    with fc1:
                        st.metric("Instant load", f"{f_power:.1f} W")
                        st.caption(f"Present V: {f_voltage:.1f} V")
                    with fc2:
                        st.metric("Today (kWh)", f"{f_today_kwh:.3f}")
                        st.caption(f"Bill today: {f_today_bill:.2f} BDT")
                    with fc3:
                        st.metric("This month (kWh)", f"{f_month_kwh:.3f}")
                        st.caption(f"Month so far: {f_month_bill:.2f} BDT")

        st.markdown("")
        col_l, col_r = st.columns([3, 1])
        with col_l:
            st.markdown("#### Last 24 hours — Building profile")
            ts = aggregate_timeseries_24h(devices, resample_rule="5T")
            if ts.empty:
                st.info(
                    "No historical data in MongoDB yet.\n\n"
                    "- Open a device page and wait a few refreshes, or\n"
                    "- Run `data_collector.py` locally/online."
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
            if st.button("📂 Open devices list"):
                go("devices")
                st.rerun()
            if st.button("➕ Add new plug"):
                go("add_device")
                st.rerun()
            st.markdown("---")
            st.markdown(
                '<span class="pill">Devices online: '
                f'{len(devices)}</span>',
                unsafe_allow_html=True,
            )

    # -------------------- HISTORY TAB --------------------
    with tabs[1]:
        today = datetime.now().date()
        hist_date = st.date_input(
            "Select date (past days only)",
            value=today,
            max_value=today,
        )
        st.caption("Future dates are disabled; data is loaded from MongoDB for past days.")

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
    st.markdown('<div class="big-title">All Connected Devices</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Each card represents a Tuya smart plug mapped to a room in the FUB building.</div>',
        unsafe_allow_html=True,
    )

    devs = load_devices()
    if not devs:
        st.info("No devices found. Add one from **Add Device** in the sidebar.")
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
    st.markdown('<div class="big-title">Add a New FUB Device</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Register a Tuya plug by its device ID from the Tuya IoT Cloud console and map it to FUB floors/rooms.</div>',
        unsafe_allow_html=True,
    )

    with st.form("add_device_form"):
        name = st.text_input("Friendly name (e.g., FUB 401 - Lab AC)")
        device_id = st.text_input("Tuya Device ID")
        building = st.text_input("Building code", value="FUB")
        floor = st.text_input("Floor (e.g., 4)")
        room = st.text_input("Room (e.g., 401)")
        capacity = st.number_input("Room capacity (optional)", min_value=0, value=0, step=1)
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
            st.info("Now open the **Devices** page and click into the device to start logging data.")


def manage_devices_page():
    st.markdown('<div class="big-title">Manage Devices</div>', unsafe_allow_html=True)
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
        "Create one-time or weekly schedules. The app checks these on every reload and "
        "sends ON/OFF commands to Tuya automatically."
    )

    # Existing schedules
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

    # Fetch and log one reading on every load/refresh
    try:
        fetch_and_log_once(dev_id, dev_name)
    except Exception as e:
        st.error(f"Tuya API error while logging data: {e}")

    tabs = st.tabs(["Today (Live)", "History & Billing", "Schedules"])

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

        st.markdown("### Recent Power (last 50 samples)")
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
        st.caption("Billing uses BD residential slab rates (EL-B-A).")

        st.markdown("### Historical analysis by date")
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
    st.markdown('<div class="big-title">Reports & Aggregations</div>', unsafe_allow_html=True)
    st.info(
        "For a simple academic project, you can export data from MongoDB or use the per-device "
        "and building charts. A CSV export button could be added here later if needed."
    )


def help_page():
    st.markdown('<div class="big-title">User Manual — FUB BEMS Dashboard</div>', unsafe_allow_html=True)

    st.markdown(
        """
        ### 1. Overview

        This dashboard is a Building Energy Management System (BEMS) prototype for EWU's FUB building.\
        It reads real-time power data from Tuya smart plugs, stores it in MongoDB, and calculates\
        energy and bills using the official Bangladesh electricity tariffs (residential domestic slabs).

        The system supports:

        - Building & floor-level aggregation  
        - Room/device-level real-time monitoring  
        - Bangladesh tariff-based billing (kWh → BDT)  
        - Manual ON/OFF control of plugs  
        - Scheduled ON/OFF (once or weekly)  
        - Historical analysis per day and custom ranges  

        **Knowledge contact:** `heyneeddev@gmail.com`
        """
    )

    st.markdown(
        """
        ### 2. Pages

        **🏠 Overview (Building dashboard)**  
        - Shows building totals for:
          - Instant power (W)
          - Today's kWh and bill (BDT)
          - This month's kWh and bill (BDT)
        - Displays floor-wise cards (FUB Floor 4, Floor 5, etc.) with the same metrics.
        - Provides:
          - **Today (Live)** tab → last 24h power & voltage line chart.
          - **History by Day** tab → choose any past date (calendar) and view the aggregated profile.

        **📂 Devices**  
        - Lists all Tuya devices (one per room), including:
          - Device name
          - Tuya device ID
          - Building, floor, room mapping
          - Last known power/voltage
        - Use **Open dashboard** on any device to see its detail page.

        **➕ Add Device**  
        - Register a new Tuya plug with:
          - Friendly name
          - Device ID
          - Building/floor/room
          - Optional room capacity
        - After adding, the device appears in **Devices**.

        **⚙️ Manage Devices**  
        - See all registered devices and remove entries that are no longer needed.

        **📈 Reports**  
        - Placeholder for future CSV exports, room/floor comparison charts, etc.
        - For now, use device history and building history tabs.

        **📘 Help / User Manual**  
        - You are here. This explains how to use the dashboard and who to contact.
        """
    )

    st.markdown(
        """
        ### 3. Device detail page (room-level)

        On the device page you have three tabs:

        **Today (Live)**  
        - Shows live snapshot of:
          - Power (W)
          - Voltage (V)
          - Current (A)
        - Live ON/OFF buttons send commands to the Tuya plug.
        - A chart of the last 50 readings visualises recent power behaviour.

        **History & Billing**  
        - Shows:
          - Today's kWh and cost (BDT)
          - This month's kWh and cost (BDT)
        - Billing uses Bangladesh domestic slabs.
        - Historical analysis lets you:
          - Pick **start** and **end** dates (up to today; future dates disabled).
          - Choose aggregation step (raw / 1min / 5min / 15min).
          - View charts and raw table for reports.

        **Schedules**  
        - View existing schedules (once or weekly).
        - For each schedule you can:
          - Enable/disable (Active checkbox)
          - Delete (🗑 button)
        - Create new schedules:
          - **Type**: One-time or weekly
          - **Action**: Turn ON or Turn OFF
          - **Time**: Time of day in Dhaka time
          - **Date** (for one-time) or **weekdays** (for weekly)

        The app runs a **soft scheduler** on every reload:
        - If the current time is past the schedule time (and not executed yet), it sends the ON/OFF command.
        - Weekly schedules trigger once per day on the selected weekdays.

        """
    )

    st.markdown(
        """
        ### 4. Data & billing model

        - All telemetry is stored in MongoDB per device, with:
          - timestamp
          - voltage, current, power
          - cumulative energy_kWh
        - Energy per day/month is computed as:
          - `max(energy_kWh) - min(energy_kWh)` for that period.
        - Bills are computed using Bangladesh residential slabs (EL-B-A),
          based on the official SRO rates.

        ### 5. Contact

        For questions, improvements or collaboration, contact:  
        **Email:** `heyneeddev@gmail.com`
        """
    )


# ------------------------------------------------------------------------------------
# Router

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
