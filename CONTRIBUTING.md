# Contributing

Thanks for helping! This page is the short version; the details live in [docs/development.md](docs/development.md) and [.github/README.md](.github/README.md).

## 1. Set up

Install the toolchain for your OS ([README → Requirements](README.md#requirements)), then:

```bash
git clone https://github.com/GeneralErdon/engish-teacher-erdon.git voice-tutor
cd voice-tutor
just setup     # dependencies + cargo-llvm-cov + git hooks (pre-commit, commit-msg, pre-push)
```

## 2. Branch (git flow)

```bash
git switch develop && git pull
git switch -c feat/short-name      # or fix/short-name
```

`master` holds releases and `develop` is the integration branch; both only change through pull requests with CI green. Never commit to them directly (a hook stops you).

## 3. Commit

[Conventional Commits](https://www.conventionalcommits.org/), checked by commitlint on every commit and again in CI:

```
feat(api): stream TTS sentence by sentence
fix(desktop): grant the microphone on Windows
docs: explain the amd profile
```

Types: `feat fix perf refactor docs test build ci chore style revert`. Scopes (optional): `api pron contracts desktop ui docker ci deps docs release`.

## 4. Test

Every change comes with tests. Coverage must stay **≥ 97 %** (lines, branches and functions) in Python, TypeScript and Rust; `just test` fails below it, and so does CI. The thresholds are a floor that only goes up: never lower them to make a build pass.

```bash
just check     # lint + types + architecture rules
just test      # all suites with coverage
```

The `pre-push` hook runs types and tests for whatever you changed, so a push rarely surprises CI.

## 5. Open the pull request

Against `develop`, using the template. CI must be green (`CI ok`), plus the Security and CodeQL checks. Keep pull requests small and focused; architecture changes add a short ADR to [docs/architecture.md](docs/architecture.md#architecture-decisions-summary).
