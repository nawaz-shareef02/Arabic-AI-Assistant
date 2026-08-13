import sys
import os
import time
import statistics
import concurrent.futures
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("load_test_rag")


def compute_percentiles(latencies):
    if not latencies:
        return {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "max": 0}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    p50 = sorted_lat[int(n * 0.50)]
    p95 = sorted_lat[min(int(n * 0.95), n - 1)]
    p99 = sorted_lat[min(int(n * 0.99), n - 1)]
    avg = statistics.mean(sorted_lat)
    max_lat = sorted_lat[-1]
    return {
        "p50": round(p50 * 1000, 2),
        "p95": round(p95 * 1000, 2),
        "p99": round(p99 * 1000, 2),
        "avg": round(avg * 1000, 2),
        "max": round(max_lat * 1000, 2),
    }


def execute_single_request(client, headers, kb_id, query):
    start = time.perf_counter()
    try:
        res = client.post(
            "/api/v1/chat/",
            json={"question": query, "knowledge_base_id": kb_id},
            headers=headers,
        )
        elapsed = time.perf_counter() - start
        return elapsed, res.status_code == 200
    except Exception:
        elapsed = time.perf_counter() - start
        return elapsed, False


def run_concurrency_test(client, headers, kb_id, concurrency_level, total_requests):
    logger.info(f"\n--- Running Load Test: Concurrency = {concurrency_level} users ({total_requests} total requests) ---")
    queries = [
        "What is the platform specification of ArabIQ?",
        "ما هي تقنيات منصة عرب آي كيو؟",
        "How does hybrid search work in ArabIQ?",
        "كيف يعمل الدمج الترتيبي التبادلي RRF؟",
        "Tell me about FastAPI and PostgreSQL integration.",
    ]

    latencies = []
    success_count = 0
    fail_count = 0

    start_time = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency_level) as executor:
        futures = []
        for i in range(total_requests):
            query = queries[i % len(queries)]
            futures.append(executor.submit(execute_single_request, client, headers, kb_id, query))

        for future in concurrent.futures.as_completed(futures):
            elapsed, success = future.result()
            latencies.append(elapsed)
            if success:
                success_count += 1
            else:
                fail_count += 1

    total_duration = time.perf_counter() - start_time
    stats = compute_percentiles(latencies)
    throughput = round(total_requests / total_duration, 2)

    logger.info(f"Results for {concurrency_level} Concurrent Users:")
    logger.info(f"  • Total Time      : {total_duration:.2f} s")
    logger.info(f"  • Throughput      : {throughput} req/sec")
    logger.info(f"  • Success Rate    : {success_count}/{total_requests} ({round(success_count/total_requests*100, 1)}%)")
    logger.info(f"  • Latency p50     : {stats['p50']} ms")
    logger.info(f"  • Latency p95     : {stats['p95']} ms")
    logger.info(f"  • Latency p99     : {stats['p99']} ms")
    logger.info(f"  • Latency Avg     : {stats['avg']} ms")

    return stats


def run_full_load_test_suite():
    logger.info("==================================================")
    logger.info("STARTING SPRINT 12.5 LOAD & PERFORMANCE SUITE")
    logger.info("==================================================")

    client = TestClient(app)

    # 1. Setup Auth & KB
    token_res = client.post(
        "/api/v1/auth/token",
        data={"username": "loadadmin@arabiq.ai", "password": "Password123!"}
    )
    if token_res.status_code != 200:
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "loadadmin@arabiq.ai",
                "password": "Password123!",
                "full_name": "Load Test Admin",
                "organization": "ArabIQ",
                "preferred_language": "en"
            }
        )
        token_res = client.post(
            "/api/v1/auth/token",
            data={"username": "loadadmin@arabiq.ai", "password": "Password123!"}
        )

    token = token_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    kb_res = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Load Testing KB", "description": "KB for benchmarking"},
        headers=headers
    )
    kb_id = kb_res.json()["id"]

    # 2. Run concurrency levels: 10, 50, 100
    run_concurrency_test(client, headers, kb_id, concurrency_level=10, total_requests=20)
    run_concurrency_test(client, headers, kb_id, concurrency_level=50, total_requests=50)
    run_concurrency_test(client, headers, kb_id, concurrency_level=100, total_requests=100)

    logger.info("\n==================================================")
    logger.info("✓ LOAD TESTING SUITE FINISHED SUCCESSFULLY")
    logger.info("==================================================")


if __name__ == "__main__":
    run_full_load_test_suite()
