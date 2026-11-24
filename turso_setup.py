"""Helper for the Turso setup.

    python turso_setup.py check        verify the settings and the connection
    python turso_setup.py group-token  create the TURSO_AUTH_TOKEN value

Secrets are never printed, except the one token you ask `group-token` to create.
"""

import sys

import config
import turso_admin
import turso_client


def _show(name, value, secret=False):
    shown = "(not set)" if not value else ("set (hidden)" if secret else value)
    print(f"  {name:<20} {shown}")


def check() -> int:
    print("Turso settings")
    _show("TURSO_DATABASE_URL", config.TURSO_DATABASE_URL)
    _show("TURSO_AUTH_TOKEN", config.TURSO_AUTH_TOKEN, secret=True)
    _show("TURSO_ORG", config.TURSO_ORG)
    _show("TURSO_API_TOKEN", config.TURSO_API_TOKEN, secret=True)
    _show("TURSO_GROUP", config.TURSO_GROUP)
    print()

    if not config.TURSO_ENABLED:
        print("Turso is OFF: the app is using local files (data are lost on hosts with a temporary disk).")
        print("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to turn it on.")
        return 1

    ok = True
    try:
        conn = turso_client.connect(config.TURSO_DATABASE_URL, config.TURSO_AUTH_TOKEN)
        conn.execute("SELECT 1").fetchone()
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        conn.close()
        print(f"[ok]   platform database reachable ({tables} tables)")
    except Exception as exc:
        ok = False
        print(f"[FAIL] platform database: {exc}")

    if config.TURSO_API_TOKEN and config.TURSO_ORG:
        try:
            names = turso_admin.list_databases()
            print(f"[ok]   API token works; organisation has {len(names)} database(s)")
        except Exception as exc:
            ok = False
            print(f"[FAIL] management API: {exc}")
    else:
        ok = False
        print("[WARN] TURSO_API_TOKEN / TURSO_ORG missing: approving a new university will fail,")
        print("       because each university gets its own Turso database.")

    print("\nEverything looks good." if ok else "\nFix the items above and run this again.")
    return 0 if ok else 1


def group_token() -> int:
    try:
        token = turso_admin.mint_group_token()
    except Exception as exc:
        print(f"Could not create the token: {exc}")
        print("Needs TURSO_API_TOKEN and TURSO_ORG (and TURSO_GROUP if not 'default').")
        return 1
    print("Put this value in TURSO_AUTH_TOKEN (Render > Environment, and your local .env).")
    print("Treat it like a password and do not share it or commit it to GitHub.\n")
    print(token)
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    sys.exit({"check": check, "group-token": group_token}.get(cmd, check)())
