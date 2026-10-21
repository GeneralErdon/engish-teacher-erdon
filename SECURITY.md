# Security policy

voice-tutor is a single-user, self-hosted app: it has **no authentication** and is meant to run on `localhost` or a trusted LAN. Exposing it to the internet is out of scope (see [docs/hardware.md](docs/hardware.md#remote-access)).

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: **Security → Report a vulnerability** ([direct link](https://github.com/GeneralErdon/engish-teacher-erdon/security/advisories/new)).

Include what you found, how to reproduce it and the impact you expect. You will get an answer within 7 days; fixes are released as soon as they are ready and credited in the advisory unless you prefer otherwise.

## Supported versions

Until the first release (`v1.0.0`), only the latest commit on `master` receives security fixes.

## What is already checked automatically

Every pull request and a weekly schedule run `uv audit` and `pnpm audit` (Python and JavaScript dependencies), Trivy (Rust dependencies, secrets, Dockerfiles), CodeQL (Python, TypeScript, Rust, GitHub Actions) and GitHub's dependency review; `gitleaks` blocks secrets at commit time. Details: [.github/README.md](.github/README.md).
