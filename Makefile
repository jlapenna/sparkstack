.PHONY: setup

setup:
	uv sync
	uv run pre-commit install
