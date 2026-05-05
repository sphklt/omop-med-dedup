import os
import sys
import pytest
import pandas as pd

# Make src/ importable for all test modules — defined once here instead of per file
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from normalize import _prepare_mapping

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@pytest.fixture(scope="session")
def mapping_df():
    return _prepare_mapping(pd.read_csv(os.path.join(_DATA_DIR, "mock_concept_mapping.csv")))
