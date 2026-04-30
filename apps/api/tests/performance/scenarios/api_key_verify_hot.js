/**
 * k6 load scenario — API key hot-path verify (T992d).
 *
 * Measures Bearer key verification throughput on the programmatic /api/v1
 * prefix. 500 VUs fire requests carrying a pre-issued echoroo_* key and
 * assert p95 < 30 ms (NFR-001 budget for auth+permission combined).
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8002 \
 *           --env API_KEY=echoroo_<prefix>_<secret> \
 *           api_key_verify_hot.js
 */
import http from "k6/http";
import { check } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 500 },
    { duration: "30s", target: 500 },
    { duration: "10s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<30"],
    http_req_failed: ["rate<0.01"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8002";
const API_KEY = __ENV.API_KEY || "echoroo_placeholder_secret";

export default function () {
  const params = {
    headers: {
      Authorization: `Bearer ${API_KEY}`,
    },
  };
  // Any authenticated read endpoint that goes through DbApiKeyVerifier.
  const res = http.get(`${BASE_URL}/api/v1/projects/`, params);
  check(res, {
    "non-5xx": (r) => r.status < 500,
  });
}
