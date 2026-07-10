import base64
import json
import random
import re
import time
from typing import Any, Dict, Optional


class OrderedMap:
    def __init__(self) -> None:
        self.keys = []
        self.values = {}

    def add(self, key: str, value: Any) -> None:
        if key not in self.values:
            self.keys.append(key)
        self.values[key] = value


TURNSTILE_LOCAL_STORAGE_KEYS = [
    "STATSIG_LOCAL_STORAGE_INTERNAL_STORE_V4",
    "STATSIG_LOCAL_STORAGE_STABLE_ID",
    "client-correlated-secret",
    "oai/apps/capExpiresAt",
    "oai-did",
    "STATSIG_LOCAL_STORAGE_LOGGING_REQUEST",
    "UiState.isNavigationCollapsed.1",
]

TURNSTILE_SCRIPTS = [
    "https://chatgpt.com/backend-api/sentinel/sdk.js",
    "https://auth.openai.com/c/prod-test/_",
]

TURNSTILE_NATIVE_STRINGS = {
    "window.Math": "[object Math]",
    "window.Reflect": "[object Reflect]",
    "window.performance": "[object Performance]",
    "window.localStorage": "[object Storage]",
    "window.Object": "function Object() { [native code] }",
    "window.Array": "function Array() { [native code] }",
    "window.String": "function String() { [native code] }",
    "window.Reflect.set": "function set() { [native code] }",
    "window.performance.now": "function () { [native code] }",
    "window.Object.create": "function create() { [native code] }",
    "window.Object.keys": "function keys() { [native code] }",
    "window.Math.random": "function random() { [native code] }",
    "window.Array.from": "function from() { [native code] }",
    "window.String.fromCharCode": "function fromCharCode() { [native code] }",
}


def _turnstile_to_str(value: Any) -> str:
    if value is None:
        return "undefined"
    if isinstance(value, float):
        text = str(value)
        return text[:-2] if text.endswith(".0") else text
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return TURNSTILE_NATIVE_STRINGS.get(value, value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    return str(value)


def _turnstile_to_number(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _normalize_turnstile_json(value: Any) -> Any:
    if isinstance(value, OrderedMap):
        return {key: _normalize_turnstile_json(value.values[key]) for key in value.keys}
    if isinstance(value, dict):
        return {str(key): _normalize_turnstile_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_turnstile_json(item) for item in value]
    if callable(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _turnstile_to_str(value)


def _xor_string(text: str, key: str) -> str:
    if not key:
        return text
    return "".join(chr(ord(ch) ^ ord(key[i % len(key)])) for i, ch in enumerate(text))


def solve_turnstile_token(dx: str, p: str) -> Optional[str]:
    try:
        decoded = base64.b64decode(dx).decode()
        token_list = json.loads(_xor_string(decoded, p))
    except Exception:
        return None

    process_map: Dict[Any, Any] = {}
    start_time = time.time()
    result = ""
    step_count = 0

    def _value(key: Any) -> Any:
        return process_map.get(key)

    def _run_queue(step_limit: int = 100000) -> None:
        nonlocal step_count
        while isinstance(_value(9), list) and _value(9):
            step_count += 1
            if step_count > step_limit:
                raise RuntimeError("turnstile_step_limit")
            token = _value(9).pop(0)
            fn = _value(token[0])
            if not callable(fn):
                raise KeyError(token[0])
            fn(*token[1:])

    def func_0(e: float) -> None:
        process_map[e] = solve_turnstile_token(_turnstile_to_str(_value(e)), _turnstile_to_str(_value(16)))

    def func_1(e: float, t: float) -> None:
        process_map[e] = _xor_string(_turnstile_to_str(_value(e)), _turnstile_to_str(_value(t)))

    def func_2(e: float, t: Any) -> None:
        process_map[e] = t

    def func_3(e: str) -> None:
        nonlocal result
        result = base64.b64encode(_turnstile_to_str(e).encode()).decode()

    def func_5(e: float, t: float) -> None:
        current = _value(e)
        incoming = _value(t)
        if isinstance(current, (list, tuple)):
            process_map[e] = list(current) + [incoming]
            return
        process_map[e] = _turnstile_to_str(current) + _turnstile_to_str(incoming)

    def func_6(e: float, t: float, n: float) -> None:
        target = _value(t)
        prop = _value(n)
        if isinstance(target, str) and isinstance(prop, str):
            value = f"{target}.{prop}"
            process_map[e] = "https://chatgpt.com/" if value == "window.document.location" else value
            return
        if isinstance(target, list):
            if isinstance(prop, (int, float)):
                process_map[e] = target[int(prop)]
            elif prop == "length":
                process_map[e] = len(target)
            else:
                process_map[e] = None
            return
        if isinstance(target, OrderedMap):
            process_map[e] = target.values.get(str(prop))
            return
        if isinstance(target, dict):
            process_map[e] = target.get(prop)
            return
        process_map[e] = None

    def func_7(e: float, *args: float) -> Any:
        target = _value(e)
        values = [_value(arg) for arg in args]
        if isinstance(target, str):
            if target == "window.Reflect.set":
                obj, key_name, val = values
                if isinstance(obj, OrderedMap):
                    obj.add(str(key_name), val)
                elif isinstance(obj, dict):
                    obj[str(key_name)] = val
                return None
            if target == "window.Array.from":
                process_map[e] = list(values[0]) if values else []
                return None
            if target == "window.String.fromCharCode":
                process_map[e] = "".join(chr(int(value)) for value in values)
                return None
        if callable(target):
            return target(*values)
        return None

    def func_8(e: float, t: float) -> None:
        process_map[e] = _value(t)

    def func_11(e: float, t: float) -> None:
        pattern = str(_value(t) or "")
        matched = None
        for src in TURNSTILE_SCRIPTS:
            match = re.search(pattern, src)
            if match:
                matched = match.group(0)
                break
        process_map[e] = matched

    def func_12(e: float) -> None:
        process_map[e] = process_map

    def func_13(e: float, t: float, *args: float) -> None:
        try:
            target = _value(t)
            if callable(target):
                target(*args)
        except Exception as error:
            process_map[e] = str(error)

    def func_14(e: float, t: float) -> None:
        process_map[e] = json.loads(_value(t))

    def func_15(e: float, t: float) -> None:
        process_map[e] = json.dumps(_normalize_turnstile_json(_value(t)), separators=(",", ":"))

    def func_17(e: float, t: float, *args: float) -> None:
        call_args = [_value(arg) for arg in args]
        target = _value(t)
        if target == "window.performance.now":
            elapsed_ns = time.time_ns() - int(start_time * 1e9)
            process_map[e] = (elapsed_ns + random.random()) / 1e6
            return
        if target == "window.Object.create":
            process_map[e] = OrderedMap()
            return
        if target == "window.Object.keys":
            if call_args and call_args[0] == "window.localStorage":
                process_map[e] = list(TURNSTILE_LOCAL_STORAGE_KEYS)
            elif call_args and isinstance(call_args[0], OrderedMap):
                process_map[e] = list(call_args[0].keys)
            elif call_args and isinstance(call_args[0], dict):
                process_map[e] = list(call_args[0].keys())
            else:
                process_map[e] = []
            return
        if target == "window.Math.random":
            process_map[e] = random.random()
            return
        if callable(target):
            process_map[e] = target(*call_args)
            return
        process_map[e] = None

    def func_18(e: float) -> None:
        process_map[e] = base64.b64decode(_turnstile_to_str(_value(e))).decode()

    def func_19(e: float) -> None:
        process_map[e] = base64.b64encode(_turnstile_to_str(_value(e)).encode()).decode()

    def func_20(e: float, t: float, n: float, *args: float) -> Any:
        if _value(e) == _value(t):
            target = _value(n)
            if callable(target):
                return target(*args)
        return None

    def func_21(e: float, t: float, n: float, o: float, *args: float) -> Any:
        if abs(_turnstile_to_number(_value(e)) - _turnstile_to_number(_value(t))) > _turnstile_to_number(_value(n)):
            target = _value(o)
            if callable(target):
                return target(*args)
        return None

    def func_22(e: float, t: float) -> None:
        saved_queue = list(_value(9) or [])
        process_map[9] = list(_value(t) or [])
        try:
            _run_queue()
        except Exception as error:
            process_map[e] = str(error)
        finally:
            process_map[9] = saved_queue

    def func_23(e: float, t: float, *args: float) -> Any:
        if _value(e) is not None:
            target = _value(t)
            if callable(target):
                return target(*args)
        return None

    def func_24(e: float, t: float, n: float) -> None:
        target = _value(t)
        prop = _value(n)
        if isinstance(target, str) and isinstance(prop, str):
            process_map[e] = f"{target}.{prop}"
        elif isinstance(target, dict):
            process_map[e] = target.get(prop)
        else:
            process_map[e] = getattr(target, str(prop), None)

    def func_27(e: float, t: float) -> None:
        current = _value(e)
        other = _value(t)
        if isinstance(current, list):
            if other in current:
                current = list(current)
                current.remove(other)
            process_map[e] = current
            return
        process_map[e] = _turnstile_to_number(current) - _turnstile_to_number(other)

    def func_28(*_: Any) -> None:
        return

    def func_29(e: float, t: float, n: float) -> None:
        left = _value(t)
        right = _value(n)
        try:
            process_map[e] = left < right
        except TypeError:
            process_map[e] = _turnstile_to_number(left) < _turnstile_to_number(right)

    def func_30(t: float, n: float, e: Any, r: Any = None) -> None:
        has_slots = isinstance(r, list)
        param_slots = e if has_slots else []
        queue = (r if has_slots else e) or []

        def generated(*call_args: Any) -> Any:
            saved_queue = list(_value(9) or [])
            if has_slots:
                for index, slot in enumerate(param_slots):
                    process_map[slot] = call_args[index] if index < len(call_args) else None
            process_map[9] = list(queue)
            try:
                _run_queue()
                return _value(n)
            except Exception as error:
                return str(error)
            finally:
                process_map[9] = saved_queue

        process_map[t] = generated

    def func_33(e: float, t: float, n: float) -> None:
        process_map[e] = _turnstile_to_number(_value(t)) * _turnstile_to_number(_value(n))

    def func_34(e: float, t: float) -> None:
        process_map[e] = _value(t)

    def func_35(e: float, t: float, n: float) -> None:
        divisor = _turnstile_to_number(_value(n))
        process_map[e] = 0 if divisor == 0 else _turnstile_to_number(_value(t)) / divisor

    process_map.update(
        {
            0: func_0,
            1: func_1,
            2: func_2,
            3: func_3,
            5: func_5,
            6: func_6,
            7: func_7,
            8: func_8,
            9: token_list,
            10: "window",
            11: func_11,
            12: func_12,
            13: func_13,
            14: func_14,
            15: func_15,
            16: p,
            17: func_17,
            18: func_18,
            19: func_19,
            20: func_20,
            21: func_21,
            22: func_22,
            23: func_23,
            24: func_24,
            27: func_27,
            28: func_28,
            29: func_29,
            30: func_30,
            33: func_33,
            34: func_34,
            35: func_35,
        }
    )

    try:
        _run_queue()
    except Exception:
        return None
    return result or None
