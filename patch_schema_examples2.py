import re

with open("tests/test_schema_examples.py", "r") as f:
    content = f.read()

test_addition = """
def test_runtime_schema_validation_rejects_exclusive_minimum_boundary():
    from steuerboard.schema_validation import SchemaValidationError, validate_instance
    with pytest.raises(SchemaValidationError):
        validate_instance(0, {"type": "number", "exclusiveMinimum": 0}, "$.timeout_seconds")

def test_runtime_schema_validation_allows_value_above_exclusive_minimum():
    from steuerboard.schema_validation import validate_instance
    validate_instance(0.1, {"type": "number", "exclusiveMinimum": 0}, "$.timeout_seconds")

def test_runtime_schema_validation_rejects_exclusive_maximum_boundary():
    from steuerboard.schema_validation import SchemaValidationError, validate_instance
    with pytest.raises(SchemaValidationError):
        validate_instance(30, {"type": "number", "exclusiveMaximum": 30}, "$.timeout_seconds")
"""

with open("tests/test_schema_examples.py", "w") as f:
    f.write(content + "\n" + test_addition)
