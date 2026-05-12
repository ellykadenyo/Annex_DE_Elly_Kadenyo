# ABC Phones - Credit Portfolio - convenience targets.
# Works on both Linux/macOS and Windows-with-make-installed.
PY ?= python

.PHONY: install profile clean features warehouse quality analysis run \
        test all distclean

install:
	$(PY) -m pip install -r requirements.txt

profile:
	$(PY) scripts/data_profiling.py

clean:
	$(PY) scripts/data_cleaning.py

features:
	$(PY) scripts/feature_engineering.py

warehouse:
	$(PY) scripts/build_warehouse.py --fresh

quality:
	$(PY) scripts/quality_checks.py

analysis:
	$(PY) scripts/analysis.py

test:
	$(PY) -m pytest tests -q

# Single-command full reproduction
run:
	$(PY) scripts/run_pipeline.py --warehouse-fresh

all: install run test

# Reset all generated artefacts (DOES NOT touch raw data)
distclean:
	rm -rf data/staging data/curated data/warehouse outputs logs
