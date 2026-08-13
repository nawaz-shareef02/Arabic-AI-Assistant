import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules["pytest"] = "active"  # Bypass rate limiters for test runner

from fastapi.testclient import TestClient
from app.main import app
from app.database.session import SessionLocal
from app.core.prometheus_exporter import metrics_registry, get_prometheus_metrics_text
from app.core.telemetry import start_ai_stage_span
from app.services.observability_service import ObservabilityService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("s14_5_validation")


def run_s14_5_validation():
    logger.info("==================================================")
    logger.info("STARTING SPRINT 14.5 ENTERPRISE OBSERVABILITY VALIDATION")
    logger.info("==================================================")

    db = SessionLocal()
    client = TestClient(app)

    try:
        # 1. Prometheus /metrics Endpoint Test
        logger.info("--- Step 1: Testing Prometheus /metrics Endpoint ---")
        metrics_res = client.get("/metrics")
        assert metrics_res.status_code == 200, f"/metrics returned {metrics_res.status_code}"
        metrics_text = metrics_res.text
        assert "arabiq_http_requests_total" in metrics_text, "Missing arabiq_http_requests_total metric"
        assert "arabiq_security_prompt_injections_total" in metrics_text, "Missing security metric"
        logger.info("✓ Prometheus /metrics Endpoint PASSED")

        # 2. Three-State Health Probes Test (/health, /ready, /live)
        logger.info("--- Step 2: Testing Three-State Health Probes ---")
        health_res = client.get("/health")
        assert health_res.status_code == 200
        health_json = health_res.json()
        assert health_json["status"] in ("Healthy", "Degraded", "Unhealthy")
        assert "postgres" in health_json and "redis" in health_json

        ready_res = client.get("/ready")
        assert ready_res.status_code in (200, 503)
        ready_json = ready_res.json()
        assert "ready" in ready_json and "status" in ready_json

        live_res = client.get("/live")
        assert live_res.status_code == 200
        assert live_res.json()["alive"] is True
        logger.info("✓ Three-State Health Probes PASSED")

        # 3. OpenTelemetry AI Sub-Stage Spans Test
        logger.info("--- Step 3: Testing OpenTelemetry AI Stage Spans ---")
        with start_ai_stage_span("Hybrid Retrieval", request_id="req-123", correlation_id="corr-456", org_id=1, user_id=1) as span_attrs:
            assert span_attrs["ai_stage"] == "Hybrid Retrieval"
            assert span_attrs["request_id"] == "req-123"
        logger.info("✓ OpenTelemetry AI Stage Spans PASSED")

        # 4. Business & AI Quality Metrics Test
        logger.info("--- Step 4: Testing ObservabilityService ---")
        obs_svc = ObservabilityService(db)
        biz_metrics = obs_svc.get_business_metrics()
        assert "total_users" in biz_metrics and "total_organizations" in biz_metrics

        ai_metrics = obs_svc.get_ai_quality_metrics()
        assert "average_retrieval_score" in ai_metrics and "prompt_risk_distribution" in ai_metrics
        logger.info("✓ ObservabilityService Business & AI Metrics PASSED")

        # 5. Prometheus Alert Rules & Grafana Dashboards Check
        logger.info("--- Step 5: Testing Prometheus Alerts & Grafana Dashboards Config ---")
        alerts_path = os.path.join(os.path.dirname(__file__), "..", "monitoring", "prometheus_alerts.yml")
        dashboards_path = os.path.join(os.path.dirname(__file__), "..", "monitoring", "grafana_dashboards.json")
        assert os.path.exists(alerts_path), "prometheus_alerts.yml missing"
        assert os.path.exists(dashboards_path), "grafana_dashboards.json missing"
        logger.info("✓ Prometheus Alerts & Grafana Dashboards Config PASSED")

        logger.info("==================================================")
        logger.info("✓ ALL SPRINT 14.5 ENTERPRISE OBSERVABILITY TESTS PASSED SUCCESSFULLY")
        logger.info("==================================================")
        return True

    finally:
        db.close()


if __name__ == "__main__":
    run_s14_5_validation()
