# Repository Guidelines

## Project Structure & Module Organization
`main.py` contains the current entry point. Project metadata lives in `pyproject.toml`. The `data/` directory stores supporting assets such as `data/boil_prompt.md`. There is no dedicated `src/` or `tests/` directory yet; add them if the project grows and keep new modules grouped by feature.

## Build, Test, and Development Commands
- `uv run python main.py` runs the current CLI entry point.
- `uv pip install -e .` installs the project in editable mode for local development (no dependencies are declared yet).
There are no build or test commands configured; add them to `pyproject.toml` as the project evolves.

## Coding Style & Naming Conventions
Use standard Python style (PEP 8) with 4-space indentation. Prefer `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Keep modules small and focused; if you add a package, group related logic under a top-level directory (for example, `src/boiltheplaylist/`).

## Testing Guidelines
No testing framework is configured yet. If you introduce tests, create a `tests/` directory and document the runner (for example, `uv run python -m unittest` or `uv run pytest`) in this file and `pyproject.toml`. Name test files with a clear pattern like `test_*.py`.

## Commit & Pull Request Guidelines
The Git history only contains an initial commit, so no convention is established. Use short, imperative commit messages (for example, “Add playlist parser”). For pull requests, include a concise summary, steps to verify, and any new data files or scripts added.

## Configuration & Data Tips
Keep prompts, fixtures, or other static inputs in `data/` and reference them by path from code. If new runtime configuration is needed, prefer environment variables and document them here.
