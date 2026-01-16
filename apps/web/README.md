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
