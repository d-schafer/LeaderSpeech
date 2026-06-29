from leaderspeech.text_scraper import probe


def test_wayback_probe_prints_snapshot_count(capsys):
    report = {
        "recipe": "arg_casarosada_wayback",
        "country": "Argentina",
        "renderer": "static",
        "listing": {
            "mode": "wayback snapshots",
            "snapshots_found": 2,
            "sampled": 1,
            "sample": ["https://example.org/a"],
        },
        "pages": [],
    }

    probe._print(report)
    out = capsys.readouterr().out

    assert "LISTING ✓ 2 snapshot(s)" in out
    assert "0 link(s)" not in out
