from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.codex_cpa_service import build_codex_upload_file
from services.cpa_push_service import upload_auth_file
from services.cpa_service import cpa_config
from services.register.openai_register import PlatformRegistrar, codex_oauth_profile, config


def _select_pool(pool_id: str = "", push_first_pool: bool = False) -> dict | None:
    pools = cpa_config.list_pools()
    if pool_id:
        return cpa_config.get_pool(pool_id)
    if push_first_pool and pools:
        return pools[0]
    return None


def _write_auth_file(out_dir: Path, filename: str, body: bytes) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_bytes(body)
    return path


def _announce_hero_sms_config() -> None:
    hero_sms = config.get("hero_sms") if isinstance(config.get("hero_sms"), dict) else {}
    if not hero_sms or not hero_sms.get("enabled"):
        return
    if not str(hero_sms.get("api_key") or "").strip():
        raise SystemExit("HeroSMS is enabled but api_key is empty in /register config")
    country_pool = hero_sms.get("country_pool") if isinstance(hero_sms.get("country_pool"), list) else []
    print(
        "HeroSMS enabled: "
        f"service={hero_sms.get('service') or 'dr'}, "
        f"country_pool={country_pool or [hero_sms.get('country') or 16]}, "
        f"operator={hero_sms.get('operator') or 'any'}, "
        f"max_price_usd={hero_sms.get('max_price_usd') or 0.03}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Codex OAuth attempt and emit a CPA type=codex auth JSON.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true", help="Create a new account with the configured mail provider, then exchange Codex OAuth tokens.")
    mode.add_argument("--email", help="Use an existing account email.")
    parser.add_argument("--password", default=os.getenv("CODEX_POC_PASSWORD", ""), help="Existing account password. Defaults to CODEX_POC_PASSWORD.")
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "codex_auth_files"), help="Where to write the generated CPA JSON.")
    parser.add_argument("--push-cpa-pool-id", default="", help="Upload the generated auth file to this configured CPA pool id.")
    parser.add_argument("--push-first-cpa-pool", action="store_true", help="Upload to the first configured CPA pool.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _announce_hero_sms_config()
    registrar = PlatformRegistrar(config.get("proxy") or "")
    try:
        if args.register:
            result = registrar.register(1, profile=codex_oauth_profile)
            tokens = {
                "email": result.get("email"),
                "access_token": result.get("access_token"),
                "refresh_token": result.get("refresh_token"),
                "id_token": result.get("id_token"),
            }
        else:
            if not args.password:
                raise SystemExit("--password or CODEX_POC_PASSWORD is required with --email")
            tokens = registrar._login_and_exchange_tokens(
                args.email,
                args.password,
                {},
                1,
                profile=codex_oauth_profile,
            )

        filename, body = build_codex_upload_file(tokens)
        path = _write_auth_file(Path(args.out_dir), filename, body)
        print(f"wrote: {path}")

        pool = _select_pool(args.push_cpa_pool_id, args.push_first_cpa_pool)
        if pool:
            upload_auth_file(pool, filename, body)
            print(f"uploaded to CPA pool {pool.get('id')}")
        elif args.push_cpa_pool_id:
            raise SystemExit(f"CPA pool not found: {args.push_cpa_pool_id}")
        else:
            print("CPA upload skipped: pass --push-cpa-pool-id or --push-first-cpa-pool")
        return 0
    finally:
        registrar.close()


if __name__ == "__main__":
    raise SystemExit(main())
