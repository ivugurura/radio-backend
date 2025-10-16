# Makefile
.PHONY: run fmt fmt-check test

run:
	python manage.py runserver

fmt:
	python -m isort .
	python -m black .

fmt-check:
	python -m isort --check-only .
	python -m black --check .

test:
	pytest -q
