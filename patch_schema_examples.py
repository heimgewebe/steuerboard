import re

with open("tests/test_schema_examples.py", "r") as f:
    content = f.read()

# Let's remove everything after line 600 or so. Let's see what is at the end of the original file.
