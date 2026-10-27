import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests

CLIENT_ID = "zugup-local"
AUTHORIZE_URL = "https://lichess.org/oauth"
TOKEN_URL = "https://lichess.org/api/token"
ACCOUNT_URL = "https://lichess.org/api/account"
TIMEOUT = 20


class LichessAuthError(Exception):
    pass


def new_challenge():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge, secrets.token_urlsafe(24)


def authorize_url(redirect_uri, state, challenge):
    query = urlencode({
        "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect_uri,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state,
    })
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(code, verifier, redirect_uri):
    try:
        response = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "redirect_uri": redirect_uri, "client_id": CLIENT_ID,
        }, timeout=TIMEOUT)
        token = response.json().get("access_token") if response.ok else None
    except (requests.RequestException, ValueError):
        token = None
    if not token:
        raise LichessAuthError("Lichess refused the authorization code")
    return token


def fetch_username(token):
    try:
        response = requests.get(ACCOUNT_URL, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        username = response.json().get("username") if response.ok else None
    except (requests.RequestException, ValueError):
        username = None
    if not username:
        raise LichessAuthError("Could not read the Lichess account")
    return username


def revoke(token):
    try:
        requests.delete(TOKEN_URL, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    except requests.RequestException:
        return False
    return True
