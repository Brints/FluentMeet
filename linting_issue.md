# Issue: Enforce Linting, Type-Checking, and Code Style

## Problem
The project currently uses `black` and `isort` for formatting, but lacks a comprehensive linter and consistent type-checking. This can lead to subtle bugs, inconsistent coding patterns, and poor maintainability as the codebase grows. There is no automated enforcement of these standards outside of the newly planned CI workflow.

## Proposed Solution
Standardize the project's code style by adopting a modern linter (e.g., `ruff`) and fully configuring `mypy` for static type analysis. Update `pyproject.toml` to serve as the single source of truth for all linting and formatting configurations.

## User Stories
- As a developer, I want clear feedback on code quality and style violations as I write code.
- As a reviewer, I want to spend less time on stylistic comments and more time on logic and architecture.

## Acceptance Criteria
- [ ] `ruff` is added as a development dependency and configured in `pyproject.toml`.
- [ ] `mypy` is added as a development dependency and configured in `pyproject.toml`.
- [ ] Existing code is updated to pass all linting and type-checking rules.
- [ ] A `make lint` or similar command is available for local verification.
- [ ] Documentation is updated to include the coding standards and how to run the tools.

## Proposed Technical Details
- Use `ruff` to replace multiple tools (flake8, autoflake, etc.) for performance and simplicity.
- Configure `ruff` rules to be strict but pragmatic (e.g., following the `B`, `E`, `F`, and `I` rule sets).
- Set up `mypy` with `strict = true` or a similar high-standard configuration to ensure type safety.
- Update `pyproject.toml` sections for `[tool.ruff]` and `[tool.mypy]`.

## Tasks
- [ ] Add `ruff` and `mypy` to `requirements.txt` (or a new `requirements-dev.txt`).
- [ ] Configure `ruff` in `pyproject.toml`.
- [ ] Configure `mypy` in `pyproject.toml`.
- [ ] Run `ruff check . --fix` to address auto-fixable issues.
- [ ] Manually fix remaining linting violations.
- [ ] Fix type-checking errors reported by `mypy`.
- [ ] Update `README.md` with instructions for running linting tools.
