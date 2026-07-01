PYTHON ?= python3
CLI ?= steuerboard
EXAMPLE_CONFIG = examples/local-configs/heim-pc.json

.PHONY: validate test smoke deploy-check docs docs-check

validate:
	$(PYTHON) scripts/validate_examples.py
	$(PYTHON) scripts/validate_heimserver_service_gate_derivation_cases.py

docs:
	$(PYTHON) scripts/docmeta/generate_cli_surface.py --write

docs-check:
	$(PYTHON) scripts/docmeta/generate_cli_surface.py --check

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
	json_smoke "inventory favorites" $(CLI) inventory favorites --json --config $(EXAMPLE_CONFIG); \
	json_smoke "inventory branch-drift" $(CLI) inventory branch-drift --warning-threshold 5 --json --config $(EXAMPLE_CONFIG); \
	json_smoke "profile show" $(CLI) profile show --json --config $(EXAMPLE_CONFIG); \
	json_smoke "operator report" $(CLI) operator report --json --config $(EXAMPLE_CONFIG) --branch-warning-threshold 5 --omnipull-report examples/omnipull-reports/non-default-branch.json --recent-problem-limit 1; \
	json_smoke "omnipull-report show mixed-run" $(CLI) omnipull-report show examples/omnipull-reports/mixed-run.json --json; \
	json_smoke "omnipull-report latest multiple-runs" $(CLI) omnipull-report latest examples/omnipull-run-indexes/multiple-runs.json --json; \
	json_smoke "omnipull-report recent-problems" $(CLI) omnipull-report recent-problems examples/omnipull-reports/non-default-branch.json examples/omnipull-reports/dirty-worktree.json examples/omnipull-reports/mixed-run.json --limit 3 --json; \
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
	@$(MAKE) docs-check
	@$(MAKE) test
	@$(MAKE) smoke
	@echo "deploy-check: passed"
