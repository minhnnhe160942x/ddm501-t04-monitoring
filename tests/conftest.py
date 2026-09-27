"""
Model là build artefact: Dockerfile train nó trong lúc build. Test cũng cần
đúng như vậy, nên nếu chưa có thì train một lần rồi dùng lại cho cả phiên.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def model_exists():
    if not (ROOT / "models" / "model.joblib").exists():
        from scripts.train_model import main as train
        train()
    return ROOT / "models"


@pytest.fixture(scope="session")
def features(model_exists):
    return json.loads((model_exists / "model_card.json").read_text())["features"]


@pytest.fixture(scope="session")
def sample(features):
    """Một hàng thật lấy từ dataset, đủ mọi feature model yêu cầu."""
    import pandas as pd
    row = pd.read_csv(ROOT / "data" / "raw" / "wdbc.csv").dropna().iloc[0]
    return {f: float(row[f]) for f in features}


@pytest.fixture(scope="session")
def client():
    # Dùng context manager thì startup event mới chạy -- không có nó model
    # không được nạp và mọi request đều 503.
    from app.main import app
    with TestClient(app) as c:
        yield c
