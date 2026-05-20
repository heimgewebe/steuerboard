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
	trap 'rm -f $$tmp_files' EXIT INT TERM; \
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
	json_smoke "omnipull-report show mixed-run" $(CLI) omnipull-report show examples/omnipull-reports/mixed-run.json --json; \
	json_smoke "omnipull-report latest multiple-runs" $(CLI) omnipull-report latest examples/omnipull-run-indexes/multiple-runs.json --json; \
	json_smoke "plan git-pull-ff-only preview" $(CLI) plan git-pull-ff-only examples/assessments/pull-preflight-local-clear-evidence-missing.json --json; \
	echo "--- smoke: assess repo . -> assess explain -> plan switch-main ---"; \
	tmp_assessment="$$(mktemp)"; \
	tmp_explanation="$$(mktemp)"; \
	tmp_files="$$tmp_files $$tmp_assessment $$tmp_explanation"; \
	if ! $(CLI) assess repo . --json --config $(EXAMPLE_CONFIG) > "$$tmp_assessment"; then \
		echo "smoke failure: assess repo command failed" >&2; \
		exit 1; \
	fi; \
	if ! $(CLI) assess explain "$$tmp_assessment" --json > "$$tmp_explanation"; then \
		echo "smoke failure: assess explain command failed" >&2; \
		exit 1; \
	fi; \
	tmp_plan="$$(mktemp)"; \
	tmp_files="$$tmp_files $$tmp_plan"; \
	if ! $(CLI) plan switch-main "$$tmp_assessment" --json > "$$tmp_plan"; then \
		echo "smoke failure: plan switch-main command failed" >&2; \
		exit 1; \
	fi; \
	$(PYTHON) -m json.tool "$$tmp_assessment" > /dev/null; \
	$(PYTHON) -m json.tool "$$tmp_explanation" > /dev/null; \
	$(PYTHON) -m json.tool "$$tmp_plan" > /dev/null; \
	echo "smoke: all entrypoints exited 0 and emitted valid JSON"

deploy-check:
	@$(MAKE) validate
	@$(MAKE) test
	@$(MAKE) smoke
	@echo "deploy-check: passed"
