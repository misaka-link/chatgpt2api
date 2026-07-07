import json

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


def test_yyds_learning_retries_when_api_returns_locally_disabled_domain(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)
    store.upsert_blacklisted_domain("yyds_mail", "bad.test", "registration_disallowed")

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
    requests = []

    def fake_request(method, path, token="", params=None, payload=None, expected=(200, 201, 204)):
        if path == "/domains":
            return {"items": []}
        requests.append(dict(payload or {}))
        if len(requests) == 1:
            return {"address": "user@bad.test", "token": "mail-token-1"}
        return {"address": "user@good.test", "token": "mail-token-2"}

    provider._request = fake_request
    try:
        mailbox = provider.create_mailbox("user")
    finally:
        provider.close()

    assert len(requests) == 2
    assert mailbox["address"] == "user@good.test"
    assert mailbox["learning_mode"] is True


def test_register_retries_new_yyds_mailbox_on_registration_disallowed(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)

    class FakeSession:
        def close(self):
            pass

    mailboxes = [
        {"provider": "yyds_mail", "provider_ref": "yyds_mail#1", "address": "first@bad.test", "domain": "bad.test", "token": "mail-token-1", "learning_mode": True},
        {"provider": "yyds_mail", "provider_ref": "yyds_mail#1", "address": "second@good.test", "domain": "good.test", "token": "mail-token-2", "learning_mode": True},
    ]
    create_account_calls = []

    monkeypatch.setattr(openai_register, "create_session", lambda proxy="": FakeSession())
    monkeypatch.setattr(openai_register, "create_mailbox", lambda username=None, register_proxy="": dict(mailboxes.pop(0)))
    monkeypatch.setattr(openai_register, "wait_for_code", lambda mailbox, register_proxy="": "123456")
    monkeypatch.setattr(openai_register.PlatformRegistrar, "_platform_authorize", lambda self, email, index: None)
    monkeypatch.setattr(openai_register.PlatformRegistrar, "_register_user", lambda self, email, password, index: None)
    monkeypatch.setattr(openai_register.PlatformRegistrar, "_send_otp", lambda self, index: None)
    monkeypatch.setattr(openai_register.PlatformRegistrar, "_validate_otp", lambda self, code, index: None)
    monkeypatch.setattr(openai_register.PlatformRegistrar, "_exchange_registered_tokens", lambda self, index: {"access_token": "access", "refresh_token": "refresh", "id_token": "id"})

    def fake_create_account(self, name, birthdate, index):
        create_account_calls.append((name, birthdate, index))
        if len(create_account_calls) == 1:
            raise RuntimeError(
                'create_account_http_400, detail={"error": {"message": "Sorry, we cannot create your account with the given information.", "type": "invalid_request_error", "param": null, "code": "registration_disallowed"}}'
            )

    monkeypatch.setattr(openai_register.PlatformRegistrar, "_create_account", fake_create_account)

    registrar = openai_register.PlatformRegistrar()
    try:
        result = registrar.register(1)
    finally:
        registrar.close()

    assert result["email"] == "second@good.test"
    assert result["mail_domain"] == "good.test"
    assert len(create_account_calls) == 2
    assert store.is_disabled("yyds_mail", "bad.test") is True
    blacklisted = store.list_blacklisted_domains("yyds_mail")
    assert blacklisted[0]["domain"] == "bad.test"
    assert blacklisted[0]["hard_fail"] == 1


def test_yyds_reputation_manual_blacklisted_domain_crud(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)

    store.upsert_blacklisted_domain("yyds_mail", "first@bad.test", "manual-block")
    items = store.list_blacklisted_domains("yyds_mail")
    assert items == [
        {
            "domain": "bad.test",
            "success": 0,
            "hard_fail": 0,
            "soft_fail": 0,
            "consecutive_fail": 0,
            "disabled": True,
            "reason": "manual-block",
            "healthy": False,
            "score": 0,
            "last_success_at": "",
            "last_failure_at": items[0]["last_failure_at"],
            "last_failure_reason": "manual-block",
            "updated_at": items[0]["updated_at"],
        }
    ]

    store.upsert_blacklisted_domain("yyds_mail", "next.test", "updated", previous_domain="first@bad.test")
    assert store.is_disabled("yyds_mail", "bad.test") is False
    assert store.is_disabled("yyds_mail", "next.test") is True

    store.delete_blacklisted_domain("yyds_mail", "next.test")
    assert store.list_blacklisted_domains("yyds_mail") == []


def test_yyds_reputation_manual_domain_crud_resets_failures(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)
    store.record_failure("yyds_mail", "bad.test", "The email you provided is not supported")

    assert store.is_disabled("yyds_mail", "bad.test") is True

    item = store.upsert_trusted_domain("yyds_mail", "good.test", previous_domain="bad.test")
    assert item["domain"] == "good.test"
    assert item["success"] >= 1
    assert item["hard_fail"] == 0
    assert item["soft_fail"] == 0
    assert item["healthy"] is True
    assert store.is_disabled("yyds_mail", "good.test") is False

    domains = store.list_trusted_domains("yyds_mail")
    assert [entry["domain"] for entry in domains] == ["good.test"]

    store.delete_domain("yyds_mail", "good.test")
    assert store.list_trusted_domains("yyds_mail") == []


def test_yyds_reputation_clear_all_actions_only_remove_visible_sections(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)

    store.upsert_blacklisted_domain("yyds_mail", "blocked.test", "manual-block")
    store.upsert_trusted_domain("yyds_mail", "good.test")
    store.record_failure("yyds_mail", "soft.test", "YYDSMail 请求异常")

    assert store.clear_blacklisted_domains("yyds_mail") == 1
    assert store.list_blacklisted_domains("yyds_mail") == []

    assert store.clear_trusted_domains("yyds_mail") == 1
    assert store.list_trusted_domains("yyds_mail") == []
    assert store.usable_domains("yyds_mail", ["soft.test"]) == ["soft.test"]


def test_yyds_reputation_migrates_legacy_mailbox_blacklist(monkeypatch, tmp_path):
    file_path = tmp_path / "mail_domain_reputation.json"
    file_path.write_text(
        json.dumps(
            {
                "providers": {
                    "yyds_mail#1": {
                        "mailboxes": {
                            "legacy@legacy.test": {
                                "disabled": True,
                                "reason": "legacy-block",
                                "updated_at": "2026-07-07T00:00:00+00:00",
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = domain_reputation.DomainReputationStore(file_path)
    monkeypatch.setattr(domain_reputation, "store", store)

    items = store.list_blacklisted_domains("yyds_mail")

    assert [item["domain"] for item in items] == ["legacy.test"]
    assert items[0]["reason"] == "legacy-block"
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert "mailboxes" not in json.dumps(data, ensure_ascii=False)


def test_mail_provider_entries_preserve_existing_provider_ref():
    items = mail_provider._entries(
        {
            "providers": [
                {"type": "yyds_mail", "provider_ref": "stable-yyds", "enable": True},
                {"type": "yyds_mail", "enable": True},
            ]
        }
    )

    assert items[0]["provider_ref"] == "stable-yyds"
    assert items[1]["provider_ref"] == "yyds_mail#2"
