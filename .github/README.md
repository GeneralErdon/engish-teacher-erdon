# CI/CD: what runs, what blocks

Every change reaches `develop` (and later `master`) through a pull request whose checks prove it is tested. The same gates run **locally as git hooks** (fast feedback) and **in CI** (where `git commit --no-verify` or the web editor cannot skip them).

## Workflows

| Workflow | Runs on | Job | What it enforces |
|---|---|---|---|
| `ci.yml` | every PR; push to `master` / `develop` | **Commit messages** | commitlint over every commit in the PR (PRs only) |
| | | **Hygiene** | the repository-wide pre-commit hooks (whitespace, YAML/TOML/JSON, large files, private keys, `uv.lock` up to date, ruff, zizmor on the workflows) |
| | | **Python** | ruff, mypy `--strict`, import-linter contracts, pytest with **≥ 97 %** coverage |
| | | **UI** | ESLint (type-aware), `tsc`, Prettier, Vitest with **≥ 97 %** coverage, production build; generated code up to date (`just types` and the route tree must not change) |
| | | **Desktop** (Ubuntu + Windows) | `cargo fmt`, clippy pedantic `-D warnings`, `cargo test` under cargo-llvm-cov with **≥ 97 %** coverage |
| | | **Docker** | `compose.yaml` valid for every profile; `api` and `pron` images build |
| | | **CI ok** | aggregate: fails if any job above failed or was cancelled. **The check branch protection requires** |
| `security.yml` | every PR; push; weekly | **Trivy** | HIGH/CRITICAL fixable CVEs in `Cargo.lock`; secrets; Dockerfile misconfigurations. Policy in `trivy.yaml`; results in the Security tab |
| | | **Audit** | `uv audit` (every Python package in `uv.lock`, OSV database, SARIF to the Security tab) and `pnpm audit` (high/critical). Trivy cannot parse uv's virtual-workspace lockfile nor pnpm 12's two-document lockfile, so each ecosystem uses its own auditor |
| | | **Dependency review** | blocks PRs that add a dependency with a known HIGH vulnerability |
| `codeql.yml` | every PR; push; weekly | **CodeQL** | `security-extended` queries for Python, TypeScript, Rust and the workflows themselves |
| `apps.yml` | push to `develop`; by hand (`gh workflow run apps.yml --ref <branch>`) | **Desktop** (Ubuntu + Windows) | builds the installers (`.deb`, `.rpm`, `.AppImage`; `.msi`, setup `.exe`) and keeps them 30 days as the run's artifacts, to download and try between releases |
| `release.yml` | tag `v*` | images + installers | multi-arch `api`/`pron` images to GHCR; Windows and Linux installers in a draft release (Phase 3) |

Coverage reports are uploaded to [Codecov](https://about.codecov.io/) (flags `python`, `ui`, `rust`) for the PR comment and the README badge. The **97 % floor itself is enforced by the test runners**, so CI fails before a regression is even uploaded.

## Hooks vs CI

| Gate | pre-commit | commit-msg | pre-push | CI |
|---|---|---|---|---|
| whitespace, EOF, YAML/TOML/JSON, merge markers, large files | yes | | | Hygiene |
| private keys / secrets | `detect-private-key`, gitleaks | | | Hygiene, Trivy |
| no direct commit to `master` / `develop` | yes | | | branch protection |
| `uv.lock` matches `pyproject.toml` | yes | | | Hygiene, Python (`--locked`) |
| ruff (lint + format) | yes | | | Hygiene, Python |
| ESLint, Prettier | yes | | | UI |
| `cargo fmt` | yes | | | Desktop |
| zizmor (workflow security) | yes | | | Hygiene |
| Conventional Commits | | commitlint | | Commit messages |
| mypy `--strict`, import-linter | | | yes | Python |
| `tsc` | | | yes | UI |
| clippy | | | yes | Desktop |
| tests | | | yes (no coverage) | Python, UI, Desktop (with coverage) |
| coverage ≥ 97 % | | | | Python, UI, Desktop |
| image builds, compose config | | | | Docker |
| CVEs (`just security` locally), CodeQL | | | | Security, CodeQL |

Pre-push hooks only run for the languages you touched. `just check` + `just test` locally is the same set CI runs.

## Coverage policy

- **Floor: 97 %** of lines, branches and functions (regions for Rust) in every language, set in `pyproject.toml` (`fail_under`), `apps/desktop/vite.config.ts` (`thresholds`) and the `justfile` (`COVERAGE_MIN` for cargo-llvm-cov).
- It is a floor, not a target: raise it as the suite grows; **never lower it to make a build pass**. Lowering it is a visible diff in a pull request, which is the point.
- Exclusions are few and justified where they are declared: entrypoints (`src/main.tsx`, `main.rs`), code that needs a real window/webview (`src-tauri/src/shell.rs`, smoke-tested by hand before each release), generated code and test helpers.

## Branch protection

`master` and `develop` have repository rulesets: changes only through pull requests, **`CI ok` must pass**, no force pushes, no deletion. GitHub counts a *skipped* required check as passing, which is why the single aggregate `CI ok` job is required instead of each job: it fails whenever any job fails or is cancelled.

## Supply chain

- Every action is pinned to a **commit SHA** (the comment shows the release). Dependabot updates them weekly, together with uv, pnpm, cargo, Docker and Compose dependencies, after a 7-day cooldown, into `develop`.
- Local composite actions (`.github/actions/setup-*`) use GitHub's self-repository syntax (`$/…`), so they are resolved from the same commit as the workflow.
- Release builds use no caches that pull request runs could have written.
- Jobs get the minimum `permissions:`; checkouts do not persist credentials; Codecov uploads use OIDC (no stored token).

## Maintainer setup (one time)

1. **Codecov:** sign in at codecov.io with GitHub and enable `engish-teacher-erdon` (installs the Codecov app). Uploads use OIDC, so no token is needed. Until then the upload step only warns.
2. **Private vulnerability reporting:** Settings → Code security → enable it (SECURITY.md links to it).
