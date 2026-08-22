.PHONY: install run test

install:
	uv venv
	uv pip install -r requirements.txt

run:
	uv run python main.py

test:
	uv run pytest