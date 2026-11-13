import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.main import danger_check, extract_record

def test_pregnancy_bleeding_flag():
    assert danger_check("The beneficiary reports bleeding during pregnancy.")

def test_newborn_fever_flag():
    assert danger_check("Newborn has high fever.")

def test_normal_note_no_flag():
    assert danger_check("ANC checkup completed, weight 52 kilo.") == []

def test_weight_extraction():
    record = extract_record("ANC checkup, weight 2.8 kilo, TT injection completed.", "SYN-1001")
    assert record["weight_kg"] == 2.8
    assert record["visit_type"] == "ANC"
