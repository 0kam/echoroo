# Echoroo Web

SvelteKit-based frontend for the Echoroo bioacoustic analysis platform.

## Tech Stack

- **Framework**: SvelteKit + Svelte 5
- **State Management**: TanStack Query (Svelte) + Svelte Stores
- **Styling**: Tailwind CSS
- **TypeScript**: 5.x with strict mode
- **Testing**: Vitest + Playwright
- **Linting**: ESLint + Prettier

## Prerequisites

- Node.js 20+
- npm or pnpm

## Installation

```bash
npm install
```

## Development

```bash
# Start development server
npm run dev

# Type check
npm run check

# Lint
npm run lint

# Format
npm run format

# Run unit tests
npm run test

# Run E2E tests
npm run test:e2e
```

### Local Trusted-Device Browser Testing

Use these focused checks when changing login, 2FA, account security, or trusted-device UI. Run commands from `apps/web` with the API available at `ECHOROO_API_URL`.

```bash
npm run test -- src/routes/\(auth\)/verify-email/verify-email.spec.ts
npm run test -- src/routes/\(auth\)/login/login-trusted-device.spec.ts
npm run test -- src/lib/api/trusted-devices.test.ts
npm run test:e2e -- tests/e2e/auth-trusted-device.spec.ts
```

Manual browser flow:

1. Start the API with `TRUSTED_DEVICE_REGISTRATION_ENABLED=true` and, for bypass testing, `TRUSTED_DEVICE_BYPASS_ENABLED=true`.
2. Start the web app with `npm run dev`.
3. Log in as a TOTP-enabled non-privileged user in a fresh browser context.
4. Complete the 2FA challenge with "trust this device" selected.
5. Confirm the user reaches the app and the browser has an `echoroo_trusted_device` cookie.
6. Log out without clearing site data, then log in again in the same browser context.
7. Confirm the login completes without showing the TOTP form.
8. Repeat login in a separate browser context or after clearing cookies and confirm the TOTP form is required.
9. Revoke the trusted device from the account security/profile view and confirm the original browser requires TOTP on the next login.

Also verify that the trusted-device checkbox is absent from the password-only step and is submitted only with second-factor confirmation. Admin or high-risk workflows must continue to require their existing stronger verification even when the routine login bypass succeeds.

## Project Structure

```
src/
├── lib/
│   ├── api/         # API client and query functions
│   ├── stores/      # Svelte stores for global state
│   ├── components/  # Reusable Svelte components
│   └── types/       # TypeScript type definitions
├── routes/
│   ├── (auth)/      # Authentication routes (login, signup)
│   ├── (app)/       # Main application routes
│   ├── (admin)/     # Admin panel routes
│   └── setup/       # Initial setup flow
└── app.html         # HTML template
```

## Building for Production

```bash
npm run build
```

The production build will be output to the `build/` directory.

## Environment Variables

Create a `.env` file in the root directory:

```env
ECHOROO_API_URL=http://localhost:8000
```

## Docker

This application is designed to run in a Docker container. See the main project README for Docker setup instructions.

## Contributing

Please refer to the main project CONTRIBUTING.md for contribution guidelines.
