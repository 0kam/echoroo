/**
 * k6 load scenario — Auth + permission gate latency (T992 / NFR-001 / SC-015).
 *
 * Scenario: 100 virtual users each hitting GET /web-api/v1/projects/:id once
 * per iteration. Measures the combined auth-middleware + permission-gate
 * latency and asserts p95 < 30 ms.
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8002 \
 *           --env PROJECT_ID=<uuid> \
 *           --env AUTH_TOKEN=<jwt> \
 *           auth_permission_check.js
 */
import http from "k6/http";
import { check } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 100 },
    { duration: "30s", target: 100 },
    { duration: "10s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<30"],
    http_req_failed: ["rate<0.01"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8002";
const PROJECT_ID = __ENV.PROJECT_ID || "00000000-0000-0000-0000-000000000001";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";

export default function () {
  const params = {
    headers: {
      Authorization: `Bearer ${AUTH_TOKEN}`,
    },
  };
  const res = http.get(
    `${BASE_URL}/web-api/v1/projects/${PROJECT_ID}`,
    params
  );
  check(res, {
    "status 200 or 403": (r) => r.status === 200 || r.status === 403,
  });
}
