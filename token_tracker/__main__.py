import argparse
import getpass
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

from .core import CONFIG, PROVIDERS, fetch, keyring, load_accounts, positive, save_accounts


def main():
    parser = argparse.ArgumentParser(description="Multi-account AI usage overlay for Wayland")
    sub = parser.add_subparsers(dest="command")
    overlay = sub.add_parser("overlay", help="Show overlay; running again toggles visibility")
    overlay.add_argument("--demo", action="store_true", help="Display explicitly labelled sample data")
    overlay.add_argument("--quit-after", type=int, help=argparse.SUPPRESS)
    waybar = sub.add_parser("waybar", help="Stream JSON for a native Waybar hover tooltip")
    waybar.add_argument("--demo", action="store_true", help="Labelled sample data; no credentials")
    sub.add_parser("accounts", help="Manage verified ChatGPT connections in GTK")
    connect = sub.add_parser("connect", help="Link a ChatGPT subscription through browser sign-in")
    connect.add_argument("provider", choices=("chatgpt",))
    connect.add_argument("name")
    connect.add_argument("--email", help="Expected ChatGPT email (prompted when omitted)")
    connect.add_argument("--workspace", help="Expected workspace name or canonical ID")
    sub.add_parser("status", help="Print real account snapshots as JSON")
    sub.add_parser("list", help="List configured accounts, without secrets")
    add = sub.add_parser("add", help="Add an independent account connection")
    add.add_argument("provider", choices=[p for p in PROVIDERS if p != "chatgpt"])
    add.add_argument("name")
    add.add_argument("--budget", type=positive)
    add.add_argument("--project-id")
    add.add_argument("--codex-home", default="~/.codex")
    remove = sub.add_parser("remove", help="Remove a connection (stored key is retained)")
    remove.add_argument("id")
    key = sub.add_parser("set-key", help="Securely prompt for an OpenAI admin key")
    key.add_argument("id")
    args = parser.parse_args()
    try:
        if args.command == "waybar":
            from .waybar import run
            return run(args.demo)
        if args.command in (None, "overlay"):
            from .ui import run
            return run(getattr(args, "demo", False), getattr(args, "quit_after", None))
        if args.command == "accounts":
            from .accounts import run
            return run()
        if args.command == "connect":
            import webbrowser
            from .chatgpt import connect
            email = args.email or input("Expected ChatGPT email: ").strip()
            workspace = args.workspace or input("Expected workspace name/ID (blank to review selected ID): ").strip()
            def show_url(url):
                print("Open this URL to sign in (Ctrl+C cancels):\n" + url, flush=True)
                webbrowser.open(url)
            def confirm(pin):
                print("Verified: " + json.dumps(pin, ensure_ascii=False), flush=True)
                return input("Link this exact user and workspace? [y/N] ").strip().lower() == "y"
            account = connect(args.name, email, workspace, show_url, confirm)
            print("Connected verified ChatGPT account: " + account["id"])
            return 0
        accounts = load_accounts()
        if args.command == "add":
            account = {"id": uuid.uuid4().hex[:12], "provider": args.provider, "name": args.name}
            if args.budget is not None:
                account["budget"] = args.budget
            if args.project_id:
                account["project_id"] = args.project_id
            if args.provider == "codex-local":
                account["codex_home"] = args.codex_home
            accounts.append(account)
            save_accounts(accounts)
            print(f"Added {account['id']}. Config: {CONFIG}")
        elif args.command == "list":
            print(json.dumps(accounts, indent=2))
        elif args.command == "remove":
            if not any(a["id"] == args.id for a in accounts):
                raise ValueError("Unknown account id")
            if any(a["id"] == args.id and a["provider"] == "chatgpt" for a in accounts):
                from .chatgpt import disconnect
                disconnect(args.id)
                print("ChatGPT connection removed and managed credentials deleted.")
                return 0
            save_accounts([a for a in accounts if a["id"] != args.id])
            print("Connection removed. Remove any retained credential using your keyring manager.")
        elif args.command == "set-key":
            if not any(a["id"] == args.id and a["provider"] == "openai-api" for a in accounts):
                raise ValueError("Unknown OpenAI API account id")
            secret = getpass.getpass("OpenAI admin API key (stored in desktop keyring): ")
            if not secret.strip():
                raise ValueError("Key cannot be empty")
            keyring(args.id, secret)
            print("Key saved in desktop keyring.")
        elif args.command == "status":
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(fetch, accounts))
            print(json.dumps([result.to_dict() for result in results], indent=2))
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Sign-in cancelled.", file=sys.stderr)
        return 130
    except (ValueError, OSError, KeyError) as error:
        print(f"token-tracker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
