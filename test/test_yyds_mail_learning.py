import pytest

from services.register import domain_reputation, mail_provider, openai_register


def test_mail_api_429_cools_down_then_retries(monkeypatch):
    calls = []
    sleeps = []
    now = [100.0]

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class FakeSession:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(429 if len(calls) == 1 else 200)

    monkeypatch.setattr(mail_provider, "mail_api_cooldown_until", 0.0)
    monkeypatch.setattr(mail_provider.time, "monotonic", lambda: now[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(mail_provider.time, "sleep", fake_sleep)

    response = mail_provider._mail_api_request(FakeSession(), "get", "https://mail.example.test/api", timeout=1)

    assert response.status_code == 200
    assert sleeps == [30]
    assert [call[0] for call in calls] == ["GET", "GET"]
    assert calls[0][1:] == calls[1][1:]


def test_yyds_non_learning_filters_disabled_domains(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)
    store.record_failure("yyds_mail", "bad.test", "The email you provided is not supported")

    provider = mail_provider.YydsMailProvider(
        {"provider_ref": "yyds_mail#1", "api_key": "token", "domain": ["bad.test"], "learning_mode": False},
        {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 1, "user_agent": "pytest", "proxy": ""},
    )
    provider._request = lambda *args, **kwargs: {"items": []}
    try:
        with pytest.raises(mail_provider.LocalDomainFilteredError):
            provider.create_mailbox()
    finally:
        provider.close()


def test_yyds_learning_prefers_successful_domains(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)
    store.record_success("yyds_mail", "good.test")

    provider = mail_provider.YydsMailProvider(
        {
            "provider_ref": "yyds_mail#1",
            "api_key": "token",
            "domain": ["bad.test", "good.test"],
            "learning_mode": True,
            "domain_explore_rate": 0,
        },
        {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 1, "user_agent": "pytest", "proxy": ""},
    )
    payloads = []

    def fake_request(method, path, token="", params=None, payload=None, expected=(200, 201, 204)):
        if path == "/domains":
            return {"items": []}
        payloads.append(dict(payload or {}))
        return {"address": "user@good.test", "token": "mail-token"}

    provider._request = fake_request
    try:
        mailbox = provider.create_mailbox("user")
    finally:
        provider.close()

    assert payloads[0]["domain"] == "good.test"
    assert mailbox["domain"] == "good.test"


def test_yyds_uses_available_domains_from_api(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)

    provider = mail_provider.YydsMailProvider(
        {"provider_ref": "yyds_mail#1", "api_key": "token", "domain": [], "learning_mode": False},
        {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 1, "user_agent": "pytest", "proxy": ""},
    )
    requests = []

    def fake_request(method, path, token="", params=None, payload=None, expected=(200, 201, 204)):
        requests.append((method, path, dict(payload or {})))
        if path == "/domains":
            return {
                "items": [
                    {"domain": "https://disabled.test/path", "available": False},
                    {"domain": "fresh.test", "available": True},
                    {"name": "user@fresh.test", "enabled": True},
                ]
            }
        return {"address": f"user@{payload['domain']}", "token": "mail-token"}

    provider._request = fake_request
    try:
        mailbox = provider.create_mailbox("user")
    finally:
        provider.close()

    assert requests[0][:2] == ("GET", "/domains")
    assert requests[1] == ("POST", "/accounts", {"localPart": "user", "domain": "fresh.test"})
    assert mailbox["domain"] == "fresh.test"


def test_yyds_api_domains_take_priority_over_configured_domains(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)
    store.record_success("yyds_mail", "configured.test")

    provider = mail_provider.YydsMailProvider(
        {
            "provider_ref": "yyds_mail#1",
            "api_key": "token",
            "domain": ["configured.test"],
            "learning_mode": True,
            "domain_explore_rate": 0,
        },
        {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 1, "user_agent": "pytest", "proxy": ""},
    )
    payloads = []

    def fake_request(method, path, token="", params=None, payload=None, expected=(200, 201, 204)):
        if path == "/domains":
            return {"items": [{"domain": "api.test", "available": True}]}
        payloads.append(dict(payload or {}))
        return {"address": f"user@{payload['domain']}", "token": "mail-token"}

    provider._request = fake_request
    try:
        mailbox = provider.create_mailbox("user")
    finally:
        provider.close()

    assert payloads == [{"localPart": "user", "domain": "api.test"}]
    assert mailbox["domain"] == "api.test"


def test_yyds_falls_back_to_auto_domain_strategy_when_domain_api_empty(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)

    provider = mail_provider.YydsMailProvider(
        {"provider_ref": "yyds_mail#1", "api_key": "token", "domain": [], "learning_mode": False},
        {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 1, "user_agent": "pytest", "proxy": ""},
    )
    payloads = []

    def fake_request(method, path, token="", params=None, payload=None, expected=(200, 201, 204)):
        if path == "/domains":
            return {"items": []}
        payloads.append(dict(payload or {}))
        return {"address": "user@auto.test", "token": "mail-token"}

    provider._request = fake_request
    try:
        mailbox = provider.create_mailbox("user")
    finally:
        provider.close()

    assert payloads == [{"localPart": "user", "autoDomainStrategy": "balanced"}]
    assert mailbox["domain"] == "auto.test"


def test_register_records_yyds_domain_reputation(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)

    openai_register._record_mail_success({"mail_provider": "yyds_mail", "mail_domain": "ok.test"})
    assert store.good_domains("yyds_mail") == ["ok.test"]

    failure = openai_register.RegisterAttemptError(
        "Failed to create account. Please try again.",
        {"provider": "yyds_mail", "address": "user@bad.test"},
    )
    result = openai_register._record_mail_failure(failure)
    assert result["bucket"] == "hard"
    assert result["disabled_changed"] is True
    assert store.is_disabled("yyds_mail", "bad.test")
