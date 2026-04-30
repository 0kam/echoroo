/**
 * k6 load scenario — WebAuthn register/challenge latency (T992c).
 *
 * Measures POST /web-api/v1/auth/2fa/webauthn/register begin latency.
 * Each iteration requires a valid interim token so this scenario is best
 * run against a dedicated load-test fixture that pre-mints tokens.
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8002 \
 *           --env INTERIM_TOKEN=<webauthn_register token> \
 *           webauthn_challenge.js
 */
import http from "k6/http";
import { check } from "k6";

export const options = {
  scenarios: {
    webauthn_begin: {
      executor: "constant-arrival-rate",
      rate: 20,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<100"],
    http_req_failed: ["rate<0.05"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8002";
const INTERIM_TOKEN = __ENV.INTERIM_TOKEN || "";

export default function () {
  const params = {
    headers: {
      Authorization: `Bearer ${INTERIM_TOKEN}`,
      "Content-Type": "application/json",
    },
  };
  // Probe the register endpoint; in load testing this returns a challenge blob.
  const res = http.post(
    `${BASE_URL}/web-api/v1/auth/2fa/webauthn/register`,
    JSON.stringify({ stage: "begin" }),
    params
  );
  check(res, {
    "non-5xx": (r) => r.status < 500,
  });
}
