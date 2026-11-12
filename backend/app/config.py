import os
import secrets

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./nexeaglefin.db")

# Set SECRET_KEY in production. Without it a random key is made at startup,
# which is safe but logs everyone out on every restart.
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48)

TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", "12"))
