"""scripts/check_youtube.py: reports whether the YouTube sign-in works, never printing secrets."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_youtube", ROOT / "scripts" / "check_youtube.py")
cy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cy)
REFRESH = "1//refresh-secret"


class R:
    def __init__(self, code, body):
        self.status_code, self._b, self.headers = code, body, {"content-type": "application/json"}

    def json(self):
        return self._b


def _keys(monkeypatch):
    class S:
        youtube_client_id, youtube_client_secret, youtube_refresh_token = "cid", "GOCSPX-secret", REFRESH
    monkeypatch.setattr(cy, "secrets", lambda: S())


def test_working_connection(monkeypatch, capsys):
    _keys(monkeypatch)
    monkeypatch.setattr(cy.httpx, "post", lambda url, data, timeout: R(200, {"access_token": "ya29.x"}))
    monkeypatch.setattr(cy.httpx, "get", lambda url, params, headers, timeout:
                        R(200, {"items": [{"snippet": {"title": "Why In Clay"}}]}))
    assert cy.main() == 0
    out = capsys.readouterr().out
    assert "Why In Clay" in out and REFRESH not in out and "GOCSPX" not in out


def test_expired_sign_in(monkeypatch, capsys):
    _keys(monkeypatch)
    monkeypatch.setattr(cy.httpx, "post", lambda url, data, timeout: R(400, {"error": "invalid_grant"}))
    assert cy.main() == 1
    out = capsys.readouterr().out
    assert "does NOT work" in out and "expired" in out and "youtube_auth.py" in out and REFRESH not in out
