import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from analysis_core import professor_ksim_step, validate_reference_first_iteration, validate_reference_intervention, make_template_xlsx, parse_matrix_upload


def test_baseline_reference():
    assert validate_reference_first_iteration()["passed"]


def test_intervention_reference():
    result = validate_reference_intervention()
    assert result["passed_first_intervention_step"]
    assert result["passed_beetle_activation_t4"]
    assert result["passed_t4_to_t5_reference"]


def test_zero_matrix_state_stays_constant():
    x = np.array([0.2, 0.7])
    a = np.zeros((2, 2))
    next_x, details = professor_ksim_step(x, a, 1.0)
    assert np.allclose(next_x, x)
    assert np.allclose(details["Exponent"], 1.0)


def test_template_is_valid_xlsx():
    data = make_template_xlsx(["A", "B", "C"])
    assert data[:2] == b"PK"
    assert len(data) > 1000


if __name__ == "__main__":
    test_baseline_reference()
    test_intervention_reference()
    test_zero_matrix_state_stays_constant()
    test_template_is_valid_xlsx()
    print("All KSIM tests passed.")
