PYTHON ?= python3
CLI ?= steuerboard
EXAMPLE_CONFIG = examples/local-configs/heim-pc.json

.PHONY: validate test smoke deploy-check

validate:
	$(PYTHON) scripts/validate_examples.py

test:
	$(PYTHON) -m pytest

smoke:
	@set -eu; \
	tmp_files=""; \
	cleanup() { rm -f $$tmp_files; }; \
	trap cleanup EXIT INT TERM; \
	json_smoke() { \
		label="$$1"; shift; \
		echo "--- smoke: $$label ---"; \
		tmp="$$(mktemp)"; \
		tmp_files="$$tmp_files $$tmp"; \
		"$$@" > "$$tmp"; \
		$(PYTHON) -m json.tool "$$tmp" > /dev/null; \
	}; \
	echo "--- smoke: --help ---"; \
	$(CLI) --help > /dev/null; \
	json_smoke "observe repo ." $(CLI) observe repo . --json; \
	json_smoke "scope explain ." $(CLI) scope explain . --json --config $(EXAMPLE_CONFIG); \
	json_smoke "inventory" $(CLI) inventory --json --config $(EXAMPLE_CONFIG); \
	json_smoke "inventory duplicates" $(CLI) inventory duplicates --json --config $(EXAMPLE_CONFIG); \
	json_smoke "assess repo ." $(CLI) assess repo . --json --config $(EXAMPLE_CONFIG); \
	echo "smoke: all entrypoints exited 0 and emitted valid JSON"

deploy-check:
	@$(MAKE) validate
	@$(MAKE) test
	@$(MAKE) smoke
	@echo "deploy-check: passed"
