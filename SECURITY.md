# Security policy

voice-tutor is a single-user, self-hosted app: it has **no authentication** and is meant to run on `localhost` or a trusted LAN. Exposing it to the internet is out of scope (see [docs/hardware.md](docs/hardware.md#remote-access)).

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: **Security → Report a vulnerability** ([direct link](https://github.com/GeneralErdon/engish-teacher-erdon/security/advisories/new)).

Include what you found, how to reproduce it and the impact you expect. You will get an answer within 7 days; fixes are released as soon as they are ready and credited in the advisory unless you prefer otherwise.

## Supported versions

Until the first release (`v1.0.0`), only the latest commit on `master` receives security fixes.

## Data at rest

Settings saved from the app, API keys included, live in an encrypted SQLite database (SQLCipher), and each API key is sealed again with AES-256-GCM. The master key is never stored in the database: it lives in the OS keyring, in `VT_SECRET_KEY`, or in a `0600` key file where there is no keyring. Details: [docs/configuration.md#encryption](docs/configuration.md#encryption).

## What is already checked automatically

Every pull request and a weekly schedule run `uv audit` and `pnpm audit` (Python and JavaScript dependencies), Trivy (Rust dependencies, secrets, Dockerfiles), CodeQL (Python, TypeScript, Rust, GitHub Actions) and GitHub's dependency review; `gitleaks` blocks secrets at commit time. Details: [.github/README.md](.github/README.md).
