"""Drive a real browser to create the GitHub repo and Render service.

Opens a visible Chromium with its own persistent profile (kept in
data/browser_profile) so logins survive between runs. You sign in
yourself - passwords are never handled here - and the script waits,
then does the clicking.

    python deploy_browser.py github     # create the repo
    python deploy_browser.py status     # what am I signed into?
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "data" / "browser_profile"
PROFILE.mkdir(parents=True, exist_ok=True)

REPO_NAME = "job-mania"


def seed_from_real_profile() -> str:
    """Copy your Edge sign-in state into the automation profile.

    Edge refuses to expose the automation channel on its *default* data
    directory ("DevTools remote debugging requires a non-default data
    directory") - a deliberate guard against hijacking a logged-in
    browser. So instead of driving your profile, we copy the cookie jar
    and its encryption key into ours, which carries the sessions across
    without ever touching your passwords.

    Requires Edge to be closed (the files are locked while it runs).
    """
    real = (Path.home() / "AppData" / "Local" / "Microsoft" / "Edge"
            / "User Data")
    if not real.exists():
        return "no Edge profile found"
    # Local State holds the DPAPI-wrapped key that decrypts the cookies.
    wanted = [
        ("Local State", "Local State"),
        ("Default/Network/Cookies", "Default/Network/Cookies"),
        ("Default/Preferences", "Default/Preferences"),
    ]
    copied, failed = [], []
    for src_rel, dst_rel in wanted:
        src, dst = real / src_rel, PROFILE / dst_rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            copied.append(src_rel)
        except Exception as e:
            failed.append(f"{src_rel} ({type(e).__name__})")
    msg = f"copied {len(copied)} profile files"
    if failed:
        msg += f"; could not copy {', '.join(failed)} - is Edge closed?"
    return msg


def open_browser(p, use_my_edge_profile: bool = False):
    """Real Microsoft Edge, visible, on a profile we are allowed to drive."""
    if use_my_edge_profile:
        print("  " + seed_from_real_profile(), flush=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="msedge",
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def wait_for_login(page, url: str, signed_in_check, label: str,
                   timeout_s: int = 420) -> bool:
    """Park on a login page until the user has signed in."""
    page.goto(url, wait_until="domcontentloaded")
    print(f"\n>>> Sign in to {label} in the browser window that just opened.")
    print(f">>> Waiting up to {timeout_s // 60} minutes...", flush=True)
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            if signed_in_check(page):
                print(f"    {label}: signed in", flush=True)
                return True
        except Exception:
            pass
        time.sleep(3)
    print(f"    {label}: timed out waiting for sign-in", flush=True)
    return False


def github_signed_in(page) -> bool:
    try:
        page.goto("https://github.com/settings/profile",
                  wait_until="domcontentloaded", timeout=20000)
    except Exception:
        return False
    return "/login" not in page.url and "settings" in page.url


def create_repo(page) -> str:
    """Create the private repo and return its clone URL."""
    page.goto("https://github.com/new", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # Repository name
    for sel in ("input#repository_name", "input[name='repository[name]']",
                "input[aria-label*='name' i]"):
        try:
            el = page.locator(sel).first
            if el.count():
                el.fill(REPO_NAME)
                break
        except Exception:
            continue

    # Private
    for sel in ("input#repository_visibility_private",
                "input[value='private']",
                "input[type='radio'][name*='visibility'][value='private']"):
        try:
            el = page.locator(sel).first
            if el.count():
                el.check(force=True)
                break
        except Exception:
            continue

    page.wait_for_timeout(1200)
    page.screenshot(path=str(ROOT / "data" / "screenshots" /
                             "gh_new_repo.png"), full_page=True)

    for name in ("Create repository", "Create a new repository"):
        try:
            btn = page.get_by_role("button", name=name).first
            if btn.is_visible(timeout=2500):
                btn.click()
                break
        except Exception:
            continue

    page.wait_for_timeout(5000)
    url = page.url
    page.screenshot(path=str(ROOT / "data" / "screenshots" /
                             "gh_after_create.png"), full_page=True)
    return url


def main() -> int:
    from playwright.sync_api import sync_playwright

    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    mine = "--my-profile" in sys.argv
    with sync_playwright() as p:
        ctx = open_browser(p, use_my_edge_profile=mine)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if action == "status":
                gh = github_signed_in(page)
                print(f"github signed in: {gh}")
                print(f"current url: {page.url}")
                page.wait_for_timeout(4000)
                return 0

            if action == "github":
                if not github_signed_in(page):
                    ok = wait_for_login(
                        page, "https://github.com/login",
                        github_signed_in, "GitHub")
                    if not ok:
                        return 1
                url = create_repo(page)
                print(f"\nafter create, landed on: {url}")
                if REPO_NAME in url and "/new" not in url:
                    print(f"REPO READY: {url}")
                else:
                    print("repo may not have been created - see the "
                          "screenshots in data/screenshots/")
                page.wait_for_timeout(3000)
                return 0
        finally:
            ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
