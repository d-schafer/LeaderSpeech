"""Translator resilience: per-chunk pacing + retry/backoff, and the atomic-write retry."""

import os

import pandas as pd
import pytest

from leaderspeech.translate import store
from leaderspeech.translate.backends.base import Translator
from leaderspeech.translate.config import TranslateConfig


class FlakyBackend(Translator):
    name = "flaky"

    def __init__(self, config, fail_times):
        super().__init__(config)
        self.fail_times = fail_times
        self.calls = 0

    def _translate_chunk(self, chunk, src_lang):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("rate limit")
        return f"OK:{chunk}"


def test_backend_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("leaderspeech.translate.backends.base.time.sleep", lambda *_: None)
    b = FlakyBackend(TranslateConfig(retries=3, backoff=2.0, call_delay=0.0), fail_times=2)
    assert b.translate("hola") == "OK:hola"
    assert b.calls == 3   # 2 failures + 1 success


def test_backend_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("leaderspeech.translate.backends.base.time.sleep", lambda *_: None)
    b = FlakyBackend(TranslateConfig(retries=2, backoff=1.0, call_delay=0.0), fail_times=99)
    with pytest.raises(RuntimeError):
        b.translate("hola")
    assert b.calls == 3   # 1 initial + 2 retries


def test_call_delay_paces_each_call(monkeypatch):
    sleeps = []
    monkeypatch.setattr("leaderspeech.translate.backends.base.time.sleep", lambda s: sleeps.append(s))
    b = FlakyBackend(TranslateConfig(retries=0, call_delay=0.5), fail_times=0)
    b.translate("hola")
    assert 0.5 in sleeps


def test_write_table_atomic_retries_on_permission_error(tmp_path, monkeypatch):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    p = tmp_path / "out.csv"
    calls = {"n": 0}
    real_replace = os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("target briefly locked (Dropbox)")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    monkeypatch.setattr(store.time, "sleep", lambda *_: None)
    store.write_table_atomic(df, p)
    assert calls["n"] == 3
    assert p.exists()
    assert store.read_table(p).shape == (2, 2)
