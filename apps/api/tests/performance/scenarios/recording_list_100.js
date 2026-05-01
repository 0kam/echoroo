/**
 * k6 load scenario — Recording list 100 items (T991 / NFR-004).
 *
 * Scenario: 50 virtual users ramp up over 30 s, hold for 60 s, then ramp
 * down over 30 s. Each iteration fetches the first 100 recordings for a
 * pre-seeded project and asserts status 200 + p95 < 800 ms.
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8002 \
 *           --env PROJECT_ID=<uuid> \
 *           --env AUTH_TOKEN=<jwt> \
 *           recording_list_100.js
 */
import http from "k6/http";
import { check } from "k6";

export const options = {
  stages: [
    { duration: "30s", target: 50 },
    { duration: "60s", target: 50 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<800"],
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
    `${BASE_URL}/web-api/v1/projects/${PROJECT_ID}/recordings?limit=100`,
    params
  );
  check(res, {
    "status is 200": (r) => r.status === 200,
    "has items array": (r) => Array.isArray(r.json("items")),
  });
}
