from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any


DEFAULT_INPUT_SELECTORS = [
    "textarea",
    "[contenteditable='true']",
    "[role='textbox']",
]
DEFAULT_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button[aria-label*='Send']",
    "button[aria-label*='发送']",
    "button[data-testid='send-button']",
]
DEFAULT_REPORT_SELECTORS = [
    "main",
    "article",
    "[data-message-author-role='assistant']",
    ".markdown",
    "body",
]
DEFAULT_FOLLOWUP_MARKERS = [
    "?",
    "？",
    "clarify",
    "could you specify",
    "which",
    "what scope",
    "请确认",
    "需要你",
    "你希望",
    "范围",
]
DEFAULT_BLOCKER_MARKERS = [
    "sign in",
    "log in",
    "login",
    "captcha",
    "upgrade",
    "subscribe",
    "usage limit",
    "rate limit",
    "登录",
    "登入",
    "验证码",
    "验证",
    "开通",
    "升级",
    "会员",
    "额度",
    "次数已用完",
    "达到上限",
]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERSISTENT_PROFILE_ROOT_ENV = "QUESTION_RESEARCH_EXTERNAL_PROFILE_ROOT"
BROWSER_PROXY_ENV = "QUESTION_RESEARCH_BROWSER_PROXY"


BUILTIN_PROVIDER_PROFILES: dict[str, dict[str, Any]] = {
    "chatgpt": {
        "provider": "ChatGPT Deep Research",
        "url": "https://chatgpt.com/",
        "activate_texts": ["Tools", "Deep research", "深度研究"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "use_browser_proxy": True,
        "notes": "Current local test: keeps loading in the automation profile. Keep it out of the default live queue until the profile/network path is fixed.",
    },
    "gemini": {
        "provider": "Gemini Deep Research",
        "url": "https://gemini.google.com/app",
        "activate_texts": ["Deep Research", "深度研究"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "use_browser_proxy": True,
        "notes": "Current local test: Google blocks this Playwright-controlled browser as unsafe. Use a normal supported browser login path before trying automation again.",
    },
    "perplexity": {
        "provider": "Perplexity Research",
        "url": "https://www.perplexity.ai/",
        "activate_texts": ["Research", "Deep Research", "Pro Search"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "Perplexity labels vary by plan and locale; adjust activate_texts if needed.",
    },
    "kimi": {
        "provider": "Kimi 探索",
        "url": "https://kimi.moonshot.cn/",
        "activate_texts": ["探索", "研究"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "Current local test: login state persisted successfully. This is in the default live queue.",
    },
    "qwen": {
        "provider": "通义千问研究",
        "url": "https://www.qianwen.com/?ch=tongyi_redirect",
        "activate_texts": ["研究", "深度研究"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "Requires an already logged-in profile.",
    },
    "doubao": {
        "provider": "豆包深入研究",
        "url": "https://www.doubao.com/chat/",
        "activate_texts": ["深入研究", "研究", "深度研究"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "Current local test: login state persisted successfully. This is in the default live queue.",
    },
    "metaso": {
        "provider": "秘塔深度研究",
        "url": "https://metaso.cn/",
        "activate_texts": ["深度研究", "研究", "深入"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "User reports MetaSo has 深度研究 but quota is low, so it is built in but excluded from the default provider queue.",
    },
    "stepfun": {
        "provider": "阶跃AI / StepFun 深度研究",
        "url": "https://chat.stepfun.com/chats/new",
        "activate_texts": ["深度研究", "研究", "Deep Research"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "User reports 阶跃AI has 深度研究. Uses the chat.stepfun.com chat entrypoint; selectors should be live-verified on this account.",
    },
    "zhipu": {
        "provider": "智谱清言研究报告",
        "url": "https://chatglm.cn/main/alltoolsdetail?lang=zh",
        "activate_texts": ["研究报告", "研究", "报告"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "notes": "Current local test: WAF slider puzzle blocks login verification. Keep it out of the default live queue until manual login becomes usable.",
    },
    "minimax": {
        "provider": "MiniMax Deep Research",
        "url": "https://agent.minimaxi.com/",
        "activate_texts": ["deep research", "Deep Research", "深度研究", "研究"],
        "input_selectors": DEFAULT_INPUT_SELECTORS,
        "submit_selectors": DEFAULT_SUBMIT_SELECTORS,
        "report_selectors": DEFAULT_REPORT_SELECTORS,
        "followup_markers": DEFAULT_FOLLOWUP_MARKERS,
        "blocker_markers": DEFAULT_BLOCKER_MARKERS,
        "use_browser_proxy": True,
        "notes": "Current local test: page keeps loading in the automation profile. Keep it out of the default live queue until the profile/network path is fixed.",
    },
}


def build_provider_profiles(
    providers: list[str],
    *,
    root: str | Path,
    profile_config_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    overrides = _read_profile_overrides(profile_config_path)
    profile_root = _persistent_profile_root()
    rows: list[dict[str, Any]] = []
    for provider in providers:
        key = normalize_provider_key(provider)
        profile = dict(BUILTIN_PROVIDER_PROFILES.get(key, {}))
        profile.update(overrides.get(key, {}))
        profile["provider"] = str(profile.get("provider") or provider).strip()
        profile["requested_provider"] = provider
        profile["key"] = key
        profile["url"] = str(profile.get("url") or "").strip()
        profile["user_data_dir"] = str(profile.get("user_data_dir") or profile_root / key)
        profile["activate_texts"] = _list(profile.get("activate_texts"))
        profile["input_selectors"] = _list(profile.get("input_selectors")) or DEFAULT_INPUT_SELECTORS
        profile["submit_selectors"] = _list(profile.get("submit_selectors")) or DEFAULT_SUBMIT_SELECTORS
        profile["report_selectors"] = _list(profile.get("report_selectors")) or DEFAULT_REPORT_SELECTORS
        profile["followup_markers"] = _list(profile.get("followup_markers")) or DEFAULT_FOLLOWUP_MARKERS
        profile["blocker_markers"] = _list(profile.get("blocker_markers")) or DEFAULT_BLOCKER_MARKERS
        profile["enabled"] = bool(profile.get("enabled", True))
        profile["ready"] = bool(profile["url"])
        profile["proxy_server"] = _profile_proxy_server(profile)
        rows.append(profile)
    return rows


def _persistent_profile_root() -> Path:
    override = str(os.environ.get(PERSISTENT_PROFILE_ROOT_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return PROJECT_ROOT / ".local" / "browser-profiles" / "external-researcher"


def _profile_proxy_server(profile: dict[str, Any]) -> str:
    configured = str(profile.get("proxy_server") or "").strip()
    if configured:
        return configured
    if bool(profile.get("use_browser_proxy")):
        return str(os.environ.get(BROWSER_PROXY_ENV) or "").strip()
    return ""


def _browser_launch_options(profile: dict[str, Any]) -> dict[str, Any]:
    proxy_server = str(profile.get("proxy_server") or "").strip()
    if not proxy_server:
        return {}
    return {"proxy": {"server": proxy_server}}


def preflight_provider_profile(
    profile: dict[str, Any],
    *,
    live: bool = False,
    headless: bool = False,
    timeout_seconds: int = 30,
    click_activation: bool = True,
) -> dict[str, Any]:
    result = _provider_result(profile, "configured" if profile.get("ready") else "missing_url")
    result.update(
        {
            "live": bool(live),
            "enabled": bool(profile.get("enabled", True)),
            "activate_texts": _list(profile.get("activate_texts")),
            "input_selectors": _list(profile.get("input_selectors")),
            "blockers": [],
        }
    )
    if not profile.get("ready") or not live:
        return result
    started = time.time()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local optional install
        result.update({"status": "failed", "error": f"Playwright is not available: {exc}"})
        return result

    with sync_playwright() as playwright:
        browser_name = str(profile.get("browser") or "chromium")
        browser_type = getattr(playwright, browser_name)
        Path(str(profile["user_data_dir"])).mkdir(parents=True, exist_ok=True)
        context = browser_type.launch_persistent_context(
            str(profile["user_data_dir"]),
            headless=bool(headless),
            viewport={"width": 1440, "height": 1000},
            **_browser_launch_options(profile),
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(str(profile["url"]), wait_until="domcontentloaded", timeout=int(timeout_seconds) * 1000)
            page.wait_for_timeout(1500)
            body_text = _page_text(page)
            blockers = _matched_markers(body_text, _list(profile.get("blocker_markers")))
            input_count = _visible_selector_count(page, _list(profile.get("input_selectors")))
            activation_present = _present_texts(page, _list(profile.get("activate_texts")))
            clicked = _click_activation_texts(page, activation_present) if click_activation else []
            result.update(
                {
                    "status": "needs_human" if blockers else "ready",
                    "url": page.url,
                    "input_visible": input_count > 0,
                    "input_visible_count": input_count,
                    "activation_texts_present": activation_present,
                    "activation_texts_clicked": clicked,
                    "blockers": blockers,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "recovery_hint": _preflight_recovery_hint(blockers, input_count, activation_present),
                }
            )
        except Exception as exc:
            result.update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "url": getattr(page, "url", str(profile.get("url") or "")),
                    "elapsed_seconds": round(time.time() - started, 2),
                    "recovery_hint": "Open this provider manually, confirm login and mode labels, then update profile selectors if needed.",
                }
            )
        finally:
            context.close()
    return result


def open_provider_login_profiles(
    profiles: list[dict[str, Any]],
    *,
    keep_open_seconds: int = 600,
    headless: bool = False,
    timeout_seconds: int = 45,
) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local optional install
        return [_provider_result(profile, "failed", error=f"Playwright is not available: {exc}") for profile in profiles]

    results: list[dict[str, Any]] = []
    contexts: list[Any] = []
    with sync_playwright() as playwright:
        for profile in profiles:
            result = _provider_result(profile, "opening")
            result.update({"login_profile_prep": True, "keep_open_seconds": int(keep_open_seconds)})
            if not profile.get("ready"):
                result.update({"status": "missing_url", "error": "provider profile has no url"})
                results.append(result)
                continue
            try:
                browser_name = str(profile.get("browser") or "chromium")
                browser_type = getattr(playwright, browser_name)
                Path(str(profile["user_data_dir"])).mkdir(parents=True, exist_ok=True)
                context = browser_type.launch_persistent_context(
                    str(profile["user_data_dir"]),
                    headless=bool(headless),
                    viewport={"width": 1440, "height": 1000},
                    ignore_https_errors=True,
                    **_browser_launch_options(profile),
                )
                contexts.append(context)
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(str(profile["url"]), wait_until="domcontentloaded", timeout=int(timeout_seconds) * 1000)
                except Exception as exc:
                    result["navigation_error"] = str(exc)
                result.update(
                    {
                        "status": "opened",
                        "url": getattr(page, "url", str(profile.get("url") or "")),
                        "recovery_hint": "Log in manually in this browser window, solve any CAPTCHA, choose the deep research mode once if needed, then close the window.",
                    }
                )
            except Exception as exc:
                result.update({"status": "failed", "error": str(exc), "recovery_hint": "Open this provider manually or update the provider URL/profile config."})
            results.append(result)
        started = time.time()
        while contexts and time.time() - started < max(1, int(keep_open_seconds)):
            open_contexts = []
            for context in contexts:
                try:
                    if context.pages:
                        open_contexts.append(context)
                    else:
                        context.close()
                except Exception:
                    continue
            contexts = open_contexts
            if not contexts:
                break
            time.sleep(1)
        for context in contexts:
            try:
                context.close()
            except Exception:
                pass
    return results


def normalize_provider_key(provider: str) -> str:
    text = str(provider or "").lower()
    if "chatgpt" in text or "openai" in text:
        return "chatgpt"
    if "gemini" in text or "google" in text:
        return "gemini"
    if "perplex" in text:
        return "perplexity"
    if "kimi" in text or "moonshot" in text:
        return "kimi"
    if "通义" in text or "qwen" in text or "aliyun" in text:
        return "qwen"
    if "豆包" in text or "doubao" in text:
        return "doubao"
    if "秘塔" in text or "metaso" in text:
        return "metaso"
    if "阶跃" in text or "stepfun" in text:
        return "stepfun"
    if "智谱" in text or "清言" in text or "chatglm" in text or "zhipu" in text:
        return "zhipu"
    if "minimax" in text or "mini max" in text or "海螺" in text:
        return "minimax"
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug or "external"


def run_provider_browser_automation(
    profile: dict[str, Any],
    *,
    prompt: str,
    default_followup_answer: str,
    followup_wait_seconds: int = 10,
    max_wait_seconds: int = 900,
    headless: bool = False,
) -> dict[str, Any]:
    if not profile.get("ready"):
        return _provider_result(profile, "skipped", error="provider profile has no url")
    started = time.time()
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local optional install
        return _provider_result(profile, "failed", error=f"Playwright is not available: {exc}")

    provider = str(profile.get("provider") or profile.get("requested_provider") or "External researcher")
    result: dict[str, Any] = _provider_result(profile, "running")
    with sync_playwright() as playwright:
        browser_name = str(profile.get("browser") or "chromium")
        browser_type = getattr(playwright, browser_name)
        Path(str(profile["user_data_dir"])).mkdir(parents=True, exist_ok=True)
        context = browser_type.launch_persistent_context(
            str(profile["user_data_dir"]),
            headless=bool(headless),
            viewport={"width": 1440, "height": 1000},
            **_browser_launch_options(profile),
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(str(profile["url"]), wait_until="domcontentloaded", timeout=60_000)
            clicked = _click_activation_texts(page, _list(profile.get("activate_texts")))
            _fill_first(page, _list(profile.get("input_selectors")), prompt)
            submitted = _click_first(page, _list(profile.get("submit_selectors")))
            if not submitted:
                page.keyboard.press("Enter")
            followup_handled = _maybe_handle_followup(
                page,
                profile,
                default_answer=default_followup_answer,
                wait_seconds=int(followup_wait_seconds),
                timeout_error=PlaywrightTimeoutError,
            )
            report_text = _wait_for_stable_report(
                page,
                _list(profile.get("report_selectors")),
                max_wait_seconds=int(max_wait_seconds),
            )
            result.update(
                {
                    "status": "succeeded" if report_text else "needs_human",
                    "provider": provider,
                    "url": page.url,
                    "report_text": report_text,
                    "activated_texts_clicked": clicked,
                    "followup": followup_handled,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "human_review_required": True,
                }
            )
        except Exception as exc:
            result.update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "url": getattr(page, "url", str(profile.get("url") or "")),
                    "elapsed_seconds": round(time.time() - started, 2),
                    "recovery_hint": "Keep the opened browser profile logged in, then update this provider's selectors/activate_texts and rerun.",
                }
            )
        finally:
            context.close()
    return result


def render_profile_config_template(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "question_research_external_researcher_profiles.v1",
        "profiles": BUILTIN_PROVIDER_PROFILES,
        "notes": [
            "Edit url, activate_texts, and selectors when a provider changes its web UI.",
            "Use only accounts/profiles you are authorized to access.",
            "Do not store passwords, cookies, API keys, or bearer tokens in this file.",
        ],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(target), "profile_count": len(BUILTIN_PROVIDER_PROFILES)}


def _read_profile_overrides(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = data.get("profiles", data) if isinstance(data, dict) else {}
    if not isinstance(profiles, dict):
        return {}
    return {normalize_provider_key(key): value for key, value in profiles.items() if isinstance(value, dict)}


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def _provider_result(profile: dict[str, Any], status: str, *, error: str = "") -> dict[str, Any]:
    return {
        "provider": str(profile.get("provider") or profile.get("requested_provider") or "External researcher"),
        "key": str(profile.get("key") or ""),
        "status": status,
        "url": str(profile.get("url") or ""),
        "user_data_dir": str(profile.get("user_data_dir") or ""),
        "error": error,
    }


def _click_activation_texts(page: Any, texts: list[str]) -> list[str]:
    clicked: list[str] = []
    for text in texts:
        if _click_text(page, text):
            clicked.append(text)
            page.wait_for_timeout(800)
    return clicked


def _present_texts(page: Any, texts: list[str]) -> list[str]:
    present: list[str] = []
    for text in texts:
        try:
            if page.get_by_text(text, exact=True).first.count() > 0:
                present.append(text)
                continue
        except Exception:
            pass
        try:
            if page.get_by_text(text, exact=False).first.count() > 0:
                present.append(text)
        except Exception:
            continue
    return present


def _visible_selector_count(page: Any, selectors: list[str]) -> int:
    count = 0
    for selector in selectors:
        try:
            locator = page.locator(selector)
            total = locator.count()
            for index in range(min(total, 5)):
                if locator.nth(index).is_visible(timeout=500):
                    count += 1
        except Exception:
            continue
    return count


def _matched_markers(text: str, markers: list[str]) -> list[str]:
    lowered = text.lower()
    return [marker for marker in markers if marker and marker.lower() in lowered]


def _preflight_recovery_hint(blockers: list[str], input_count: int, activation_present: list[str]) -> str:
    if blockers:
        return f"Human action required before automation: {', '.join(blockers[:5])}"
    if input_count <= 0:
        return "No visible prompt input was detected; login manually or update input_selectors."
    if not activation_present:
        return "Prompt input exists, but no deep-research mode label was detected; update activate_texts or select the mode manually."
    return "Provider looks ready for a non-headless automation run."


def _click_text(page: Any, text: str) -> bool:
    candidates = [
        lambda: page.get_by_text(text, exact=True).first,
        lambda: page.get_by_text(text, exact=False).first,
        lambda: page.get_by_role("button", name=re.compile(re.escape(text), re.I)).first,
    ]
    for factory in candidates:
        try:
            locator = factory()
            if locator.count() > 0 and locator.is_visible(timeout=1_000):
                locator.click(timeout=3_000)
                return True
        except Exception:
            continue
    return False


def _click_first(page: Any, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).last
            if locator.count() > 0 and locator.is_visible(timeout=1_000):
                locator.click(timeout=3_000)
                return True
        except Exception:
            continue
    return False


def _fill_first(page: Any, selectors: list[str], value: str) -> None:
    last_error: Exception | None = None
    for selector in selectors:
        try:
            locator = page.locator(selector).last
            if locator.count() == 0 or not locator.is_visible(timeout=1_000):
                continue
            tag = locator.evaluate("el => el.tagName.toLowerCase()")
            if tag in {"textarea", "input"}:
                locator.fill(value, timeout=5_000)
            else:
                locator.click(timeout=3_000)
                page.keyboard.insert_text(value)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"no editable prompt box found; last error: {last_error}")


def _maybe_handle_followup(page: Any, profile: dict[str, Any], *, default_answer: str, wait_seconds: int, timeout_error: type[Exception]) -> dict[str, Any]:
    body_text = _page_text(page)
    markers = _list(profile.get("followup_markers"))
    likely_followup = any(marker.lower() in body_text.lower() for marker in markers if marker)
    if not likely_followup:
        return {"detected": False}
    page.wait_for_timeout(max(0, int(wait_seconds)) * 1000)
    current_input = _current_input_text(page, _list(profile.get("input_selectors")))
    if current_input.strip():
        return {"detected": True, "action": "human_input_detected"}
    try:
        _fill_first(page, _list(profile.get("input_selectors")), default_answer)
        submitted = _click_first(page, _list(profile.get("submit_selectors")))
        if not submitted:
            page.keyboard.press("Enter")
        return {"detected": True, "action": "auto_default_submitted", "wait_seconds": wait_seconds}
    except timeout_error as exc:
        return {"detected": True, "action": "failed_to_submit_default", "error": str(exc)}
    except Exception as exc:
        return {"detected": True, "action": "failed_to_submit_default", "error": str(exc)}


def _current_input_text(page: Any, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector).last
            if locator.count() == 0 or not locator.is_visible(timeout=500):
                continue
            tag = locator.evaluate("el => el.tagName.toLowerCase()")
            if tag in {"textarea", "input"}:
                return str(locator.input_value(timeout=1_000) or "")
            return str(locator.inner_text(timeout=1_000) or "")
        except Exception:
            continue
    return ""


def _wait_for_stable_report(page: Any, selectors: list[str], *, max_wait_seconds: int) -> str:
    best = ""
    stable_since = time.time()
    started = time.time()
    while time.time() - started < max(1, max_wait_seconds):
        text = _extract_report_text(page, selectors)
        if len(text) > len(best):
            best = text
            stable_since = time.time()
        if len(best) > 1000 and time.time() - stable_since >= 12:
            return best
        page.wait_for_timeout(2_000)
    return best


def _extract_report_text(page: Any, selectors: list[str]) -> str:
    best = ""
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            text = locator.last.inner_text(timeout=2_000)
            if len(text) > len(best):
                best = text
        except Exception:
            continue
    return best.strip()


def _page_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=2_000) or "")
    except Exception:
        return ""
