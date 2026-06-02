/**
 * Client-side TOTP enrollment helper for the public invitation signup flow
 * (spec/011 US2, T220).
 *
 * The public invitation accept endpoint has NO server-side TOTP "begin"
 * step for the new-user branch. Instead the frontend generates a fresh
 * base32 secret in the browser, renders the `otpauth://` provisioning URI
 * as a QR code, and sends `{ totp_secret_signed: <secret>, totp_initial_code:
 * <6-digit code> }` to the accept endpoint. The backend confirms enrollment
 * with `pyotp.TOTP(secret, digits=6, interval=30)`, which matches the
 * `otplib` defaults (SHA1 / 6 digits / 30s period).
 *
 * SECURITY: the generated secret and provisioning URI are sensitive. They
 * MUST NEVER be logged (no `console.*`) — they live only in component state
 * and are transmitted once over HTTPS.
 */

import { generateSecret, generateURI } from 'otplib';
import QRCode from 'qrcode';

/** Issuer label shown in authenticator apps. Mirrors backend `ISSUER_NAME`. */
const ISSUER = 'Echoroo';

export interface TotpEnrollArtifacts {
  /** Base32 secret, client-generated — sent verbatim as `totp_secret_signed`. */
  secret: string;
  /** `otpauth://totp/Echoroo:<email>?secret=...&issuer=Echoroo` provisioning URI. */
  provisioningUri: string;
}

/**
 * Generate a fresh base32 TOTP secret + `otpauth://` URI bound to `email`.
 *
 * Uses the `otplib` v13 functional helpers with their defaults (SHA1 / 6
 * digits / 30s period), which match the backend's `pyotp.TOTP(secret, 6, 30)`
 * verification. Never logs the returned secret.
 */
export function generateTotpEnrollment(email: string): TotpEnrollArtifacts {
  const secret = generateSecret();
  const provisioningUri = generateURI({ issuer: ISSUER, label: email, secret });
  return { secret, provisioningUri };
}

/**
 * Render the `otpauth://` provisioning URI to a PNG data URL for an
 * `<img src>`. Uses the same options as the canonical 2FA-setup page.
 */
export async function totpQrDataUrl(provisioningUri: string): Promise<string> {
  return QRCode.toDataURL(provisioningUri, {
    width: 240,
    margin: 1,
    errorCorrectionLevel: 'M',
  });
}
