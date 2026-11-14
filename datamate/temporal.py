"""
Temporal, solar-lunar calendar, and messy date/number parsing helpers for DataMate.

Implements Section 2 (Thời gian) and Section 8 (Cách ghi trong file) of the
DataMate rulebook without hardcoding business identifiers.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


_EXCEL_EPOCH = dt.date(1899, 12, 30)

_VI_MONTH_DATE_RE = re.compile(
    r"^\s*(?:ng[aà]y\s*)?(\d{1,2})\s*(?:thg|th[aá]ng|/|-|\.)\s*(\d{1,2})(?:\s*(?:(?:n[aă]m\b|[/\-.])\s*|\s+)(\d{2,4}))?\s*$",
    re.IGNORECASE,
)
_DMY_RE = re.compile(
    r"^\s*(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\s*$"
)
_YMD_RE = re.compile(
    r"^\s*(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?:[T\s](\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?))?\s*$"
)
_SERIAL_RE = re.compile(r"^\s*(\d{5}(?:\.\d+)?)\s*$")


def normalize_nfc(text: str) -> str:
    """Return Unicode NFC-normalized text with stripped ends."""
    return unicodedata.normalize("NFC", str(text)).strip()


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamp_day(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, _last_day_of_month(year, month)))


def _add_months(year: int, month: int, delta: int) -> Tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    new_year, new_month_zero = divmod(total, 12)
    return new_year, new_month_zero + 1


def parse_date_value(
    value: Any,
    default_year: Optional[int] = None,
    day_first: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse messy Vietnamese spreadsheet date/datetime cell into ISO strings.

    Returns ``(iso_date, iso_time)`` where ``iso_date`` is ``YYYY-MM-DD``
    (or ``None`` if unparseable) and ``iso_time`` is ``HH:MM:SS`` if a time
    component was present, else ``None``.

    Supports:
    - ``datetime.datetime`` / ``datetime.date`` objects
    - Excel serial numbers (integers/numeric strings roughly in 20000..70000)
    - ISO ``YYYY-MM-DD[ HH:MM[:SS]]``
    - ``DD/MM/YYYY[ HH:MM[:SS]]``, ``DD-MM-YYYY``, ``DD.MM.YYYY``
    - ``1 thg 6 2025``, ``ngày 1 tháng 6 năm 2025``
    - Yearless dates ``DD/MM`` when ``default_year`` is known (Rulebook §8)
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, None
    if isinstance(value, dt.datetime):
        t = value.strftime("%H:%M:%S")
        return value.date().isoformat(), (None if t == "00:00:00" and value.microsecond == 0 else t)
    if isinstance(value, dt.date):
        return value.isoformat(), None
    if isinstance(value, (int, float)):
        if 20000 <= value <= 80000:
            days = int(value)
            frac = float(value) - days
            d = _EXCEL_EPOCH + dt.timedelta(days=days)
            if frac > 1e-6:
                secs = round(frac * 86400)
                t_obj = (dt.datetime.combine(d, dt.time.min) + dt.timedelta(seconds=secs)).time()
                return d.isoformat(), t_obj.strftime("%H:%M:%S")
            return d.isoformat(), None
        return None, None

    s = normalize_nfc(str(value))
    if not s or s.lower() in {"nan", "nat", "none", "null", "n/a", "-"}:
        return None, None

    m_serial = _SERIAL_RE.match(s)
    if m_serial:
        serial_val = float(m_serial.group(1))
        if 20000 <= serial_val <= 80000:
            return parse_date_value(serial_val, default_year=default_year, day_first=day_first)

    m_ymd = _YMD_RE.match(s)
    if m_ymd:
        y, m, d = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
        t_str = m_ymd.group(4)
        try:
            iso_d = dt.date(y, m, d).isoformat()
        except ValueError:
            return None, None
        if t_str:
            parts = t_str.split(".")[0].split(":")
            hh = int(parts[0])
            mm = int(parts[1])
            ss = int(parts[2]) if len(parts) > 2 else 0
            t_norm = f"{hh:02d}:{mm:02d}:{ss:02d}"
            return iso_d, (None if t_norm == "00:00:00" else t_norm)
        return iso_d, None

    m_dmy = _DMY_RE.match(s)
    if m_dmy:
        p1, p2 = int(m_dmy.group(1)), int(m_dmy.group(2))
        y_raw = m_dmy.group(3)
        t_str = m_dmy.group(4)
        if y_raw is None:
            if default_year is None:
                return None, None
            y = int(default_year)
        else:
            y = int(y_raw)
            if y < 100:
                y += 2000

        if day_first:
            d, m = (p1, p2) if p2 <= 12 else (p2, p1)
        else:
            m, d = (p1, p2) if p1 <= 12 else (p2, p1)

        try:
            iso_d = dt.date(y, m, d).isoformat()
        except ValueError:
            return None, None
        if t_str:
            parts = t_str.split(":")
            hh, mm = int(parts[0]), int(parts[1])
            ss = int(parts[2]) if len(parts) > 2 else 0
            t_norm = f"{hh:02d}:{mm:02d}:{ss:02d}"
            return iso_d, (None if t_norm == "00:00:00" else t_norm)
        return iso_d, None

    m_vi = _VI_MONTH_DATE_RE.match(s)
    if m_vi:
        d, m = int(m_vi.group(1)), int(m_vi.group(2))
        y_raw = m_vi.group(3)
        if y_raw is None:
            if default_year is None:
                return None, None
            y = int(default_year)
        else:
            y = int(y_raw)
            if y < 100:
                y += 2000
        try:
            return dt.date(y, m, d).isoformat(), None
        except ValueError:
            return None, None

    return None, None


@dataclass(frozen=True)
class CalendarRow:
    """Single row of DataMate's solar-lunar calendar.csv."""

    date: str
    weekday: int
    lunar_day: int
    lunar_month: int
    lunar_year: int
    lunar_leap: bool
    holiday: str


class SolarLunarCalendar:
    """Lookup wrapper around a split's ``calendar.csv``."""

    def __init__(self, calendar_path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(calendar_path)
        self.by_solar: Dict[str, CalendarRow] = {}
        self.by_lunar: Dict[Tuple[int, int, int, bool], str] = {}
        self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                leap = str(raw["lunar_leap"]).strip().lower() in {"true", "1", "yes"}
                row = CalendarRow(
                    date=raw["date"].strip(),
                    weekday=int(raw["weekday"]),
                    lunar_day=int(raw["lunar_day"]),
                    lunar_month=int(raw["lunar_month"]),
                    lunar_year=int(raw["lunar_year"]),
                    lunar_leap=leap,
                    holiday=normalize_nfc(raw.get("holiday", "")),
                )
                self.by_solar[row.date] = row
                self.by_lunar[(row.lunar_year, row.lunar_month, row.lunar_day, row.lunar_leap)] = row.date

    def get_solar(self, iso_date: str) -> Optional[CalendarRow]:
        """Return calendar metadata for an ISO ``YYYY-MM-DD`` date."""
        return self.by_solar.get(iso_date)

    def find_solar_from_lunar(
        self,
        lunar_year: int,
        lunar_month: int,
        lunar_day: int,
        lunar_leap: bool = False,
    ) -> Optional[str]:
        """Resolve a lunar date to its solar ``YYYY-MM-DD`` date."""
        return self.by_lunar.get((lunar_year, lunar_month, lunar_day, lunar_leap))

    def tet_window(self, lunar_year: int) -> Optional[Tuple[str, str, str, str]]:
        """
        Return ``(tet_start, tet_end, pre_tet_start, pre_tet_end)`` for Tết ``lunar_year``.

        Rulebook §2:
        - Tết = solar(23 tháng Chạp, lunar_year - 1) .. solar(mùng 10 tháng Giêng, lunar_year) inclusive.
        - Trước Tết = equal number of days immediately preceding ``tet_start``.
        """
        start_str = self.find_solar_from_lunar(lunar_year - 1, 12, 23, False)
        end_str = self.find_solar_from_lunar(lunar_year, 1, 10, False)
        if not start_str or not end_str:
            return None
        start_d = dt.date.fromisoformat(start_str)
        end_d = dt.date.fromisoformat(end_str)
        span_days = (end_d - start_d).days + 1
        pre_end = start_d - dt.timedelta(days=1)
        pre_start = start_d - dt.timedelta(days=span_days)
        return start_d.isoformat(), end_d.isoformat(), pre_start.isoformat(), pre_end.isoformat()

    def all_tet_windows(self) -> Dict[int, Dict[str, Any]]:
        """Compute all Tết windows available in ``calendar.csv``."""
        lunar_years = sorted({row.lunar_year for row in self.by_solar.values()})
        result: Dict[int, Dict[str, Any]] = {}
        for ly in lunar_years:
            win = self.tet_window(ly)
            if win:
                tet_s, tet_e, pre_s, pre_e = win
                n_days = (dt.date.fromisoformat(tet_e) - dt.date.fromisoformat(tet_s)).days + 1
                result[ly] = {
                    "tet_start": tet_s,
                    "tet_end": tet_e,
                    "pre_tet_start": pre_s,
                    "pre_tet_end": pre_e,
                    "days": n_days,
                }
        return result


class TemporalResolver:
    """
    Deterministic resolver for DataMate relative dates & comparison windows
    anchored at a question's ``as_of_date``.
    """

    MORNING_SHIFT = ("06:00:00", "13:59:59")
    AFTERNOON_SHIFT = ("14:00:00", "21:59:59")

    def __init__(
        self,
        as_of_date: str | dt.date,
        cal: Optional[SolarLunarCalendar] = None,
    ) -> None:
        if isinstance(as_of_date, dt.date):
            self.today = as_of_date
        else:
            self.today = dt.date.fromisoformat(str(as_of_date).strip())
        self.cal = cal

    @property
    def as_of_iso(self) -> str:
        return self.today.isoformat()

    def last_n_days(self, n: int) -> Tuple[str, str]:
        """Return ``[today - (n - 1), today]`` inclusive (Rulebook §2)."""
        if n <= 0:
            raise ValueError(f"N must be positive, got {n}")
        start = self.today - dt.timedelta(days=n - 1)
        return start.isoformat(), self.today.isoformat()

    def resolve_month(self, month: int, year: Optional[int] = None) -> Tuple[str, str]:
        """
        Resolve month M (optionally yearless) per Rulebook §2:
        If ``year`` is omitted, use ``today.year`` if ``month <= today.month``
        else ``today.year - 1``. Cap end at ``today`` if current month.
        """
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month: {month}")
        if year is None:
            year = self.today.year if month <= self.today.month else self.today.year - 1
        start = dt.date(year, month, 1)
        end = dt.date(year, month, _last_day_of_month(year, month))
        if year == self.today.year and month == self.today.month and end > self.today:
            end = self.today
        return start.isoformat(), end.isoformat()

    def resolve_quarter(self, quarter: int, year: Optional[int] = None) -> Tuple[str, str]:
        """
        Resolve solar quarter Q (1..4) per Rulebook §2:
        If ``year`` is omitted, use ``today.year`` unless quarter Q starts strictly
        after ``today`` (in which case use ``today.year - 1``).
        """
        if not 1 <= quarter <= 4:
            raise ValueError(f"Invalid quarter: {quarter}")
        m_start = (quarter - 1) * 3 + 1
        m_end = quarter * 3
        if year is None:
            year = self.today.year if dt.date(self.today.year, m_start, 1) <= self.today else self.today.year - 1
        start = dt.date(year, m_start, 1)
        end = dt.date(year, m_end, _last_day_of_month(year, m_end))
        if end > self.today and start <= self.today:
            end = self.today
        return start.isoformat(), end.isoformat()

    def latest_tet_window(self, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Return the Tết window for explicit ``year`` or the latest Tết window
        whose start date is on or before ``as_of_date``.
        """
        if self.cal is None:
            return None
        windows = self.cal.all_tet_windows()
        if year is not None:
            return windows.get(year)
        candidates = [
            (ly, win) for ly, win in windows.items()
            if win["tet_start"] <= self.as_of_iso
        ]
        if not candidates:
            return None
        ly, win = max(candidates, key=lambda x: x[0])
        return {"lunar_year": ly, **win}

    def build_context(self) -> Dict[str, Any]:
        """Pre-compute all standard relative windows anchored at ``as_of_date``."""
        d = self.today
        yesterday = d - dt.timedelta(days=1)

        # Weeks start Monday (weekday 0 in Python date.weekday(), 1 in calendar.csv)
        this_week_start = d - dt.timedelta(days=d.weekday())
        last_week_start = this_week_start - dt.timedelta(days=7)
        last_week_end = this_week_start - dt.timedelta(days=1)

        # Current month & previous month (full vs same-day-count MTD comparison)
        this_month_start = dt.date(d.year, d.month, 1)
        prev_y, prev_m = _add_months(d.year, d.month, -1)
        prev_month_start = dt.date(prev_y, prev_m, 1)
        prev_month_full_end = dt.date(prev_y, prev_m, _last_day_of_month(prev_y, prev_m))
        prev_month_mtd_end = _clamp_day(prev_y, prev_m, d.day)

        # Year-to-date & same-period last year
        ytd_start = dt.date(d.year, 1, 1)
        ly_ytd_start = dt.date(d.year - 1, 1, 1)
        ly_ytd_end = _clamp_day(d.year - 1, d.month, d.day)
        ly_month_start = dt.date(d.year - 1, d.month, 1)
        ly_month_mtd_end = _clamp_day(d.year - 1, d.month, d.day)
        ly_month_full_end = dt.date(d.year - 1, d.month, _last_day_of_month(d.year - 1, d.month))

        ctx: Dict[str, Any] = {
            "as_of_date": d.isoformat(),
            "today": (d.isoformat(), d.isoformat()),
            "yesterday": (yesterday.isoformat(), yesterday.isoformat()),
            "this_week": (this_week_start.isoformat(), d.isoformat()),
            "last_week": (last_week_start.isoformat(), last_week_end.isoformat()),
            "last_7_days": self.last_n_days(7),
            "last_30_days": self.last_n_days(30),
            "this_month": (this_month_start.isoformat(), d.isoformat()),
            "last_month_full": (prev_month_start.isoformat(), prev_month_full_end.isoformat()),
            "last_month_same_days": (prev_month_start.isoformat(), prev_month_mtd_end.isoformat()),
            "ytd": (ytd_start.isoformat(), d.isoformat()),
            "last_year_ytd": (ly_ytd_start.isoformat(), ly_ytd_end.isoformat()),
            "same_month_last_year_full": (ly_month_start.isoformat(), ly_month_full_end.isoformat()),
            "same_month_last_year_mtd": (ly_month_start.isoformat(), ly_month_mtd_end.isoformat()),
            "morning_shift": self.MORNING_SHIFT,
            "afternoon_shift": self.AFTERNOON_SHIFT,
        }

        if self.cal is not None:
            cal_row = self.cal.get_solar(d.isoformat())
            if cal_row is not None:
                ctx["today_calendar"] = {
                    "weekday": cal_row.weekday,
                    "lunar_day": cal_row.lunar_day,
                    "lunar_month": cal_row.lunar_month,
                    "lunar_year": cal_row.lunar_year,
                    "lunar_leap": cal_row.lunar_leap,
                    "holiday": cal_row.holiday,
                }
            tet = self.latest_tet_window()
            if tet is not None:
                ctx["latest_tet"] = tet
            ctx["all_tet_windows"] = self.cal.all_tet_windows()

        return ctx
