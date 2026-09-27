"""
Authoritative Time Utility Module for RouterX.

Provides centralized conversion, arithmetic, and formatting between:
  - Absolute simulation datetime (ISO 8601 string / datetime)
  - Elapsed simulation minutes (float)
  - User-facing 12-hour clock times (e.g. "12:42 PM")
  - Time windows (e.g. "1:00 PM – 2:00 PM")
  - Durations (e.g. "15 min", "1h 30m")
  - ETA deltas (e.g. "↑ +15 min", "↓ -9 min")
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Union
import re


def get_current_local_iso() -> str:
    """Return the current local system date/time formatted as an ISO 8601 string."""
    return datetime.now().astimezone().isoformat()


def parse_datetime(dt_val: Union[str, datetime]) -> datetime:
    """Parse a datetime object or ISO string into a timezone-aware datetime."""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val
    try:
        # Standard fromisoformat
        dt = datetime.fromisoformat(dt_val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        # Fallback
        return datetime.now().astimezone()


def to_datetime(start_time: Union[str, datetime], elapsed_minutes: float) -> datetime:
    """
    Calculate absolute simulation datetime:
    current_simulation_datetime = simulation_start_datetime + simulation_elapsed_minutes
    """
    base_dt = parse_datetime(start_time)
    return base_dt + timedelta(minutes=float(elapsed_minutes))


def to_elapsed_minutes(start_time: Union[str, datetime], target_time: Union[str, datetime]) -> float:
    """Calculate elapsed minutes from simulation start time to target datetime."""
    base_dt = parse_datetime(start_time)
    target_dt = parse_datetime(target_time)
    delta = target_dt - base_dt
    return round(delta.total_seconds() / 60.0, 2)


def format_clock_time(
    dt_or_min: Union[datetime, float, int],
    start_time: Optional[Union[str, datetime]] = None,
    include_seconds: bool = False,
) -> str:
    """
    Format time into a 12-hour AM/PM string, e.g. "12:42 PM" or "12:42:18 PM".
    Accepts either an absolute datetime or elapsed minutes + start_time.
    """
    if isinstance(dt_or_min, (int, float)):
        base = start_time or get_current_local_iso()
        dt = to_datetime(base, float(dt_or_min))
    elif isinstance(dt_or_min, datetime):
        dt = dt_or_min
    elif isinstance(dt_or_min, str):
        try:
            dt = parse_datetime(dt_or_min)
        except Exception:
            return dt_or_min
    else:
        return "—"

    # Use strftime with 12-hour format
    # Strip leading zero from hour (e.g. "01:00 PM" -> "1:00 PM")
    time_fmt = "%I:%M:%S %p" if include_seconds else "%I:%M %p"
    formatted = dt.strftime(time_fmt)
    if formatted.startswith("0"):
        formatted = formatted[1:]
    return formatted


def format_date(
    dt_or_min: Union[datetime, float, int, str],
    start_time: Optional[Union[str, datetime]] = None,
) -> str:
    """Format date into standard presentation: "Sep 27, 2026"."""
    if isinstance(dt_or_min, (int, float)):
        base = start_time or get_current_local_iso()
        dt = to_datetime(base, float(dt_or_min))
    elif isinstance(dt_or_min, datetime):
        dt = dt_or_min
    elif isinstance(dt_or_min, str):
        try:
            dt = parse_datetime(dt_or_min)
        except Exception:
            return dt_or_min
    else:
        return "—"

    return dt.strftime("%b %d, %Y")


def format_time_window(
    start_min: float,
    end_min: float,
    start_time: Optional[Union[str, datetime]] = None,
) -> str:
    """Format delivery window: "1:00 PM – 2:00 PM"."""
    base = start_time or get_current_local_iso()
    s_str = format_clock_time(start_min, base)
    e_str = format_clock_time(end_min, base)
    return f"{s_str} – {e_str}"


def format_duration(minutes: float) -> str:
    """
    Format operational duration (distinct from timestamps):
    e.g. 15.0 -> "15 min", 75.0 -> "1h 15m".
    """
    mins = round(float(minutes))
    if abs(mins) < 60:
        return f"{mins} min"
    hours = mins // 60
    rem_mins = mins % 60
    if rem_mins == 0:
        return f"{hours}h"
    return f"{hours}h {rem_mins}m"


def format_eta_delta(delta_minutes: float) -> str:
    """Format ETA delta: "↑ +15 min" or "↓ -9 min"."""
    d = round(float(delta_minutes), 1)
    if d > 0:
        return f"↑ +{d:g} min"
    elif d < 0:
        return f"↓ -{abs(d):g} min"
    return "0 min"


def parse_clock_time(time_str: str, start_time: Union[str, datetime]) -> float:
    """
    Parse a user-input clock time like "2:30 PM", "14:30", "2:30pm", "9:00 AM"
    relative to the simulation start date, and return elapsed minutes.
    Handles crossing midnight correctly.
    """
    base_dt = parse_datetime(start_time)
    cleaned = time_str.strip().upper()

    # Regex for 12-hour or 24-hour time
    m12 = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)$", cleaned)
    m24 = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", cleaned)

    hour = 0
    minute = 0
    second = 0

    if m12:
        h, m, s, meridian = m12.groups()
        hour = int(h)
        minute = int(m)
        second = int(s) if s else 0
        if meridian == "PM" and hour < 12:
            hour += 12
        elif meridian == "AM" and hour == 12:
            hour = 0
    elif m24:
        h, m, s = m24.groups()
        hour = int(h)
        minute = int(m)
        second = int(s) if s else 0
    else:
        # Fallback to direct float if entered as number of minutes
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    target_dt = base_dt.replace(hour=hour, minute=minute, second=second, microsecond=0)

    # If target is earlier than start time by more than 12 hours (e.g. 12:10 AM when start was 11:50 PM),
    # or if target is earlier than start on the same day when creating a future window, assume next day.
    if target_dt < base_dt:
        # If difference is negative, add 1 day
        diff_mins = (target_dt - base_dt).total_seconds() / 60.0
        if diff_mins < -180:  # more than 3 hours earlier, likely next day crossing
            target_dt += timedelta(days=1)

    elapsed = (target_dt - base_dt).total_seconds() / 60.0
    return round(elapsed, 1)
