import re

with open("tests/test_schema_examples.py", "r") as f:
    content = f.read()

# I messed up `tests/test_schema_examples.py` by appending duplicate tests and an extra import at the top level?
# Ah! I did `cat test_schema_validation.py >> tests/test_schema_examples.py` early on. That had:
# import pytest
# from steuerboard.schema_validation import SchemaValidationError, validate_instance
#
# THIS global import shadows `validate_instance` from `scripts.validate_examples`!
# Wow!
# I need to clean up `tests/test_schema_examples.py`.
