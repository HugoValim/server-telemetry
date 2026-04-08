import subprocess
import sys
from pathlib import Path


def run(*args: str) -> str:
    app = Path(__file__).parent / "app.py"
    cmd = [sys.executable, str(app), *args]
    return subprocess.check_output(cmd, text=True).strip()


def test_mean():
    assert run("1", "2", "3") == "2.0"


def test_sum():
    assert run("--mode", "sum", "1", "2", "3") == "6.0"


def test_min():
    assert run("--mode", "min", "1", "-5", "2") == "-5.0"


def test_max():
    assert run("--mode", "max", "1", "-5", "2") == "2.0"
