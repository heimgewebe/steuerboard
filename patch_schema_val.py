import re

with open("steuerboard/schema_validation.py", "r") as f:
    content = f.read()

# I need to change re.fullmatch back to re.search. Wait! It IS re.search!
# Look at line 116: if "pattern" in schema and re.search(schema["pattern"], instance) is None:
# Why did it fail with `re.search`? Ah! Let's read the error message.
