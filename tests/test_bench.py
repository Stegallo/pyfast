"""Test per il modulo bench.

Testa la logica di timing e il formato dell'output senza eseguire realmente
processi pesanti — usiamo script leggeri.
"""

import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pyfast.bench import TimingResult, BenchmarkResult, run_benchmark, _rustc_available


# ---------------------------------------------------------------------------
# TimingResult
# ---------------------------------------------------------------------------

class TestTimingResult:
    def test_mean(self):
        t = TimingResult(runs=[0.1, 0.2, 0.3], label="test")
        assert abs(t.mean - 0.2) < 1e-9

    def test_best(self):
        t = TimingResult(runs=[0.3, 0.1, 0.2], label="test")
        assert t.best == 0.1

    def test_worst(self):
        t = TimingResult(runs=[0.3, 0.1, 0.2], label="test")
        assert t.worst == 0.3

    def test_mean_ms(self):
        t = TimingResult(runs=[0.1], label="test")
        assert abs(t.mean_ms() - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# BenchmarkResult speedup
# ---------------------------------------------------------------------------

class TestBenchmarkResult:
    def test_speedup_calculated(self):
        py = TimingResult(runs=[1.0], label="Python")
        rs = TimingResult(runs=[0.1], label="Rust")
        result = BenchmarkResult(
            python=py, rust=rs, compile_time_s=2.0, script_path="test.py"
        )
        assert abs(result.speedup - 10.0) < 1e-9

    def test_speedup_none_when_no_rust(self):
        py = TimingResult(runs=[1.0], label="Python")
        result = BenchmarkResult(
            python=py, rust=None, compile_time_s=None, script_path="test.py"
        )
        assert result.speedup is None


# ---------------------------------------------------------------------------
# run_benchmark con script reale (leggero)
# ---------------------------------------------------------------------------

class TestRunBenchmark:
    def test_python_only_benchmark(self, tmp_path: Path):
        """Benchmark senza rustc disponibile — misura solo Python."""
        script = tmp_path / "hello.py"
        script.write_text('print("hello")\n')

        with patch("pyfast.bench._rustc_available", return_value=False):
            result = run_benchmark(str(script), runs=2, warmup=0, verbose=False)

        assert len(result.python.runs) == 2
        assert result.rust is None
        assert result.speedup is None
        # Il tempo Python deve essere positivo
        assert result.python.mean > 0

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            run_benchmark(str(tmp_path / "nonexistent.py"), verbose=False)
