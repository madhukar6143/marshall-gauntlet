import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from payments import fee, to_cents


def test_to_cents():
    assert to_cents(12.34) == 1234


def test_fee():
    assert fee(1000) == 59
