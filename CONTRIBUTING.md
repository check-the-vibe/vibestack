# Contributing to VibeStack

Thanks for helping improve VibeStack. Keep changes practical: a clear problem,
a small coherent implementation, tests proportional to risk, and documentation
for user-visible or operational changes are more useful than additional process.

## Development workflow

Read [AGENTS.md](AGENTS.md) and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) before changing a running desktop.
The short loop is:

```bash
npm ci
npx playwright install chromium
bin/vibestack-dev test
bin/vibestack-dev build vibestack:change-YYYYMMDD
bin/vibestack-dev accept vibestack:change-YYYYMMDD
```

Use focused tests while iterating, but run the complete source suite before
submitting. Changes that affect the image or runtime must pass disposable image
acceptance. Do not use a personal `/data` directory for acceptance tests.

## Pull requests

- Explain the user-visible outcome and important trade-offs.
- Add or update tests for changed behavior and failure paths.
- Keep `README.md`, `docs/DEVELOPMENT.md`, `docs/SPEC.md`, and the packaged
  runtime agent guidance aligned when their contracts change.
- Do not commit credentials, persistent user data, logs, screenshots, browser
  profiles, build output, or generated caches.
- Preserve loopback-by-default networking. Treat automation, setup, terminal,
  desktop streaming, password handling, and package installation as security
  boundaries rather than ordinary web endpoints.

There is no required issue template, commit-message format, or contributor
agreement. Match the surrounding style and avoid new dependencies when the
standard library or existing tooling is sufficient.
