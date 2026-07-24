"""Parse Afghan/Persian Solar Hijri (Jalali) dates out of Dari/Persian text and convert to a
Gregorian ISO date.

Afghanistan writes its Solar Hijri calendar with the ZODIAC month names (حمل, ثور, جوزا, …),
which differ from the Iranian Persian names (فروردین, اردیبهشت, …); dateparser only knows the
Iranian set, so we map both here. Digits may be Western (1404) or Persian/Arabic-Indic (۱۴۰۴).

`parse_jalali(text)` returns (date_str, precision):
  * ("YYYY-MM-DD", "day")  — a full day/month/year date was found and converted exactly
  * ("YYYY",       "year") — only a Solar-Hijri YEAR was found → the Gregorian year it mostly
                             falls in (jy + 621); an approximate fallback, day/month unknown
  * (None, None)           — no Solar-Hijri date signal in the text

Used by the cleaner to correct the (often bogus) scraped date BEFORE the tenure/leaders
crosscheck runs, so a Taliban-era 1403/1404 speech isn't misdated to a Ghani year. Pure +
unit-tested. No external calendar dependency (the conversion is the standard algorithm).
"""

from __future__ import annotations

import re

# Persian + Arabic-Indic digits -> Western
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# month name -> number: Afghan zodiac names, then Iranian Persian names (+ common variants)
MONTHS: dict[str, int] = {
    "حمل": 1, "ثور": 2, "جوزا": 3, "سرطان": 4, "اسد": 5, "سنبله": 6, "سنبلة": 6,
    "میزان": 7, "عقرب": 8, "قوس": 9, "جدی": 10, "دلو": 11, "حوت": 12,
    "فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4, "مرداد": 5, "شهریور": 6,
    "مهر": 7, "آبان": 8, "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12,
}
_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
_MIN_YEAR, _MAX_YEAR = 1300, 1420   # sane Solar-Hijri range for modern speech text
_ARABIC = re.compile(r"[؀-ۿ]")   # Persian/Dari script gate (see parse_jalali)

_DMY = re.compile(rf"(\d{{1,2}})\s*({_NAMES})\s*(1[34]\d{{2}})")      # 19 حمل 1404
_NUM = re.compile(r"(?<!\d)(1[34]\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)")  # 1404/01/19
_YMD = re.compile(rf"(1[34]\d{{2}})\s*({_NAMES})\s*(\d{{1,2}})")      # 1404 حمل 19
_YEAR = re.compile(r"(?<!\d)(1[34]\d{2})(?!\d)")                      # a bare 13xx/14xx year


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Convert a Jalali (Solar Hijri) date to a Gregorian (year, month, day)."""
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    mlen = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and gd > mlen[gm]:
        gd -= mlen[gm]
        gm += 1
    return gy, gm + 1, gd


def _iso(jy: int, jm: int, jd: int) -> str | None:
    if not (_MIN_YEAR <= jy <= _MAX_YEAR and 1 <= jm <= 12 and 1 <= jd <= 31):
        return None
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


def parse_jalali(text) -> tuple[str | None, str | None]:
    """Best Gregorian date derivable from a Solar-Hijri date in `text`. See module docstring."""
    if not isinstance(text, str) or not text:
        return None, None
    # Persian/Dari script only: without this, the bare-year fallback would mis-read a "1403"
    # that appears as a plain number in a Latin-script (e.g. Spanish) speech as a 2024 date.
    if not _ARABIC.search(text):
        return None, None
    t = text.translate(_DIGITS)
    m = _DMY.search(t)                                   # DD Month YYYY (most common)
    if m and (iso := _iso(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))):
        return iso, "day"
    m = _NUM.search(t)                                   # YYYY/MM/DD numeric
    if m and (iso := _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))):
        return iso, "day"
    m = _YMD.search(t)                                   # YYYY Month DD
    if m and (iso := _iso(int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))):
        return iso, "day"
    m = _YEAR.search(t)                                  # bare year -> approximate year
    if m:
        jy = int(m.group(1))
        if _MIN_YEAR <= jy <= _MAX_YEAR:
            return str(jy + 621), "year"
    return None, None
