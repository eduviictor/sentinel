.PHONY: install lint check test

install:
	uv sync
	@if [ "$$(git rev-parse --git-dir)" = "$$(git rev-parse --git-common-dir)" ]; then \
		uv run pre-commit install; \
	elif [ -f "$$(git rev-parse --git-common-dir)/hooks/pre-commit" ]; then \
		echo "worktree: the pre-commit hook is shared with the main checkout, not reinstalled"; \
	else \
		echo "worktree: no pre-commit hook yet, run make install in the main checkout" >&2; \
		exit 1; \
	fi

lint:
	uv run ruff check --fix
	uv run ruff format

check:
	uv run ruff check
	uv run ruff format --check
	$(MAKE) test

test:
	uv run pytest -q
