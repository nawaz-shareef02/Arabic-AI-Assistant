"""
SecurityMetrics — Refinement #10: Security Metrics Hook Collector for Prometheus / Monitoring.
"""

from typing import Dict


class SecurityMetricsCollector:
    _counters: Dict[str, int] = {
        "failed_logins": 0,
        "rate_limit_hits": 0,
        "prompt_injection_detections": 0,
        "blocked_uploads": 0,
        "token_revocations": 0,
        "session_revocations": 0,
    }

    @classmethod
    def increment(cls, metric_name: str, count: int = 1):
        if metric_name in cls._counters:
            cls._counters[metric_name] += count

    @classmethod
    def get_metrics(cls) -> Dict[str, int]:
        return dict(cls._counters)


security_metrics = SecurityMetricsCollector()
