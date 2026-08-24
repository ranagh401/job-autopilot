from pathlib import Path

from dotenv import load_dotenv

# Load .env on package import so every entry point (server, scripts,
# scheduler) sees the credentials.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
