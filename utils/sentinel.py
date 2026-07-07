"""OpenAI Sentinel SDK-backed token helpers.

使用当前官方 Sentinel SDK 生成注册 / 登录阶段所需的 Sentinel token
与 session observer token，避免继续依赖过时的本地手写 PoW 逻辑。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urljoin, urlparse

import quickjs

from utils.log import logger

if TYPE_CHECKING:
    from curl_cffi.requests import Session


DEFAULT_SENTINEL_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
DEFAULT_SENTINEL_SEC_CH_UA = '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"'
SENTINEL_LOADER_URL = "https://sentinel.openai.com/backend-api/sentinel/sdk.js"
SENTINEL_LOADER_FALLBACK_URL = "https://chatgpt.com/backend-api/sentinel/sdk.js"
SENTINEL_REQ_URL = "https://sentinel.openai.com/backend-api/sentinel/req"
SENTINEL_REQ_REFERER = "https://sentinel.openai.com/backend-api/sentinel/frame.html"
SENTINEL_SDK_VERSION_RE = re.compile(r"/sentinel/([^/]+)/sdk\.js")
SENTINEL_HANDLE_PREFIX = "sentinel-handle-"
SENTINEL_REFRESH_AFTER_SECONDS = 15 * 60
SENTINEL_OBSERVER_TIMEOUT_MS = 5000
SENTINEL_REQ_TIMEOUT_SECONDS = 20
SENTINEL_JS_CALL_TIMEOUT_SECONDS = 8.0


@dataclass(slots=True)
class _SdkBundle:
    version: str
    source: str
    sdk_url: str


class _PromiseBridge:
    def __init__(self) -> None:
        self._results: dict[str, Any] = {}
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()

    def resolve(self, promise_id: str, value_json: str) -> None:
        with self._lock:
            self._results[promise_id] = json.loads(value_json)

    def reject(self, promise_id: str, message: str) -> None:
        with self._lock:
            self._errors[promise_id] = str(message)

    def pop_result(self, promise_id: str) -> Any:
        with self._lock:
            if promise_id in self._errors:
                raise RuntimeError(self._errors.pop(promise_id))
            if promise_id in self._results:
                return self._results.pop(promise_id)
        raise KeyError(promise_id)

    def has_result(self, promise_id: str) -> bool:
        with self._lock:
            return promise_id in self._results or promise_id in self._errors


class SentinelTokenGenerator:
    """保留旧类名，兼容现有测试与调用方导入。"""

    def __init__(self, device_id: str, ua: str):
        self.device_id = str(device_id or "")
        self.user_agent = str(ua or DEFAULT_SENTINEL_USER_AGENT)


class SentinelSDKRuntime:
    def __init__(self, sdk_bundle: _SdkBundle, user_agent: str) -> None:
        self.sdk_bundle = sdk_bundle
        self.user_agent = str(user_agent or DEFAULT_SENTINEL_USER_AGENT)
        self._bridge = _PromiseBridge()
        self._context = quickjs.Context()
        self._context.set_max_stack_size(1024 * 1024)
        self._context.set_memory_limit(256 * 1024 * 1024)
        self._install_python_bridges()
        self._context.eval(self._build_js_shim())
        self._context.eval(self._inject_exports(self.sdk_bundle.source))

    def _install_python_bridges(self) -> None:
        self._context.add_callable("__py_random_hex", lambda n: os.urandom(int(n)).hex())
        self._context.add_callable("__py_uuid4", lambda: str(uuid.uuid4()))
        self._context.add_callable("__py_url_parts", self._py_url_parts)
        self._context.add_callable("__py_parse_qsl", self._py_parse_qsl)
        self._context.add_callable("__py_resolve", self._bridge.resolve)
        self._context.add_callable("__py_reject", self._bridge.reject)

    @staticmethod
    def _py_url_parts(url: str, base: str | None = None) -> str:
        full = urljoin(base or "", str(url or ""))
        parsed = urlparse(full)
        return json.dumps(
            {
                "href": full,
                "origin": f"{parsed.scheme}://{parsed.netloc}",
                "pathname": parsed.path,
                "search": f"?{parsed.query}" if parsed.query else "",
                "hostname": parsed.hostname or "",
                "host": parsed.netloc,
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _py_parse_qsl(query: str) -> str:
        pairs = list(parse_qsl(str(query or "").lstrip("?"), keep_blank_values=True))
        return json.dumps(pairs, separators=(",", ":"))

    def _inject_exports(self, source: str) -> str:
        needle = "t.init=we,t.sessionObserverToken=async function(t){"
        if needle not in source:
            raise RuntimeError("sentinel_sdk_export_hook_missing")
        exports = (
            "window.__py_handles=new Map(),"
            "t.__PY={"
            "makeHandle:function(reqJson){var id='"
            + SENTINEL_HANDLE_PREFIX
            + "'+C();window.__py_handles.set(id,JSON.parse(reqJson));return id;},"
            "getRequirementsToken:function(){return P.getRequirementsToken();},"
            "getRequirementsTokenBlocking:function(){return P.getRequirementsTokenBlocking();},"
            "getEnforcementToken:function(handle){return P.getEnforcementToken(window.__py_handles.get(handle));},"
            "getEnforcementTokenSync:function(handle){return P.getEnforcementTokenSync(window.__py_handles.get(handle));},"
            "attachRequirements:function(handle,proof){var req=window.__py_handles.get(handle);D(req,proof);return null;},"
            "runTurnstile:function(handle){var req=window.__py_handles.get(handle);return req&&req.turnstile&&req.turnstile.dx?_n(req,req.turnstile.dx):Promise.resolve(null);},"
            "runCollector:function(handle){var req=window.__py_handles.get(handle);var so=req&&req.so;if(!req||!so||so.required!==true||typeof so.collector_dx!=='string')return Promise.resolve(null);var key=$((req??{}))??'';return Ot(function(){return jt(so.collector_dx,key);});},"
            "runSnapshot:function(handle){var req=window.__py_handles.get(handle);var so=req&&req.so;if(!req||!so||so.required!==true||typeof so.snapshot_dx!=='string')return Promise.resolve(null);return Nt(so.snapshot_dx);},"
            "sdkVersion:function(){return Zn||null;}"
            "},"
        )
        return source.replace(needle, exports + needle, 1)

    def _build_js_shim(self) -> str:
        sdk_url = json.dumps(self.sdk_bundle.sdk_url)
        user_agent = json.dumps(self.user_agent)
        return f"""
var __realGlobal = globalThis;
var __now = 1000;
var __timerSeq = 1;
var __timers = [];
function setTimeout(fn, delay) {{
  var id = __timerSeq++;
  __timers.push({{ id: id, at: __now + (Number(delay) || 0), fn: fn }});
  return id;
}}
function clearTimeout(id) {{
  __timers = __timers.filter(function(t) {{ return t.id !== id; }});
}}
function __advanceTimers(ms) {{
  __now += Number(ms) || 0;
  var ran = 0;
  while (true) {{
    var nextIndex = -1;
    var nextAt = Infinity;
    for (var i = 0; i < __timers.length; i++) {{
      if (__timers[i].at <= __now && __timers[i].at < nextAt) {{
        nextAt = __timers[i].at;
        nextIndex = i;
      }}
    }}
    if (nextIndex < 0) break;
    var timer = __timers.splice(nextIndex, 1)[0];
    timer.fn();
    ran += 1;
  }}
  return ran;
}}
function requestIdleCallback(fn, opts) {{
  return setTimeout(function() {{
    fn({{ timeRemaining: function() {{ return 10; }}, didTimeout: false }});
  }}, 0);
}}
function URL(input, base) {{
  var p = JSON.parse(__py_url_parts(String(input), base === undefined ? null : String(base)));
  this.href = p.href;
  this.origin = p.origin;
  this.pathname = p.pathname;
  this.search = p.search;
  this.hostname = p.hostname;
  this.host = p.host;
}}
function URLSearchParams(init) {{
  this.__entries = [];
  if (typeof init === 'string') {{
    this.__entries = JSON.parse(__py_parse_qsl(init));
  }} else if (init && typeof init.length === 'number') {{
    for (var i = 0; i < init.length; i++) this.__entries.push(init[i]);
  }}
}}
URLSearchParams.prototype[Symbol.iterator] = function() {{
  return this.__entries[Symbol.iterator]();
}};
var __b64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
function atob(input) {{
  var str = String(input).replace(/=+$/, '');
  var output = '';
  if (str.length % 4 === 1) throw new Error('bad base64');
  for (var bc = 0, bs, buffer, idx = 0; (buffer = str.charAt(idx++)); ) {{
    buffer = __b64.indexOf(buffer);
    if (~buffer) {{
      bs = bc % 4 ? bs * 64 + buffer : buffer;
      if (bc++ % 4) output += String.fromCharCode(255 & (bs >> ((-2 * bc) & 6)));
    }}
  }}
  return output;
}}
function btoa(input) {{
  var str = String(input);
  var output = '';
  for (var block, charCode, idx = 0, map = __b64; str.charAt(idx | 0) || (map = '=', idx % 1); output += map.charAt(63 & block >> 8 - idx % 1 * 8)) {{
    charCode = str.charCodeAt(idx += 3 / 4);
    if (charCode > 0xFF) throw new Error('bad char');
    block = block << 8 | charCode;
  }}
  return output;
}}
function __magic(name) {{
  var fn = function() {{ return null; }};
  return new Proxy(fn, {{
    get: function(target, prop) {{
      if (prop in target) return target[prop];
      if (prop === Symbol.iterator) return function*(){{}};
      if (prop === 'valueOf') return function() {{ return null; }};
      if (prop === 'toJSON') return function() {{ return null; }};
      if (prop === 'bind') return Function.prototype.bind.bind(fn);
      return __magic(name + '.' + String(prop));
    }},
    apply: function(target, thisArg, args) {{
      return null;
    }}
  }});
}}
function __wrap(base, name) {{
  return new Proxy(base, {{
    get: function(target, prop) {{
      if (prop in target) return target[prop];
      return __magic(name + '.' + String(prop));
    }},
    set: function(target, prop, value) {{
      target[prop] = value;
      return true;
    }}
  }});
}}
var performance = __wrap({{
  now: function() {{ return __now; }},
  timeOrigin: 1700000000000,
  memory: {{ jsHeapSizeLimit: 4294705152 }}
}}, 'performance');
var navigator = __wrap({{
  userAgent: {user_agent},
  language: 'en-US',
  languages: ['en-US', 'en'],
  hardwareConcurrency: 8
}}, 'navigator');
var screen = __wrap({{ width: 1920, height: 1080 }}, 'screen');
var __docScripts = [{{ src: {sdk_url} }}, {{ src: 'https://auth.openai.com/c/prod-test/_' }}];
function __makeElement(tag) {{
  return __wrap({{
    tagName: String(tag || '').toUpperCase(),
    style: {{}},
    src: '',
    addEventListener: function(event, cb) {{ if (event === 'load') setTimeout(cb, 0); }},
    contentWindow: __magic('contentWindow')
  }}, 'element');
}}
var document = __wrap({{
  cookie: '',
  scripts: __docScripts,
  currentScript: __docScripts[0],
  documentElement: {{ getAttribute: function(name) {{ return name === 'data-build' ? 'prod-test-build' : null; }} }},
  body: {{ appendChild: function(el) {{ return el; }} }},
  head: {{ appendChild: function(el) {{ return el; }} }},
  createElement: function(tag) {{ return __makeElement(tag); }}
}}, 'document');
var window = __wrap(__realGlobal, 'window');
window.window = window;
window.self = window;
window.globalThis = window;
window.top = window;
window.location = new URL('https://chatgpt.com/');
window.document = document;
window.navigator = navigator;
window.screen = screen;
window.performance = performance;
window.addEventListener = function() {{}};
window.removeEventListener = function() {{}};
window.requestIdleCallback = requestIdleCallback;
window.structuredClone = function(v) {{ return JSON.parse(JSON.stringify(v)); }};
window.ai = {{}};
window.solana = {{}};
window.TextEncoder = undefined;
var crypto = {{
  getRandomValues: function(arr) {{
    var hex = __py_random_hex(arr.length);
    for (var i = 0; i < arr.length; i++) {{
      arr[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    }}
    return arr;
  }},
  randomUUID: function() {{ return __py_uuid4(); }}
}};
window.crypto = crypto;
function __py_call(name, argsJson, promiseId) {{
  try {{
    var fn = SentinelSDK.__PY[name];
    var args = JSON.parse(argsJson || '[]');
    var result = fn.apply(null, args);
    if (result && typeof result.then === 'function') {{
      Promise.resolve(result).then(
        function(v) {{ __py_resolve(promiseId, JSON.stringify(v === undefined ? null : v)); }},
        function(err) {{ __py_reject(promiseId, String((err && err.stack) || (err && err.message) || err)); }}
      );
      return 'async';
    }}
    __py_resolve(promiseId, JSON.stringify(result === undefined ? null : result));
    return 'sync';
  }} catch (err) {{
    __py_reject(promiseId, String((err && err.stack) || (err && err.message) || err));
    return 'error';
  }}
}}
"""

    def call(self, name: str, *args: Any, timeout: float = SENTINEL_JS_CALL_TIMEOUT_SECONDS) -> Any:
        promise_id = str(uuid.uuid4())
        args_json = json.dumps(args, separators=(",", ":"))
        self._context.eval(
            f"__py_call({json.dumps(name)}, {json.dumps(args_json)}, {json.dumps(promise_id)})"
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            progressed = False
            while self._context.execute_pending_job():
                progressed = True
            try:
                if self._context.eval("__advanceTimers(10)"):
                    progressed = True
            except Exception:
                pass
            while self._context.execute_pending_job():
                progressed = True
            if self._bridge.has_result(promise_id):
                return self._bridge.pop_result(promise_id)
            if not progressed:
                time.sleep(0.001)
        raise TimeoutError(f"sentinel_js_timeout:{name}")


class _SentinelRuntimePool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sdk_cache: _SdkBundle | None = None
        self._sdk_cache_at = 0.0
        self._runtime_cache: dict[str, SentinelSDKRuntime] = {}

    def get_runtime(self, session: "Session", user_agent: str) -> SentinelSDKRuntime:
        sdk_bundle = self._get_sdk_bundle(session, user_agent)
        cache_key = f"{sdk_bundle.version}|{user_agent}"
        with self._lock:
            runtime = self._runtime_cache.get(cache_key)
            if runtime is None:
                runtime = SentinelSDKRuntime(sdk_bundle, user_agent)
                self._runtime_cache[cache_key] = runtime
            return runtime

    def _get_sdk_bundle(self, session: "Session", user_agent: str) -> _SdkBundle:
        with self._lock:
            cached = self._sdk_cache
            if cached and time.time() - self._sdk_cache_at < SENTINEL_REFRESH_AFTER_SECONDS:
                return cached
        bundle = self._fetch_sdk_bundle(session, user_agent)
        with self._lock:
            self._sdk_cache = bundle
            self._sdk_cache_at = time.time()
        return bundle

    @staticmethod
    def _fetch_sdk_bundle(session: "Session", user_agent: str) -> _SdkBundle:
        headers = {
            "User-Agent": user_agent or DEFAULT_SENTINEL_USER_AGENT,
            "Accept": "*/*",
            "Referer": "https://auth.openai.com/",
            "sec-ch-ua": DEFAULT_SENTINEL_SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        loader_resp = None
        last_error = ""
        for loader_url in (SENTINEL_LOADER_URL, SENTINEL_LOADER_FALLBACK_URL):
            try:
                loader_resp = session.get(loader_url, headers=headers, timeout=SENTINEL_REQ_TIMEOUT_SECONDS, verify=False)
                if loader_resp.status_code == 200 and loader_resp.text:
                    break
                last_error = f"{loader_url}:{loader_resp.status_code}"
            except Exception as error:
                last_error = f"{loader_url}:{error}"
        if loader_resp is None or loader_resp.status_code != 200:
            raise RuntimeError(f"sentinel_loader_fetch_failed:{last_error}")
        match = SENTINEL_SDK_VERSION_RE.search(str(loader_resp.text or ""))
        if not match:
            raise RuntimeError("sentinel_sdk_version_not_found")
        version = match.group(1).strip()
        sdk_url = f"https://sentinel.openai.com/sentinel/{version}/sdk.js"
        sdk_resp = session.get(sdk_url, headers=headers, timeout=SENTINEL_REQ_TIMEOUT_SECONDS, verify=False)
        if sdk_resp.status_code != 200 or not sdk_resp.text:
            raise RuntimeError(f"sentinel_sdk_fetch_failed:{sdk_resp.status_code}")
        return _SdkBundle(version=version, source=str(sdk_resp.text), sdk_url=sdk_url)


_runtime_pool = _SentinelRuntimePool()


def _so_header_from_snapshot(snapshot_value: str | None, challenge_token: str, device_id: str, flow: str) -> str:
    snapshot_value = str(snapshot_value or "").strip()
    if not snapshot_value:
        return ""
    if challenge_token:
        return json.dumps(
            {"so": snapshot_value, "c": challenge_token, "id": device_id, "flow": flow},
            separators=(",", ":"),
        )
    return snapshot_value


def build_sentinel_token(
    session: "Session",
    device_id: str,
    flow: str,
    *,
    user_agent: str = "",
    sec_ch_ua: str = "",
) -> tuple[str, str, str]:
    """请求 sentinel token 并返回 (sentinel_header, oai-sc cookie, so_header)。"""
    ua = user_agent or DEFAULT_SENTINEL_USER_AGENT
    ch_ua = sec_ch_ua or DEFAULT_SENTINEL_SEC_CH_UA
    runtime = _runtime_pool.get_runtime(session, ua)
    requirements_token = str(runtime.call("getRequirementsToken", timeout=4.0) or "").strip()
    if not requirements_token:
        raise RuntimeError("sentinel_requirements_token_empty")

    req_resp = session.post(
        SENTINEL_REQ_URL,
        data=json.dumps({"p": requirements_token, "id": device_id, "flow": flow}),
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "Referer": SENTINEL_REQ_REFERER,
            "Origin": "https://sentinel.openai.com",
            "User-Agent": ua,
            "sec-ch-ua": ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
        timeout=SENTINEL_REQ_TIMEOUT_SECONDS,
        verify=False,
    )
    data = req_resp.json() if req_resp.text else {}
    challenge_token = str(data.get("token") or "").strip()
    if req_resp.status_code != 200 or not challenge_token:
        raise RuntimeError(f"sentinel_req_failed_{req_resp.status_code}")

    handle = str(runtime.call("makeHandle", json.dumps(data, separators=(",", ":"))))
    runtime.call("attachRequirements", handle, requirements_token)
    enforcement_token = str(runtime.call("getEnforcementToken", handle) or "").strip()
    if not enforcement_token:
        raise RuntimeError("sentinel_enforcement_token_empty")

    turnstile_token = ""
    try:
        turnstile_token = str(runtime.call("runTurnstile", handle, timeout=5.0) or "").strip()
    except Exception:
        turnstile_token = ""

    so_header = ""
    snapshot_value = ""
    try:
        runtime.call("runCollector", handle, timeout=5.0)
        snapshot_value = str(runtime.call("runSnapshot", handle, timeout=5.0) or "").strip()
        so_header = _so_header_from_snapshot(snapshot_value, challenge_token, device_id, flow)
    except Exception as error:
        logger.warning(
            {
                "event": "sentinel_so_generation_failed",
                "flow": flow,
                "sdk_version": runtime.sdk_bundle.version,
                "error": str(error),
            }
        )

    sentinel_value = json.dumps(
        {
            "p": enforcement_token,
            "t": turnstile_token or None,
            "c": challenge_token,
            "id": device_id,
            "flow": flow,
        },
        separators=(",", ":"),
    ).replace(":null", ':""')
    oai_sc_value = "0" + challenge_token
    logger.info(
        {
            "event": "sentinel_tokens_generated",
            "flow": flow,
            "sdk_version": runtime.sdk_bundle.version,
            "sentinel_token_length": len(sentinel_value),
            "so_token_generated": bool(so_header),
            "so_token_length": len(so_header),
        }
    )
    return sentinel_value, oai_sc_value, so_header
