import os

# Tests use a fixed college so they don't depend on what is in your .env.
os.environ["COLLEGE_NAME"] = "Ravenmoor College"
os.environ["COLLEGE_DOMAIN"] = "ravenmoor.edu"
