"""Gmail tools via the official Google API client.

One-time setup (done by the user, once):
  1. Google Cloud Console (console.cloud.google.com) -> create a project.
  2. "APIs & Services" -> enable the **Gmail API**.
  3. "OAuth consent screen" -> External, add yourself as a test user.
  4. "Credentials" -> Create Credentials -> OAuth client ID -> **Desktop app**
     -> download the JSON file.
  5. Point ``GMAIL_CLIENT_SECRETS`` at that file in your ``.env``
     (or drop it at ``data/gmail_client_secrets.json``).
  6. Click **Connect Gmail** in the app topbar: your browser opens for
     consent, and the token is saved to ``data/gmail_token.json``
     (git-ignored, never committed).

Scopes requested: ``gmail.readonly`` and ``gmail.send`` — the app can read
and send mail, nothing else. Revoke anytime at
https://myaccount.google.com/permissions.

``gmail_send`` is a *gated* tool: the first call raises
:class:`~agentic_workspace.tools.NeedsConfirmation` with the full draft so
the UI can show it to the user. Only after explicit approval does the mail
actually send. Nothing is ever sent silently.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _data_dir() -> Path:
    here = Path(__file__).resolve()
    repo_root = here.parents[3] if len(here.parents) > 3 else Path.cwd()
    d = repo_root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_path() -> Path:
    return _data_dir() / "gmail_token.json"


def client_secrets_path(config_path: str | None = None) -> Path | None:
    """Where the OAuth client JSON lives: .env override or data/ default."""
    if config_path:
        p = Path(config_path).expanduser()
        if p.exists():
            return p
    default = _data_dir() / "gmail_client_secrets.json"
    return default if default.exists() else None


def is_connected() -> bool:
    return token_path().exists()


def connect_interactive(client_secrets: Path) -> str:
    """Run the OAuth consent flow in the system browser (blocking).

    Called from a worker thread by the "Connect Gmail" button. Returns a
    friendly status string.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return (
            "Gmail needs two packages: "
            "`pip install google-api-python-client google-auth-oauthlib`"
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secrets), SCOPES
        )
        creds = flow.run_local_server(port=0, open_browser=True)
    except Exception as exc:
        return f"Gmail sign-in didn't complete: {exc}"
    token_path().write_text(creds.to_json(), encoding="utf-8")
    return "Gmail connected."


def _service(config_client_secrets: str | None = None):
    """Build the Gmail API service, or return an error string."""
    if not is_connected():
        return None, (
            "Gmail is not connected. Click **Connect Gmail** in the topbar "
            "to sign in first."
        )
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None, (
            "Gmail needs two packages: "
            "`pip install google-api-python-client google-auth-oauthlib`"
        )
    try:
        creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path().write_text(creds.to_json(), encoding="utf-8")
        service = build("gmail", "v1", credentials=creds)
        return service, ""
    except Exception as exc:
        return None, f"Gmail auth failed ({exc}). Try Connect Gmail again."


def _headers(payload: dict, names: tuple[str, ...]) -> dict:
    out = {}
    for h in payload.get("payload", {}).get("headers", []):
        if h.get("name") in names:
            out[h["name"]] = h.get("value", "")
    return out


def gmail_search(query: str, max_results: int = 8, _client_secrets: str | None = None) -> str:
    """Search Gmail. Returns subject/from/date/snippet per message."""
    service, err = _service(_client_secrets)
    if service is None:
        return err
    try:
        listing = (
            service.users()
            .messages()
            .list(userId="me", q=query or "", maxResults=max(1, max_results))
            .execute()
        )
    except Exception as exc:
        return f"Gmail search failed: {exc}"
    messages = listing.get("messages", [])
    if not messages:
        return f"No Gmail messages match '{query}'."
    lines = []
    for m in messages:
        try:
            full = (
                service.users()
                .messages()
                .get(userId="me", id=m["id"], format="metadata",
                     metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            h = _headers(full, ("Subject", "From", "Date"))
            lines.append(
                f"[{m['id']}] {h.get('Subject', '(no subject)')}\n"
                f"   From: {h.get('From', '?')} · {h.get('Date', '')}\n"
                f"   {full.get('snippet', '')}"
            )
        except Exception:
            lines.append(f"[{m['id']}] (couldn't fetch details)")
    return "\n".join(lines)


def _decode_body(payload: dict) -> str:
    """Walk MIME parts for the first text/plain body."""
    def walk(part: dict) -> str:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime.startswith("text/plain") and data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""
        for sub in part.get("parts", []) or []:
            text = walk(sub)
            if text:
                return text
        return ""

    return walk(payload.get("payload", {}))


def gmail_read(message_id: str, _client_secrets: str | None = None) -> str:
    """Read one Gmail message by id (from gmail_search)."""
    service, err = _service(_client_secrets)
    if service is None:
        return err
    try:
        full = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except Exception as exc:
        return f"Couldn't read message {message_id}: {exc}"
    h = _headers(full, ("Subject", "From", "Date"))
    body = _decode_body(full)[:8000]
    return (
        f"Subject: {h.get('Subject', '(no subject)')}\n"
        f"From: {h.get('From', '?')}\n"
        f"Date: {h.get('Date', '')}\n\n{body or '(no readable text body)'}"
    )


def gmail_send(
    to: str,
    subject: str,
    body: str,
    _confirmed: bool = False,
    _client_secrets: str | None = None,
) -> str:
    """Send an email. GATED: first call raises NeedsConfirmation with the draft."""
    from . import NeedsConfirmation

    to, subject, body = (to or "").strip(), (subject or "").strip(), (body or "").strip()
    if not to or not body:
        return "Not sent: 'to' and 'body' are both required."
    if not _confirmed:
        raise NeedsConfirmation(
            "gmail_send",
            {"to": to, "subject": subject or "(no subject)", "body": body},
        )
    service, err = _service(_client_secrets)
    if service is None:
        return err
    try:
        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject or "(no subject)"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
    except Exception as exc:
        return f"Gmail send failed: {exc}"
    return f"Sent email to {to}."
