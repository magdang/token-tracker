"""Configuration and provider adapters. No GUI dependency or credential logging."""

import json
import math
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "token-tracker/accounts.json"
PROVIDERS = ("openai-api", "codex-local", "manual")


@dataclass
class Metric:
    label: str
    used: float
    limit: float = 100
    unit: str = "%"
    resets_at: str | None = None


@dataclass
class Snapshot:
    account_id: str
    source: str
    updated_at: str | None = None
    metrics: list[Metric] = field(default_factory=list)
    note: str = ""
    error: str | None = None

    def to_dict(self):
        return asdict(self)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Budget and limits must be finite positive numbers") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Budget and limits must be finite positive numbers")
    return number


def validate(accounts):
    if not isinstance(accounts, list):
        raise ValueError("accounts must be a list")
    seen = set()
    for account in accounts:
        if not isinstance(account, dict):
            raise ValueError("Each account must be an object")
        identity = account.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError("Every account needs a unique, nonempty id")
        seen.add(identity)
        if account.get("provider") not in PROVIDERS:
            raise ValueError(f"Unsupported provider for {identity}")
        if not isinstance(account.get("name"), str) or not account["name"].strip():
            raise ValueError("Every account needs a name")
        if "budget" in account:
            positive(account["budget"])
        metrics = account.get("metrics", [])
        if not isinstance(metrics, list):
            raise ValueError("metrics must be a list")
        for metric in metrics:
            if not isinstance(metric, dict) or "used" not in metric or "label" not in metric:
                raise ValueError("Each metric needs a label and usage")
            if not isinstance(metric["label"], str) or not isinstance(metric.get("unit", "%"), str):
                raise ValueError("Metric labels and units must be text")
            if any(not isinstance(metric.get(field, default), (int, float))
                   for field, default in (("used", 0), ("limit", 100))):
                raise ValueError("Metric usage and limits must be numbers")
            positive(metric.get("limit", 100))
            try:
                used = float(metric["used"])
            except (TypeError, ValueError):
                raise ValueError("Usage must be a finite nonnegative number") from None
            if not math.isfinite(used) or used < 0:
                raise ValueError("Usage must be a finite nonnegative number")
    return accounts


def load_accounts(path=CONFIG):
    if not path.exists():
        return []
    config = json.loads(path.read_text())
    if not isinstance(config, dict) or "accounts" not in config:
        raise ValueError("Configuration needs an accounts list")
    return validate(config["accounts"])


def save_accounts(accounts, path=CONFIG):
    validate(accounts)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".accounts-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"accounts": accounts}, stream, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def keyring(account_id, secret=None):
    args = ["secret-tool"]
    if secret is None:
        args += ["lookup", "application", "token-tracker", "account", account_id]
    else:
        args += ["store", "--label=Token Tracker", "application", "token-tracker", "account", account_id]
    result = subprocess.run(
        args, input=secret, text=True, capture_output=True, timeout=30, check=False
    )
    if result.returncode or (secret is None and not result.stdout.strip()):
        raise ValueError("Keyring unavailable or no key stored; run set-key for this account")
    return result.stdout.strip() if secret is None else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward privileged authorization headers to a redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_cost_page(params, key):
    request = urllib.request.Request(
        "https://api.openai.com/v1/organization/costs?" + urllib.parse.urlencode(params, doseq=True),
        headers={"Authorization": f"Bearer {key}", "User-Agent": "token-tracker/0.1"},
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        return json.load(response)


def openai_costs(account, key=None):
    key = key if key is not None else keyring(account["id"])
    now = datetime.now(timezone.utc)
    params = {
        "start_time": int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()),
        "end_time": int(now.timestamp()),
        "limit": 31,
    }
    if account.get("project_id"):
        params["project_ids"] = [account["project_id"]]
    spent = Decimal(0)
    pages = set()
    for _ in range(100):
        page = get_cost_page(params, key)
        for bucket in page["data"]:
            for result in bucket["results"]:
                amount = result.get("amount") or {}
                if amount.get("currency", "usd") != "usd":
                    raise ValueError("Non-USD billing is not supported yet")
                value = Decimal(str(amount.get("value", 0)))
                if not value.is_finite():
                    raise ValueError("Invalid cost returned by provider")
                spent += value
        if not page.get("has_more"):
            break
        cursor = page.get("next_page")
        if not cursor or cursor in pages:
            raise ValueError("Invalid pagination from provider")
        pages.add(cursor)
        params["page"] = cursor
    else:
        raise ValueError("Cost report exceeded pagination limit")
    return Snapshot(
        account["id"], "reported", timestamp(),
        [Metric("Month to date (UTC)", float(spent), float(account.get("budget", 0)), "USD")],
        "Provider reporting can lag. Budget is your target, not a credit balance. Organization/project totals may overlap other connections.",
    )


def codex_local(account):
    """Read only quota events, never credentials. A home must belong to one account."""
    home = Path(account.get("codex_home", "~/.codex")).expanduser()
    candidates = sorted(
        (home / "sessions").rglob("*.jsonl"),
        key=lambda path: path.stat().st_mtime, reverse=True,
    )[:30]
    latest = None
    for path in candidates:
        with path.open("rb") as stream:
            # Bound reads; discard the partial first record when tailing.
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 2_000_000))
            if size > 2_000_000:
                stream.readline()
            for line in stream:
                if b'"rate_limits"' not in line:
                    continue
                try:
                    event = json.loads(line)
                    payload = event.get("payload", {})
                    limits = payload.get("rate_limits")
                    observed = event.get("timestamp")
                    if payload.get("type") != "token_count" or not limits or not observed:
                        continue
                    when = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        continue
                    if latest is None or when > latest[0]:
                        latest = (when, limits)
                except (ValueError, TypeError, AttributeError):
                    continue
    if latest is None:
        return Snapshot(account["id"], "unavailable", note="No Codex quota snapshot found. Use Codex CLI, then refresh.")
    metrics = []
    for name in ("primary", "secondary"):
        window = latest[1].get(name)
        if not window:
            continue
        minutes = window.get("window_minutes")
        label = f"{minutes / 60:g}h window" if minutes else name.title()
        reset = window.get("resets_at")
        metrics.append(Metric(
            label, float(window["used_percent"]),
            resets_at=datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else None,
        ))
    return Snapshot(
        account["id"], "local snapshot", latest[0].isoformat(), metrics,
        "Last observed by Codex, not a live query. Use a separate CODEX_HOME per account; shared homes cannot be attributed reliably.",
    )


def fetch(account, api_key=None):
    try:
        if account["provider"] == "openai-api":
            return openai_costs(account, api_key)
        if account["provider"] == "codex-local":
            return codex_local(account)
        return Snapshot(
            account["id"], "manual", account.get("updated_at"),
            [Metric(**metric) for metric in account.get("metrics", [])],
            "Manually entered; not linked to the provider." if account.get("metrics") else
            "Automatic subscription integration not available yet.",
        )
    except urllib.error.HTTPError as error:
        return Snapshot(account["id"], "unavailable", error=f"Provider HTTP {error.code}; check key permissions or retry later.")
    except Exception as error:
        # Never surface remote bodies or exception strings that could contain secrets.
        message = str(error) if isinstance(error, ValueError) else f"Unable to refresh ({type(error).__name__})"
        return Snapshot(account["id"], "unavailable", error=message)
