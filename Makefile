.PHONY: help
help:
	@echo "Make targets for Nublado:"
	@echo "make init - Set up dev environment (install prek hooks)"
	@echo "make update - Update dependencies and run make init"
	@echo "make update-deps - Update dependencies"

.PHONY: init
init:
	uv sync --frozen --all-groups
	uv run prek install

.PHONY: update
update: update-deps init

.PHONY: update-deps
update-deps:
	uv lock --upgrade
	uv lock --upgrade --directory client
	uv lock --upgrade --directory hub
	uv run --only-group=lint prek autoupdate
	./scripts/update-uv-version.sh
