"""Write out the GitHub/Render secrets, ready to copy-paste.

Reads the local .env and lists exactly the names each host needs, so
nothing is missed or mistyped. The output file is gitignored.

    python prepare_secrets.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "secrets_for_github.txt"

# What the hosted pipeline actually reads.
NEEDED = [
    ("DATABASE_URL", "paste your Neon connection string here"),
    ("GMAIL_ADDRESS", None),
    ("GMAIL_APP_PASSWORD", None),
    ("AZURE_OPENAI_ENDPOINT", None),
    ("AZURE_OPENAI_API_KEY", None),
    ("AZURE_OPENAI_DEPLOYMENT", None),
    ("AZURE_OPENAI_API_VERSION", None),
    ("SERPER_API_KEY", None),
    ("HUNTER_API_KEY", None),
    ("ADZUNA_APP_ID", None),
    ("ADZUNA_APP_KEY", None),
    ("RAPIDAPI_KEY", None),
]
# Render also serves the UI, so it needs the login password too.
RENDER_EXTRA = [("DASHBOARD_PASSWORD", None)]


def read_env() -> dict:
    env = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def main() -> int:
    env = read_env()
    lines = [
        "GITHUB ACTIONS SECRETS",
        "  <repo> -> Settings -> Secrets and variables -> Actions",
        "         -> New repository secret",
        "",
        "This file contains live credentials. It is gitignored, so it will",
        "not be pushed. Delete it once the secrets are saved.",
        "",
        "=" * 62,
    ]
    missing = []
    for name, placeholder in NEEDED:
        value = env.get(name) or placeholder or ""
        if not value:
            missing.append(name)
            value = "(not set locally)"
        lines += [f"NAME:  {name}", f"VALUE: {value}", ""]

    lines += ["=" * 62, "",
              "RENDER also needs the above, plus:", ""]
    for name, _ in RENDER_EXTRA:
        lines += [f"NAME:  {name}", f"VALUE: {env.get(name, '')}", ""]

    if missing:
        lines += ["", "Not found in .env: " + ", ".join(missing)]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.name} with {len(NEEDED) + len(RENDER_EXTRA)} entries")
    if missing:
        print("missing locally:", ", ".join(missing))
    print("\nThis file holds live credentials - delete it after use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
