from leaderspeech.clean_structure_metadata import jalali


def test_conversion_known_dates():
    assert jalali.jalali_to_gregorian(1404, 1, 19) == (2025, 4, 8)
    assert jalali.jalali_to_gregorian(1403, 1, 1) == (2024, 3, 20)   # Nowruz
    assert jalali.jalali_to_gregorian(1400, 6, 1) == (2021, 8, 23)


def test_parse_afghan_zodiac_month_persian_digits():
    # 19 Hamal 1404, Persian digits, date at the top of the text
    iso, prec = jalali.parse_jalali("۱۹ حمل ۱۴۰۴\nمتن سخنرانی رئیس جمهور ...")
    assert (iso, prec) == ("2025-04-08", "day")


def test_parse_western_digits_zodiac():
    iso, prec = jalali.parse_jalali("جلسه در 1 سنبله 1400 برگزار شد")
    assert (iso, prec) == ("2021-08-23", "day")


def test_parse_iranian_month_name():
    iso, prec = jalali.parse_jalali("۱ فروردین ۱۴۰۳")   # 1 Farvardin 1403 = Nowruz 2024
    assert (iso, prec) == ("2024-03-20", "day")


def test_numeric_jalali():
    iso, prec = jalali.parse_jalali("تاریخ نشر: 1404/01/19")
    assert (iso, prec) == ("2025-04-08", "day")


def test_year_only_fallback():
    iso, prec = jalali.parse_jalali("در جریان سال 1403 اقدامات زیادی صورت گرفت")
    assert (iso, prec) == ("2024", "year")


def test_full_date_beats_year_only():
    # a full date present -> day precision, not the bare-year fallback
    iso, prec = jalali.parse_jalali("۵ ثور ۱۴۰۲ و همچنین سال ۱۳۹۹")
    assert prec == "day" and iso.startswith("2023")


def test_no_date():
    assert jalali.parse_jalali("no persian date, just a number 12345") == (None, None)
    assert jalali.parse_jalali("") == (None, None)
    assert jalali.parse_jalali(None) == (None, None)


def test_latin_script_year_is_guarded():
    # a bare "1403" in a Latin-script speech must NOT be read as a Jalali date
    assert jalali.parse_jalali("En el ano 1403 ocurrio un evento historico") == (None, None)
    assert jalali.parse_jalali("Law No. 1404 of the Republic") == (None, None)
