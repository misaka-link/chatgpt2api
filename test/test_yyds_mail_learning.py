import pytest

from services.register import domain_reputation, mail_provider, openai_register


def test_yyds_non_learning_filters_disabled_domains(monkeypatch, tmp_path):
    store = domain_reputation.DomainReputationStore(tmp_path / "mail_domain_reputation.json")
    monkeypatch.setattr(domain_reputation, "store", store)
    store.record_failure("yyds_mail", "bad.test", "The email you provided is not supported")

    provider = mail_provider.YydsMailProvider(
        {"provider_ref": "yyds_mail#1", "api_key": "token", "domain": ["bad.test"], "learning_mode": False},
        {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 1, "user_agent": "pytest", "proxy": ""},
    )
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
        payloads.append(dict(payload or {}))
        return {"address": "user@good.test", "token": "mail-token"}

    provider._request = fake_request
    try:
        mailbox = provider.create_mailbox("user")
    finally:
        provider.close()

    assert payloads[0]["domain"] == "good.test"
    assert mailbox["domain"] == "good.test"


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
