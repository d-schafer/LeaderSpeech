"""Tests for the strict head-line date parser.

Every positive is a real shape lifted from data/scraped/*.csv, and every negative is a real
observed failure of the naive "scan the first N chars" approach that this module exists to avoid.
"""

import pytest

from leaderspeech import datetext


# --- positives: a head line that IS a date -----------------------------------------------------

def test_uzbekistan_bare_dotted_date_on_line_0():
    # uzb_president_english_wayback, 71% of rows look exactly like this
    text = ("05.12.2016\n"
            "The following congratulatory message has come from President of the Russian "
            "Federation Vladimir Putin, addressed to President-elect of the Republic of "
            "Uzbekistan Shavkat Mirziyoyev:")
    assert datetext.parse_text_head(text) == ("2016-12-05", "day")


def test_uzbekistan_date_on_line_1_after_the_title():
    # the other 28%: trafilatura repeats the headline as line 0
    text = ("President Shavkat Mirziyoyev departed for Kazakhstan\n"
            "09.09.2017\n"
            "On September 9, President of the Republic of Uzbekistan Shavkat Mirziyoyev "
            "departed for the city of Astana.")
    assert datetext.parse_text_head(text) == ("2017-09-09", "day")


def test_albania_month_day_year_after_a_pipe_line():
    # alb_president_english_wayback
    text = ("|\n"
            "THE ADDRESS OF PRESIDENT MOISIU AT THE ASSEMBLY\n"
            "January 12, 2006\n"
            "Distinguished Madam Speaker,")
    assert datetext.parse_text_head(text) == ("2006-01-12", "day")


def test_belarus_pipe_wrapped_date_line():
    # blr_president_english_wayback renders its date inside a table cell
    text = ("| 19.11.2010 |\n"
            "| President Alexander Lukashenko has sent greetings to the participants |")
    assert datetext.parse_text_head(text) == ("2010-11-19", "day")


def test_leading_weekday_is_noise():
    # aze_president_english_wayback
    text = "The Hill\nFriday, November 08, 2013\nMichael McMahon"
    assert datetext.parse_text_head(text) == ("2013-11-08", "day")


def test_day_month_year_words():
    assert datetext.parse_text_head("9 June 2015\nThe G7 group met today.") == ("2015-06-09", "day")


def test_iso_date_line():
    assert datetext.parse_text_head("2019-04-09\nbody text here") == ("2019-04-09", "day")


def test_published_label_is_noise():
    assert datetext.parse_text_head("Published: 4 March 2015\nRemarks") == ("2015-03-04", "day")


def test_ordinal_suffix_and_of():
    assert datetext.parse_text_head("21st of May 2018\nAddress") == ("2018-05-21", "day")


def test_tier2_non_english_month_name():
    pytest.importorskip("dateparser")
    # alb_president_wayback -- Albanian month name, unreachable by the English regexes
    got, prec = datetext.parse_text_head("12 Janar 2006\nfjalim i presidentit", languages=["sq"])
    assert (got, prec) == ("2006-01-12", "day")


def test_tier2_is_skipped_when_disabled():
    assert datetext.parse_text_head("12 Janar 2006\nfjalim", use_dateparser=False) == (None, None)


# --- negatives: prose that merely CONTAINS a date ----------------------------------------------

def test_prose_date_is_refused_azerbaijan():
    # the exact string the naive parser mis-read; the row's real date is 2013
    text = ("20 January 1990 went down in the history of modern Azerbaijan as one of the most "
            "tragic and at the same time heroic pages.")
    assert datetext.parse_text_head(text) == (None, None)


def test_prose_date_is_refused_armenia():
    text = ("By the Presidential decree of December 27, 2008 Vakhtang Darchinian was awarded "
            "the Medal of Gratitude.")
    assert datetext.parse_text_head(text) == (None, None)


def test_bare_year_is_never_returned():
    text = "The Constitution of the Republic of Belarus of 1994 with alterations and additions"
    assert datetext.parse_text_head(text) == (None, None)


def test_trailing_date_in_a_title_is_deliberately_missed():
    # nga_statehouse_wayback. Accepting this shape dropped ind_pmindia precision 98.9% -> 60.3%,
    # so it is refused on purpose and left to the model.
    text = ("Press briefing by Defence Headquarters on current counter-Terrorism Campaign. "
            "March 4, 2015")
    assert datetext.parse_text_head(text) == (None, None)


def test_footer_template_year_is_refused():
    assert datetext.parse_text_head("© Gvern ta' Malta 2024 Termini tal-uzu") == (None, None)


def test_navigation_chrome_is_refused():
    text = "Official pages in social networks\nSearch on site\nView\nFont size"
    assert datetext.parse_text_head(text) == (None, None)


def test_ambiguous_slash_date_is_refused():
    assert datetext.parse_text_head("05/12/2016\nbody") == (None, None)


def test_slash_date_is_accepted_when_a_component_disambiguates():
    assert datetext.parse_text_head("25/12/2016\nbody") == ("2016-12-25", "day")


def test_url_slug_is_not_read_as_an_iso_date():
    text = "http://president.gov.mt/wp-content/uploads/2015-07-20/x\nbody"
    assert datetext.parse_text_head(text) == (None, None)


def test_below_the_year_floor_is_refused():
    assert datetext.parse_text_head("01.01.1950\nbody") == (None, None)


def test_far_future_is_refused():
    assert datetext.parse_text_head("01.01.2099\nbody") == (None, None)


def test_impossible_calendar_date_is_refused():
    assert datetext.parse_text_head("31.02.2016\nbody") == (None, None)


def test_long_line_containing_a_date_is_refused():
    line = "On 05.12.2016 the President received the credentials of several new ambassadors here"
    assert len(line) > 60
    assert datetext.parse_text_head(line) == (None, None)


def test_date_deeper_than_the_line_window_is_refused():
    text = "\n".join(["line %d" % i for i in range(9)] + ["05.12.2016"])
    assert datetext.parse_text_head(text, lines=4) == (None, None)


def test_date_deeper_in_the_head_is_found_when_the_window_allows():
    text = "\n".join(["line %d" % i for i in range(9)] + ["05.12.2016"])
    assert datetext.parse_text_head(text, lines=12) == ("2016-12-05", "day")


# --- guards ------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "", 12345, [], {}])
def test_non_text_input_is_safe(bad):
    assert datetext.parse_text_head(bad) == (None, None)


def test_head_lines_skips_blanks_and_strips():
    assert datetext.head_lines("\n\n  a  \n\n b \n c \n d \n e \n", lines=3) == ["a", "b", "c"]


def test_head_lines_on_non_text():
    assert datetext.head_lines(None) == []


# --- lang_hint ---------------------------------------------------------------------------------

def test_lang_hint_from_detected_language():
    assert datetext.lang_hint({"detected_language": "sq"}) == ["sq"]


def test_lang_hint_from_source_language_name():
    assert datetext.lang_hint({"source_language": "Spanish"}) == ["es"]


def test_lang_hint_returns_none_when_unknown():
    assert datetext.lang_hint({"source_language": ""}) is None
    assert datetext.lang_hint(None) is None
