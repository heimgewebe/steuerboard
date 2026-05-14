PYTHON       ?= python3
EXAMPLE_CONFIG = examples/local-configs/heim-pc.json

.PHONY: validate test smoke deploy-check

validate:
	$(PYTHON) scripts/validate_examples.py

test:
	$(PYTHON) -m pytest

smoke:
	@echo "--- smoke: --help ---"
	$(PYTHON) -m steuerboard --help > /dev/null
	@echo "--- smoke: observe repo . ---"
	$(PYTHON) -m steuerboard observe repo . --json | $(PYTHON) -m json.tool > /dev/null
	@echo "--- smoke: scope explain . ---"
	$(PYTHON) -m steuerboard scope explain . --json --config $(EXAMPLE_CONFIG) | $(PYTHON) -m json.tool > /dev/null
	@echo "--- smoke: inventory ---"
	$(PYTHON) -m steuerboard inventory --json --config $(EXAMPLE_CONFIG) | $(PYTHON) -m json.tool > /dev/null
	@echo "--- smoke: inventory duplicates ---"
	$(PYTHON) -m steuerboard inventory duplicates --json --config $(EXAMPLE_CONFIG) | $(PYTHON) -m json.tool > /dev/null
	@echo "--- smoke: assess repo . ---"
	$(PYTHON) -m steuerboard assess repo . --json | $(PYTHON) -m json.tool > /dev/null
	@echo "smoke: all entrypoints exited 0 and emitted valid JSON"

deploy-check: validate test smoke
	@echo "deploy-check: passed"
