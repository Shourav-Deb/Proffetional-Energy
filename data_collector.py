import time
from datetime import datetime, timezone

from helpers import load_devices_local, dhaka_tz
from get_power_data import fetch_and_log_once

INTERVAL_SECONDS = 10 


def main():
    devices = load_devices_local()
    if not devices:
        print("[collector] No devices found in devices.json. Exiting.")
        return

    print(f"[collector] Starting data collector for {len(devices)} device(s).")
    print(f"[collector] Interval: {INTERVAL_SECONDS} seconds.")
    print("[collector] Press Ctrl+C to stop.\n")

    try:
        while True:
            loop_start_utc = datetime.now(timezone.utc)
            loop_start_local = loop_start_utc.astimezone(dhaka_tz)
            print(
                f"[collector] ==== New cycle at "
                f"{loop_start_local.isoformat(timespec='seconds')} ===="
            )

           
            devices = load_devices_local()

            for d in devices:
                dev_id = d.get("id")
                dev_name = d.get("name", "")
                if not dev_id:
                    print("[collector] Skipping device with missing 'id':", d)
                    continue
                try:
                    result = fetch_and_log_once(dev_id, dev_name)
                    now_local = datetime.now(timezone.utc).astimezone(dhaka_tz)
                    print(
                        f"[collector] {now_local.isoformat(timespec='seconds')} | "
                        f"{dev_name or dev_id} -> {result}"
                    )
                except Exception as e:
                    now_local = datetime.now(timezone.utc).astimezone(dhaka_tz)
                    print(
                        f"[collector] ERROR at {now_local.isoformat(timespec='seconds')} "
                        f"for device {dev_name or dev_id}: {e}"
                    )

            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n[collector] Stopped by user. Goodbye.")


if __name__ == "__main__":
    main()
