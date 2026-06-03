import re

with open("tests/test_schema_examples.py", "r") as f:
    content = f.read()

# Wait... the error traceback says:
# E           steuerboard.schema_validation.SchemaValidationError: /app/examples/invalid-action-approval-scope-false.json.approval_scope.single_plan_only: expected const True, got False
# steuerboard/schema_validation.py:96: SchemaValidationError
#
# But `validate_instance` comes from `scripts/validate_examples.py`!
# Let me look at `scripts/validate_examples.py` definition of `validate_instance`.
