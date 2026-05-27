.PHONY: setup

setup:
	git submodule update --init --recursive
	uv sync
	uv run pre-commit install
