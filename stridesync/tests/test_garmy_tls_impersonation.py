import garmy.auth.client as auth_client_module
import garmy.auth.sso as sso
from garmy import AuthClient

from app.sync import garmy_tls_impersonation


def _reset(monkeypatch):
    monkeypatch.setattr(garmy_tls_impersonation, "_applied", False)


def test_apply_patches_auth_http_client_session_to_curl_cffi(monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_TLS_IMPERSONATE", raising=False)
    _reset(monkeypatch)

    garmy_tls_impersonation.apply()

    auth_client = AuthClient(token_dir=str(tmp_path))
    session = auth_client.http_client.session

    from curl_cffi.requests.session import Session as CurlSession

    assert isinstance(session, CurlSession)


def test_apply_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_TLS_IMPERSONATE", "chrome124")
    _reset(monkeypatch)

    captured = {}

    garmy_tls_impersonation.apply()

    import curl_cffi.requests as curl_requests

    original_session_init = curl_requests.Session.__init__

    def _capture_impersonate(self, *args, **kwargs):
        captured["impersonate"] = kwargs.get("impersonate")
        return original_session_init(self, *args, **kwargs)

    monkeypatch.setattr(curl_requests.Session, "__init__", _capture_impersonate)

    AuthClient(token_dir=str(tmp_path))

    assert captured["impersonate"] == "chrome124"


def test_oauth1_session_tolerates_curl_cffi_parent_without_adapters(monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_TLS_IMPERSONATE", raising=False)
    _reset(monkeypatch)
    garmy_tls_impersonation.apply()

    auth_client = AuthClient(token_dir=str(tmp_path))
    parent_session = auth_client.http_client.session
    assert not hasattr(parent_session, "adapters")

    oauth1_session = sso.GarminOAuth1Session(parent=parent_session)

    assert isinstance(oauth1_session, sso.GarminOAuth1Session)


def test_oauth1_session_still_inherits_from_a_normal_requests_parent(monkeypatch):
    # Unpatched behavior must be preserved for a real requests.Session parent (e.g. if some
    # other code path still constructs one) — the original __init__ should run unmodified.
    _reset(monkeypatch)
    garmy_tls_impersonation.apply()

    import requests

    parent = requests.Session()
    oauth1_session = sso.GarminOAuth1Session(parent=parent)

    assert oauth1_session.proxies == parent.proxies
    assert oauth1_session.verify == parent.verify


def test_apply_is_idempotent(monkeypatch, tmp_path):
    _reset(monkeypatch)

    garmy_tls_impersonation.apply()
    patched_method = auth_client_module.AuthHttpClient._create_session

    garmy_tls_impersonation.apply()

    assert auth_client_module.AuthHttpClient._create_session is patched_method
