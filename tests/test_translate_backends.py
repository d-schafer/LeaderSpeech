"""NLLB token-chunking (no over-budget chunk -> no silent truncation) + the googletrans endpoint
backend's response parsing. Neither needs the model download or the network."""

from leaderspeech.translate.config import TranslateConfig


# --- a tiny fake tokenizer: 1 token per whitespace word --------------------------------------
class _IDs:
    def __init__(self, toks):
        self._toks = toks
        self.shape = (1, len(toks))

    def __getitem__(self, i):
        return self._toks           # input_ids[0] -> the token list (sliceable)


class _Enc:
    def __init__(self, toks):
        self.input_ids = _IDs(toks)

    def to(self, _dev):
        return self


class FakeTok:
    def __call__(self, text, return_tensors=None, truncation=False, max_length=None):
        toks = text.split()
        if truncation and max_length:
            toks = toks[:max_length]
        return _Enc(toks)

    def decode(self, toks, skip_special_tokens=True):
        return " ".join(toks)


def test_nllb_chunks_never_exceed_budget_and_lose_nothing():
    from leaderspeech.translate.backends.nllb import NLLBBackend
    b = NLLBBackend()          # constructs without loading the model
    b._tok = FakeTok()
    b._chunk_tokens = 10
    run_on = " ".join(f"w{i}" for i in range(45))          # one 45-"token" sentence, no breaks
    tail = " ".join(f"x{i}" for i in range(25))
    text = f"{run_on}. Short one. {tail}."
    chunks = b._token_chunks(text)
    assert chunks
    assert all(len(c.split()) <= 10 for c in chunks), [len(c.split()) for c in chunks]
    joined = " ".join(chunks)
    assert "w0" in joined and "w44" in joined and "x24" in joined   # nothing dropped


# --- googletrans endpoint parsing ------------------------------------------------------------
def test_googletrans_parses_translate_a_response(monkeypatch):
    from leaderspeech.translate.backends import googletrans as gt

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [[["Hello ", "Hola ", None, None], ["world.", "mundo.", None, None]], None, "es"]

    monkeypatch.setattr(gt.httpx, "post", lambda *a, **k: FakeResp())
    b = gt.GoogleTransBackend()            # config=None -> no call_delay sleep
    assert b.translate("Hola mundo.", "es") == "Hello world."


def test_googletrans_empty_response():
    from leaderspeech.translate.backends import googletrans as gt
    b = gt.GoogleTransBackend()
    assert b.translate("", "es") == ""     # empty input short-circuits before any request
