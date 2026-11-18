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
    sub.add_parser("status", help="Print real account snapshots as JSON")
    sub.add_parser("list", help="List configured accounts, without secrets")
    add = sub.add_parser("add", help="Add an independent account connection")
    add.add_argument("provider", choices=PROVIDERS)
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
        if args.command in (None, "overlay"):
            from .ui import run
            return run(getattr(args, "demo", False), getattr(args, "quit_after", None))
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
    except (ValueError, OSError, KeyError) as error:
        print(f"token-tracker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
