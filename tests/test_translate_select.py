"""The interactive backend picker: VRAM-based recommendation + choice handling."""

from leaderspeech.translate import select
from leaderspeech.translate.config import TranslateConfig


def test_recommend_by_vram():
    assert select.recommend(0) == "google"
    assert select.recommend(3.5) == "google"
    assert select.recommend(8) == "nllb"          # this machine
    assert select.recommend(24) == "nllb-large"


def test_default_choice_follows_recommendation(monkeypatch):
    monkeypatch.setattr(select, "detect_gpu", lambda: (0.0, None))   # no GPU -> google
    tr, cfg = select.choose_backend(TranslateConfig(), input_fn=lambda _p: "")
    assert tr == "google"


def test_picking_nllb_large_sets_the_big_model(monkeypatch):
    # options: 1 google, 2 googletrans, 3 nllb-600M, 4 nllb-3.3B, 5 opusmt
    monkeypatch.setattr(select, "detect_gpu", lambda: (24.0, "RTX A5000"))
    tr, cfg = select.choose_backend(TranslateConfig(), input_fn=lambda _p: "4")
    assert tr == "nllb" and cfg.nllb_model == "facebook/nllb-200-3.3B"


def test_picking_600m_keeps_the_small_model(monkeypatch):
    monkeypatch.setattr(select, "detect_gpu", lambda: (8.0, "RTX 3060 Ti"))
    tr, cfg = select.choose_backend(TranslateConfig(), input_fn=lambda _p: "3")
    assert tr == "nllb" and cfg.nllb_model == "facebook/nllb-200-distilled-600M"


def test_picking_googletrans(monkeypatch):
    monkeypatch.setattr(select, "detect_gpu", lambda: (0.0, None))
    tr, _cfg = select.choose_backend(TranslateConfig(), input_fn=lambda _p: "2")
    assert tr == "googletrans"


def test_explicit_google_choice(monkeypatch):
    monkeypatch.setattr(select, "detect_gpu", lambda: (8.0, "RTX 3060 Ti"))
    tr, _cfg = select.choose_backend(TranslateConfig(), input_fn=lambda _p: "1")
    assert tr == "google"
