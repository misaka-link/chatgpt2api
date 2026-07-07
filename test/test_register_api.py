from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from unittest import mock
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT_DIR / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_register_module():
    api_package = types.ModuleType("api")
    api_package.__path__ = [str(ROOT_DIR / "api")]
    previous = {name: sys.modules.get(name) for name in ("api", "api.support", "api.register")}
    sys.modules["api"] = api_package
    support_module = _load_module("api.support", "api/support.py")
    setattr(api_package, "support", support_module)
    register_module = _load_module("api.register", "api/register.py")
    setattr(api_package, "register", register_module)
    return previous, register_module


def _restore_modules(previous: dict[str, object | None]) -> None:
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


AUTH_HEADERS = {"Authorization": "Bearer chatgpt2api"}


class FakeRegisterService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get(self) -> dict:
        return {"enabled": False}

    def update(self, _updates: dict) -> dict:
        return {"enabled": False}

    def start(self) -> dict:
        return {"enabled": True}

    def stop(self) -> dict:
        return {"enabled": False}

    def reset(self) -> dict:
        return {"enabled": False}

    def reset_outlook_pool(self, scope: str) -> dict:
        return {"scope": scope}

    def get_reputation(self, provider: str, provider_ref: str = "") -> dict:
        self.calls.append(("get_reputation", provider, provider_ref))
        return {
            "provider": provider,
            "provider_ref": provider_ref,
            "blacklisted_domains": [],
            "trusted_domains": [],
        }

    def upsert_reputation_blacklisted_domain(self, provider: str, provider_ref: str, domain: str, reason: str = "", previous_domain: str = "") -> dict:
        self.calls.append(("upsert_blacklisted_domain", provider, provider_ref, domain, reason, previous_domain))
        if "." not in domain and "@" not in domain:
            raise ValueError("域名不能为空")
        return self.get_reputation(provider, provider_ref)

    def delete_reputation_blacklisted_domain(self, provider: str, provider_ref: str, domain: str) -> dict:
        self.calls.append(("delete_blacklisted_domain", provider, provider_ref, domain))
        if "." not in domain and "@" not in domain:
            raise ValueError("域名不能为空")
        return self.get_reputation(provider, provider_ref)

    def clear_reputation_blacklisted_domains(self, provider: str, provider_ref: str) -> dict:
        self.calls.append(("clear_blacklisted_domains", provider, provider_ref))
        return {"cleared": 2, "reputation": self.get_reputation(provider, provider_ref)}

    def upsert_reputation_domain(self, provider: str, provider_ref: str, domain: str, previous_domain: str = "") -> dict:
        self.calls.append(("upsert_domain", provider, provider_ref, domain, previous_domain))
        if "." not in domain:
            raise ValueError("域名不能为空")
        return self.get_reputation(provider, provider_ref)

    def delete_reputation_domain(self, provider: str, provider_ref: str, domain: str) -> dict:
        self.calls.append(("delete_domain", provider, provider_ref, domain))
        if "." not in domain:
            raise ValueError("域名不能为空")
        return self.get_reputation(provider, provider_ref)

    def clear_reputation_trusted_domains(self, provider: str, provider_ref: str) -> dict:
        self.calls.append(("clear_trusted_domains", provider, provider_ref))
        return {"cleared": 3, "reputation": self.get_reputation(provider, provider_ref)}


class RegisterApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_modules, self.register_module = _load_register_module()
        self.addCleanup(lambda: _restore_modules(self.previous_modules))
        self.fake_service = FakeRegisterService()
        self.patchers = [
            mock.patch.object(self.register_module, "require_admin", lambda _authorization: {"role": "admin"}),
            mock.patch.object(self.register_module, "register_service", self.fake_service),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(self.register_module.create_router())
        self.client = TestClient(app)

    def test_get_register_reputation(self) -> None:
        response = self.client.get(
            "/api/register/reputation",
            headers=AUTH_HEADERS,
            params={"provider": "yyds_mail", "provider_ref": "yyds_mail#1"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["reputation"]
        self.assertEqual(payload["provider"], "yyds_mail")
        self.assertEqual(payload["provider_ref"], "yyds_mail#1")
        self.assertIn(("get_reputation", "yyds_mail", "yyds_mail#1"), self.fake_service.calls)

    def test_blacklisted_domain_upsert_returns_400_on_invalid_domain(self) -> None:
        response = self.client.post(
            "/api/register/reputation/blacklisted-domains",
            headers=AUTH_HEADERS,
            json={
                "provider": "yyds_mail",
                "provider_ref": "yyds_mail#1",
                "domain": "invalid",
                "reason": "manual",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("域名不能为空", response.text)

    def test_domain_delete_routes_to_service(self) -> None:
        response = self.client.post(
            "/api/register/reputation/trusted-domains/delete",
            headers=AUTH_HEADERS,
            json={
                "provider": "yyds_mail",
                "provider_ref": "yyds_mail#1",
                "domain": "good.test",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(("delete_domain", "yyds_mail", "yyds_mail#1", "good.test"), self.fake_service.calls)

    def test_blacklisted_domain_delete_routes_to_service(self) -> None:
        response = self.client.post(
            "/api/register/reputation/blacklisted-domains/delete",
            headers=AUTH_HEADERS,
            json={
                "provider": "yyds_mail",
                "provider_ref": "yyds_mail#1",
                "domain": "bad.test",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(("delete_blacklisted_domain", "yyds_mail", "yyds_mail#1", "bad.test"), self.fake_service.calls)

    def test_blacklisted_domain_clear_routes_to_service(self) -> None:
        response = self.client.post(
            "/api/register/reputation/blacklisted-domains/clear",
            headers=AUTH_HEADERS,
            json={
                "provider": "yyds_mail",
                "provider_ref": "yyds_mail#1",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cleared"], 2)
        self.assertIn(("clear_blacklisted_domains", "yyds_mail", "yyds_mail#1"), self.fake_service.calls)

    def test_trusted_domain_clear_routes_to_service(self) -> None:
        response = self.client.post(
            "/api/register/reputation/trusted-domains/clear",
            headers=AUTH_HEADERS,
            json={
                "provider": "yyds_mail",
                "provider_ref": "yyds_mail#1",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cleared"], 3)
        self.assertIn(("clear_trusted_domains", "yyds_mail", "yyds_mail#1"), self.fake_service.calls)


if __name__ == "__main__":
    unittest.main()
