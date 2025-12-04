.PHONY: help
help:
	@echo "Make targets for Nublado:"
	@echo "make init - Set up dev environment (install pre-commit hooks)"
	@echo "make update - Update dependencies and run make init"
	@echo "make update-deps - Update dependencies"

.PHONY: init
init:
	uv sync --frozen --all-groups
	uv run pre-commit install

.PHONY: update
update: update-deps init

.PHONY: update-deps
update-deps:
	uv lock --upgrade
	uv lock --upgrade --directory client
	uv lock --upgrade --directory hub
	uv run --only-group=lint pre-commit autoupdate
	./scripts/update-uv-version.sh
