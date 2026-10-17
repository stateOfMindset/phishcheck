import os

# Tests use a fixed college so they don't depend on what is in your .env.
os.environ["COLLEGE_NAME"] = "Ravenmoor College"
os.environ["COLLEGE_DOMAIN"] = "ravenmoor.edu"

# The tests never connect to the database, but server.config requires these settings to exist.
# Defaults let `pytest` run on a fresh clone before .env has been created.
for name, value in {"POSTGRES_USER": "test", "POSTGRES_PASSWORD": "test",
                    "POSTGRES_DB": "test"}.items():
    os.environ.setdefault(name, value)
