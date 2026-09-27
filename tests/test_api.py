"""
Test cho service mà Tutorial 04 giám sát.

Metric cũng là một phần của contract, không phải thứ trang trí: nếu counter
ngừng tăng thì dashboard và alert đều mù, mà service vẫn trả 200 như thường.
Nên ở đây test cả hành vi HTTP lẫn hành vi metric.
"""
from prometheus_client import REGISTRY


def value(name, labels=None):
    v = REGISTRY.get_sample_value(name, labels or {})
    return 0.0 if v is None else v


class TestHealth:
    def test_health_reports_model_loaded(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["model_loaded"] is True
        assert body["version"] == "1.0.0"

    def test_model_loaded_gauge_is_one(self, client):
        assert value("wdbc_model_loaded") == 1.0

    def test_model_info_carries_versions_as_labels(self, client):
        # Info pattern: gauge luôn bằng 1, thông tin nằm ở label.
        samples = [s for m in REGISTRY.collect() for s in m.samples
                   if s.name == "wdbc_model_info"]
        assert len(samples) == 1
        assert samples[0].value == 1.0
        assert samples[0].labels["version"] == "1.0.0"
        assert samples[0].labels["sklearn_version"]


class TestPredict:
    def test_valid_request_returns_prediction(self, client, sample):
        r = client.post("/predict", json={"sample_id": "T-001", "features": sample})
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] in {"benign", "malignant"}
        assert 0.0 <= body["probability"] <= 1.0
        assert body["threshold"] == 0.5
        assert body["model_version"] == "1.0.0"

    def test_missing_feature_returns_422(self, client, sample, features):
        broken = {k: v for k, v in sample.items() if k != features[0]}
        r = client.post("/predict", json={"sample_id": "T-002", "features": broken})
        assert r.status_code == 422
        assert features[0] in r.json()["detail"]

    def test_missing_feature_increments_error_counter(self, client, sample, features):
        labels = {"reason": "missing_features"}
        before = value("wdbc_errors_total", labels)
        broken = {k: v for k, v in sample.items() if k != features[0]}
        client.post("/predict", json={"sample_id": "T-003", "features": broken})
        assert value("wdbc_errors_total", labels) == before + 1

    def test_prediction_increments_counter_for_its_outcome(self, client, sample):
        r = client.post("/predict", json={"sample_id": "T-004", "features": sample})
        outcome = r.json()["outcome"]
        labels = {"outcome": outcome}
        before = value("wdbc_predictions_total", labels)
        client.post("/predict", json={"sample_id": "T-005", "features": sample})
        assert value("wdbc_predictions_total", labels) == before + 1

    def test_latency_histogram_observes_each_prediction(self, client, sample):
        before = value("wdbc_prediction_latency_seconds_count")
        client.post("/predict", json={"sample_id": "T-006", "features": sample})
        assert value("wdbc_prediction_latency_seconds_count") == before + 1

    def test_malignant_share_stays_a_fraction(self, client, sample):
        client.post("/predict", json={"sample_id": "T-007", "features": sample})
        assert 0.0 <= value("wdbc_malignant_share") <= 1.0


class TestMetricsEndpoint:
    def test_serves_prometheus_exposition_format(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")

    def test_exposes_every_metric_the_alerts_depend_on(self, client):
        # Mỗi tên dưới đây đều bị monitoring/prometheus/alerts/model.yml dùng.
        # Đổi tên metric mà quên sửa rule thì alert im lặng chứ không báo lỗi.
        body = client.get("/metrics").text
        for name in ("wdbc_predictions_total",
                     "wdbc_errors_total",
                     "wdbc_prediction_latency_seconds_bucket",
                     "wdbc_model_loaded",
                     "wdbc_model_info",
                     "wdbc_malignant_share"):
            assert name in body, f"thiếu metric {name}"

    def test_latency_buckets_bracket_the_expected_range(self, client):
        # Buckets dừng ở 1s, và alert SlowPredictions đặt ngưỡng p95 > 50ms.
        # Không có bucket nào quanh 50ms thì con số p95 là nội suy vô nghĩa.
        body = client.get("/metrics").text
        assert 'le="0.05"' in body
        assert 'le="1.0"' in body

    def test_cardinality_stays_constant_without_the_trap(self, client, sample):
        # 23 series, và con số đó KHÔNG được tăng theo lượng request.
        def series():
            return sum(1 for line in client.get("/metrics").text.splitlines()
                       if line.startswith("wdbc_") and not line.startswith("#"))
        before = series()
        for i in range(20):
            client.post("/predict", json={"sample_id": f"T-1{i:03d}", "features": sample})
        assert series() == before
