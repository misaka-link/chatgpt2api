# 注册后自动导入 CPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 注册成功后自动把完整 CPA 文件推送到 CLIProxyAPI 管理 API，并保留本地号池入库，不破坏现有注册流程。

**Architecture:** 在注册 worker 成功拿到 `access_token / refresh_token / id_token` 后，复用现有 CPA payload 生成逻辑构造单个 JSON 文件，再通过 CLIProxyAPI Management API 上传。注册成功与 CPA 推送解耦：本地入号成功即算注册成功，CPA 推送失败只记录日志和统计，不影响 worker 返回值。配置放在注册设置里，默认可开可关。

**Tech Stack:** Python 3.13, FastAPI, curl-cffi, Next.js/React, Zustand, existing settings page/store, Docker host.docker.internal.

---

### Task 1: Add CPA auto-import config to register settings model and API

**Files:**
- Modify: `services/register_service.py`
- Modify: `api/register.py`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/app/settings/store.ts`

- [ ] **Step 1: Write the failing test**

```python
# test/test_register_cpa_auto_import.py
from unittest import mock

def test_register_config_includes_cpa_auto_import_fields():
    data = register_service.get()
    assert data["cpa_auto_import"]["enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest test.test_register_cpa_auto_import -v`
Expected: FAIL because `cpa_auto_import` is missing from the register config.

- [ ] **Step 3: Write minimal implementation**

```python
# services/register_service.py

def _default_config() -> dict:
    return {
        **openai_register.config,
        "mode": "total",
        "target_quota": 100,
        "target_available": 10,
        "check_interval": 5,
        "enabled": False,
        "cpa_auto_import": {
            "enabled": False,
            "base_url": "http://host.docker.internal:8317",
            "secret_key": "",
        },
        "stats": {...},
    }

# api/register.py
class RegisterConfigRequest(BaseModel):
    ...
    cpa_auto_import: dict | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest test.test_register_cpa_auto_import -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/register_service.py api/register.py web/src/lib/api.ts web/src/app/settings/store.ts test/test_register_cpa_auto_import.py
git commit -m "feat: add cpa auto import config"
```

### Task 2: Push full CPA file after successful register

**Files:**
- Create: `services/cpa_push_service.py`
- Modify: `services/register/openai_register.py`
- Modify: `services/register_service.py`
- Modify: `api/register.py`
- Test: `test/test_cpa_push_service.py`
- Test: `test/test_openai_register_cpa_auto_import.py`

- [ ] **Step 1: Write the failing test**

```python
# test/test_cpa_push_service.py

def test_build_cpa_upload_file_uses_full_register_result():
    filename, content = build_cpa_upload_file({
        "email": "a@example.com",
        "access_token": "at",
        "refresh_token": "rt",
        "id_token": "id",
    })
    assert filename == "a@example.com.json"
    assert b'"refresh_token": "rt"' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest test.test_cpa_push_service -v`
Expected: FAIL because the service does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# services/cpa_push_service.py
from pathlib import Path
import json
from services.cpa_export_service import build_cpa_payload, safe_cpa_filename


def build_cpa_upload_file(result: dict) -> tuple[str, bytes]:
    payload = build_cpa_payload(result)
    filename = safe_cpa_filename(payload.get("email") or payload.get("account_id"), 0)
    return filename, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
```

```python
# services/register/openai_register.py
from services.cpa_push_service import push_cpa_auth_file
...
result = registrar.register(index)
account_service.add_accounts([access_token])
account_service.refresh_accounts([access_token])
push_cpa_auth_file(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest test.test_cpa_push_service test.test_openai_register_cpa_auto_import -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/cpa_push_service.py services/register/openai_register.py services/register_service.py api/register.py test/test_cpa_push_service.py test/test_openai_register_cpa_auto_import.py
git commit -m "feat: auto push cpa after register"
```

### Task 3: Expose controls in the settings UI

**Files:**
- Modify: `web/src/app/register/components/register-card.tsx`
- Modify: `web/src/app/settings/store.ts`
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Write the failing test**

```tsx
// no new test runner needed; add a store-level test or run build after wiring state
```

- [ ] **Step 2: Run validation to see the missing fields**

Run: `npm run build`
Expected: build currently passes, but the UI will not expose the new config until code is added.

- [ ] **Step 3: Write minimal implementation**

```tsx
// register-card.tsx: add toggle + base_url + secret_key inputs
// store.ts: add setRegisterCpaAutoImportEnabled / BaseUrl / SecretKey and include them in saveRegister/toggleRegister payloads
```

- [ ] **Step 4: Run build to verify it passes**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/register/components/register-card.tsx web/src/app/settings/store.ts web/src/lib/api.ts
git commit -m "feat: add cpa auto import settings"
```

### Task 4: Verify end-to-end without regressing registration success

**Files:**
- Modify: any tests if needed
- Test: `test/test_register_cpa_auto_import.py`
- Test: `test/test_cpa_push_service.py`
- Test: `test/test_openai_register_cpa_auto_import.py`

- [ ] **Step 1: Write the failing test**

```python
# test/test_openai_register_cpa_auto_import.py

def test_worker_returns_ok_even_if_cpa_push_fails(monkeypatch):
    ...
```

- [ ] **Step 2: Run the focused test suite**

Run: `uv run python -m unittest test.test_register_cpa_auto_import test.test_cpa_push_service test.test_openai_register_cpa_auto_import -v`
Expected: PASS.

- [ ] **Step 3: Write minimal implementation**

```python
# ensure push failures only log and never flip worker ok=False
```

- [ ] **Step 4: Run full relevant verification**

Run: `uv run python -m unittest test.test_register_cpa_auto_import test.test_cpa_push_service test.test_openai_register_cpa_auto_import test.test_accounts_cpa_export_api test.test_cpa_export_service test.test_openai_keys_api test.test_openai_key_service test.test_config -v`
Run: `npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: auto import cpa on register success"
```
