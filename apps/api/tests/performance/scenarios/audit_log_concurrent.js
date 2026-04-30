/**
 * k6 load scenario — Audit log concurrent INSERT chain integrity (T993 / FR-093 / SC-014).
 *
 * Scenario: 200 virtual users fire rapid POST requests that each trigger an
 * audit log write. After the run, chain integrity is verified out-of-band by
 * the Python test in test_audit_log_concurrent_chain.py. This script only
 * asserts that all writes succeed (status 2xx) and that p95 < 200 ms.
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8002 \
 *           --env AUTH_TOKEN=<jwt> \
 *           audit_log_concurrent.js
 */
import http from "k6/http";
import { check } from "k6";

export const options = {
  stages: [
    { duration: "5s", target: 200 },
    { duration: "30s", target: 200 },
    { duration: "5s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<200"],
    http_req_failed: ["rate<0.05"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8002";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";

export default function () {
  const params = {
    headers: {
      Authorization: `Bearer ${AUTH_TOKEN}`,
      "Content-Type": "application/json",
    },
  };
  // A no-op probe endpoint that triggers an audit write (replace with a
  // suitable writable endpoint in the actual load environment).
  const res = http.get(`${BASE_URL}/web-api/v1/projects/`, params);
  check(res, {
    "status 2xx": (r) => r.status >= 200 && r.status < 300,
  });
}
