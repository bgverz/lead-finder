.PHONY: setup doctor smoke-test test run

setup:
	sh scripts/setup.sh

doctor:
	python -m lead_pipeline doctor

smoke-test:
	python -m lead_pipeline smoke-test

test:
	pytest -q

run:
	python -m lead_pipeline run --mode mock
