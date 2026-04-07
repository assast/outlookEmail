# Branch Protection & Release Recommendations

This document records the recommended repository governance settings for `outlookEmail`.

## Goal

Prevent accidental direct development on `main`, reduce noisy release/build activity, and make releases more predictable.

## Recommended Branch Roles

- `main`: stable release branch
- `dev`: default development branch

## Recommended GitHub Branch Protection

### Protect `main`

Recommended settings:

- Require a pull request before merging
- Require at least 1 approval (optional if solo-maintained, but recommended if collaborators join later)
- Dismiss stale approvals when new commits are pushed
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Restrict direct pushes to `main`
- Restrict force pushes
- Restrict branch deletion

### Suggested required checks for `main`

At minimum:

- `build-and-push`

If more CI checks are added later, include them here.

### Protect `dev`

Recommended lighter rules:

- Allow direct pushes if the repository is primarily solo-maintained
- Disallow force pushes unless explicitly needed
- Optionally require PRs for larger risky changes

## Suggested Daily Workflow

1. Develop on `dev`
2. Push incremental changes to `dev`
3. Verify app behavior / CI status
4. Merge `dev` into `main` only for releasable states
5. Update `VERSION` and `CHANGELOG.md`
6. Push a version tag such as `v1.0.1`

## Build Trigger Policy

To avoid excessive image publishing:

- Docker builds should trigger only for code/runtime/container-related changes
- Documentation-only changes should not trigger image rebuilds
- GitHub Release creation should happen only on `v*` tags

Current repository policy implemented in Actions:

- `docker-build-push.yml` triggers on:
  - Python source changes
  - `requirements.txt`
  - `Dockerfile`
  - `.dockerignore`
  - `templates/**`
  - workflow file changes
- It does **not** trigger for README / changelog / release-doc-only edits

## Release Policy

- `main` represents release-ready code
- Version tags (`vX.Y.Z`) represent formal releases
- GitHub Release notes should be sourced from `CHANGELOG.md`
- Avoid tagging if `VERSION`, `CHANGELOG.md`, and actual shipped code are out of sync

## Optional Future Enhancements

- Make `dev` the repository default branch for day-to-day development
- Add a test workflow and require it on `main`
- Add manual approval for production image publishing
- Split `latest` and `stable` image semantics if needed
