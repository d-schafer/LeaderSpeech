"""RSS / Atom harvesting (pagination.type == 'feed'), exercised without network by
passing a fake httpx-like client into feed.harvest_entries."""

from leaderspeech.text_scraper import feed
from leaderspeech.text_scraper.recipe import Recipe


def _recipe(link_pattern="/discurso/", feed_block=None, **pag):
    pagination = {"type": "feed", **pag}
    if feed_block is not None:
        pagination["feed"] = feed_block
    base = {
        "source_id": "t",
        "country": "Mexico",
        "source_language": "Spanish",
        "start_urls": ["http://x/feed"],
        "listing": {"link_pattern": link_pattern},
        "title": {"selectors": ["h1"]},
        "text": {"selectors": ["article"]},
        "date": {"selectors": ["time"]},
        "date_languages": ["es"],
        "pagination": pagination,
    }
    return Recipe(**base)


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return _Resp(self.pages.pop(0) if self.pages else "<rss><channel></channel></rss>")

    def close(self):
        pass


RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <item>
    <title>Discurso uno</title>
    <link>https://x/discurso/1</link>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    <description>Resumen corto</description>
    <content:encoded>Texto completo uno</content:encoded>
  </item>
  <item>
    <title>Noticia dos</title>
    <link>https://x/noticia/2</link>
    <pubDate>Tue, 02 Jan 2024 10:00:00 GMT</pubDate>
    <description>Otro</description>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Discurso atom</title>
    <link href="https://x/discurso/9" rel="alternate"/>
    <updated>2024-03-04T00:00:00Z</updated>
    <content>Cuerpo atom completo</content>
  </entry>
</feed>"""


def test_rss_extracts_filters_and_prefers_content_encoded():
    entries = feed.harvest_entries(_recipe(), client=FakeClient([RSS]))
    assert [e["url"] for e in entries] == ["https://x/discurso/1"]  # /noticia/ filtered out
    e = entries[0]
    assert e["title"] == "Discurso uno"
    assert e["date"] == "2024-01-01"                 # RFC822 pubDate parsed
    assert e["text"] == "Texto completo uno"          # content:encoded wins over description


def test_rss_use_content_false_leaves_text_empty():
    entries = feed.harvest_entries(
        _recipe(feed_block={"use_content": False}), client=FakeClient([RSS]))
    assert entries[0]["text"] == ""


def test_atom_uses_link_href_and_content():
    entries = feed.harvest_entries(_recipe(), client=FakeClient([ATOM]))
    e = entries[0]
    assert e["url"] == "https://x/discurso/9"
    assert e["title"] == "Discurso atom"
    assert e["date"] == "2024-03-04"
    assert e["text"] == "Cuerpo atom completo"


def test_feed_single_request_when_no_param():
    client = FakeClient([RSS])
    feed.harvest_entries(_recipe(), client=client)
    assert len(client.calls) == 1
