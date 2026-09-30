# What this does not show

Limits of each component of the national rebuild, updated as each one ships.
The Wisconsin/Minnesota baseline keeps its own list in `methodology.md`
("What this project does not show").

## Repo hygiene and tooling

- **The secret scan is not proof of absence.** `detect-secrets` is pattern and
  entropy based and runs on tracked files. A separate one-time regex check of git
  history (private-key, cloud-key and token patterns) found nothing on
  2026-09-30, but that was not a full-history scan by a dedicated tool.
- **Ignoring a file does not remove it from history.** `.claude/launch.json` is
  now untracked, but earlier commits still contain it. It holds no secret.
- **Lint and type checks cover only the national-rebuild code.** The frozen
  Wisconsin baseline (`src/*.py`, `app/`, existing tests) is not linted or
  formatted, so "lint clean" says nothing about it.
- **Pre-commit hooks are opt-in per clone** (`pre-commit install`). CI repeats the
  secret scan and lint on every push and pull request, and that is the backstop.
- **CI shows the code passes on a clean Linux runner, not that any dataset is
  correct.** Data validity is the job of each connector's validation gates.
