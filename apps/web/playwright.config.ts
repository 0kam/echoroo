import type { PlaywrightTestConfig } from '@playwright/test';

const config: PlaywrightTestConfig = {
  testDir: 'tests/e2e',
  testMatch: /(.+\.)?(test|spec)\.[jt]s/,
  timeout: 30000, // 30 seconds per test
  webServer: {
    command: 'npm run dev',
    port: 5173,
    timeout: 120000, // 2 minutes to start dev server
    reuseExistingServer: !process.env.CI,
  },
  use: {
    baseURL: 'http://localhost:5173',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  // Run tests in parallel
  workers: process.env.CI ? 1 : undefined,
  // Fail build on CI if you accidentally left test.only in the source code
  forbidOnly: !!process.env.CI,
  // Retry on CI only
  retries: process.env.CI ? 2 : 0,
  // Reporter to use
  reporter: process.env.CI ? 'github' : 'list',
};

export default config;
