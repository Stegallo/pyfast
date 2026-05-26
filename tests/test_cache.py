"""Test per il sistema di errori di compilazione nella cache."""

import pytest
from pathlib import Path

from pyfast import cache as cache_mod


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Reindirizza la cache verso una directory temporanea."""
    monkeypatch.setattr(cache_mod, "CACHE_ROOT", tmp_path / "cache")
    return tmp_path / "cache"


class TestCompileError:
    def test_no_error_by_default(self, tmp_cache):
        assert cache_mod.get_compile_error("abc123") is None

    def test_store_and_get_rustc_error(self, tmp_cache):
        cache_mod.store_compile_error("abc123", cache_mod.ERROR_RUSTC, "error[E0425]: foo")
        kind, msg = cache_mod.get_compile_error("abc123")
        assert kind == cache_mod.ERROR_RUSTC
        assert "E0425" in msg

    def test_store_and_get_transpile_error(self, tmp_cache):
        cache_mod.store_compile_error("abc123", cache_mod.ERROR_TRANSPILE, "type hint mancante")
        kind, msg = cache_mod.get_compile_error("abc123")
        assert kind == cache_mod.ERROR_TRANSPILE
        assert "type hint" in msg

    def test_store_and_get_no_rustc(self, tmp_cache):
        cache_mod.store_compile_error("abc123", cache_mod.ERROR_RUSTC_NOT_FOUND, "rustc non trovato")
        kind, msg = cache_mod.get_compile_error("abc123")
        assert kind == cache_mod.ERROR_RUSTC_NOT_FOUND

    def test_clear_compile_error(self, tmp_cache):
        cache_mod.store_compile_error("abc123", cache_mod.ERROR_RUSTC, "errore")
        cache_mod.clear_compile_error("abc123")
        assert cache_mod.get_compile_error("abc123") is None

    def test_message_with_newlines(self, tmp_cache):
        """Il messaggio può contenere newline (stderr di rustc)."""
        msg = "error[E0425]: foo\n  --> src/main.rs:1:5\n  |\n1 | runs = 1;\n  | ^^^^ not found"
        cache_mod.store_compile_error("abc123", cache_mod.ERROR_RUSTC, msg)
        kind, recovered = cache_mod.get_compile_error("abc123")
        assert kind == cache_mod.ERROR_RUSTC
        assert recovered == msg
