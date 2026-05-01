# TODO — HomeAssistantAssistAWS

Action items derived from the security & quality review of [`lambda_functions/lambda_function.py`](lambda_functions/lambda_function.py).
Priority levels: 🔴 critical · 🟠 high · 🟡 medium · 🟢 low.

## Status (2026-05-01)

| Item | Status | Branch / commit |
|------|--------|-----------------|
| #1 globals leak across users | ✅ Resolved | `fix/echo-show-defensive-launch` (partial: `is_apl_supported`, `apl_document_token`) + `fix/critical-and-high-security` `ef3e83e` (rest) |
| #2 `load_config` writes to `globals()` | ✅ Resolved | `fix/critical-and-high-security` `ef3e83e` |
| #3 unvalidated locale field | ✅ Resolved | `ef3e83e` |
| #4 missing HA POST timeout | ✅ Resolved | `ef3e83e` |
| #5 HTTPS not enforced | ✅ Resolved | `ef3e83e` |
| #6 `debug` truthiness bug | ✅ Resolved | `ef3e83e` (also removed env-var token fallback) |
| #13 logger used before init | ✅ Resolved (incidental) | `ef3e83e` |
| #15 `globals().get(keywords_*)` `None.split` crash | ✅ Resolved (incidental) | `ef3e83e` |
| #7–#12, #14, #16–#21 | Open | — |

Branches not yet merged into `main`. Code below still cites pre-fix line numbers.

---

## Security

### 🔴 1. Stop sharing user state via module globals ✅ Resolved (`6fe241a` + `ef3e83e`)
- **Where:** [lambda_function.py:67-81](lambda_functions/lambda_function.py)
- **Problem:** `account_linking_token`, `conversation_id`, `last_interaction_date`, `is_apl_supported`, `user_locale` are module-level globals. AWS Lambda containers are reused across invocations and across different end users → User A's bearer token / conversation context can leak into User B's request when invocations interleave (provisioned concurrency, the `ThreadPoolExecutor` path, or simply a warm container handling a different user next).
- **Fix:**
  - Pass `account_linking_token` as an explicit argument to `process_conversation` and `fetch_prompt_from_ha`.
  - Persist `conversation_id` in `handler_input.attributes_manager.session_attributes` (per Alexa session).
  - Persist `last_interaction_date` in `persistent_attributes` keyed by `userId` (or just drop the "first run of the day" greeting if not worth the dependency).
  - Compute `is_apl_supported` per request from `handler_input.request_envelope.context.system.device`.

### 🔴 2. `load_config` can overwrite arbitrary module globals ✅ Resolved (`ef3e83e`)
- **Where:** [lambda_function.py:39-52](lambda_functions/lambda_function.py)
- **Problem:** Every `name=value` line in a `.lang` file is written into `globals()[name]`. A line like `home_assistant_url=http://attacker.example` in a locale file silently overrides runtime config. No allowlist.
- **Fix:** Load into a dedicated dict (`LOCALE_STRINGS: dict[str, str] = {}`); replace every `globals().get("alexa_speak_*")` with `LOCALE_STRINGS.get(...)`.

### 🟠 3. Validate the `locale` request field ✅ Resolved (`ef3e83e`)
- **Where:** [lambda_function.py:106](lambda_functions/lambda_function.py)
- **Problem:** `load_config(f"locale/{locale}.lang")` uses an untrusted request field as part of a file path. Today Alexa restricts the value, but the code shouldn't depend on that.
- **Fix:** Allowlist the locales actually shipped in `lambda_functions/locale/`; fall back to `en-US` on mismatch.

### 🟠 4. Add timeout to the main HA POST ✅ Resolved (`ef3e83e`)
- **Where:** [lambda_function.py:309](lambda_functions/lambda_function.py)
- **Problem:** No timeout on `requests.post(...)`. A slow/hung HA hangs Lambda until its hard limit.
- **Fix:** `requests.post(ha_api_url, headers=headers, json=data, timeout=(5, 25))`. The existing `Timeout` exception handler will then actually fire.

### 🟠 5. Enforce HTTPS on `home_assistant_url` ✅ Resolved (`ef3e83e`)
- **Where:** [lambda_function.py:72](lambda_functions/lambda_function.py)
- **Problem:** A misconfigured `http://` URL exposes the Bearer token in cleartext.
- **Fix:** Validate scheme at cold start; refuse to start (or log error and return generic failure) if not `https://`.

### 🟠 6. `debug` env flag has the `bool("False") == True` bug ✅ Resolved (`ef3e83e`)
- **Where:** [lambda_function.py:58](lambda_functions/lambda_function.py)
- **Problem:** `bool(os.environ.get('debug', False))` is `True` for any non-empty string, including the literal `"False"`. Debug mode also bypasses Alexa account linking ([:124](lambda_functions/lambda_function.py)) → if accidentally on in prod, every user shares the env-var token.
- **Fix:** `debug = os.environ.get('debug', '').strip().lower() == 'true'` (matches the pattern used for the other flags). Consider removing the env-var token fallback entirely — or gate it behind a separate explicit flag.

### 🟡 7. Don't log full HA payloads at debug
- **Where:** [lambda_function.py:307-312](lambda_functions/lambda_function.py)
- **Problem:** `logger.debug(f"HA response data: {response.text}")` logs every HA response to CloudWatch. May contain room layout, presence info, sensor readings.
- **Fix:** Log only metadata (status, content-type, length); redact bodies in debug, or move body logs behind a separate `verbose_debug` flag off by default.

### 🟡 8. Remove dead/buggy `int(response.status_code, 0)` calls
- **Where:** [lambda_function.py:355,365](lambda_functions/lambda_function.py)
- **Problem:** `response.status_code` is already `int`; `int(int_value, base)` raises `TypeError`. Those branches never execute as intended; everything falls to the generic else.
- **Fix:** Drop the wrapper: `if contenttype == "text/html" and response.status_code >= 400:`.

### 🟡 9. Modernize GitHub Actions release workflow
- **Where:** [.github/workflows/release.yml](.github/workflows/release.yml)
- **Problem:** Uses archived `actions/create-release@v1` and `actions/upload-release-asset@v1` (deprecated 2021).
- **Fix:** Migrate to `softprops/action-gh-release@v2`. Pin third-party actions to a SHA. Set `permissions: contents: read` at workflow level, narrow to `write` only on the release job.

### 🟡 10. Pin and monitor dependencies
- **Where:** [lambda_functions/requirements.txt](lambda_functions/requirements.txt)
- **Problem:** `requests>=2.26.0` unbounded; `ask-sdk-core==1.19.0` is years out of date.
- **Fix:** Pin exact versions. Enable Dependabot. Plan an `ask-sdk-core` upgrade after adding tests.

### 🟢 11. Audit the giant `.gitignore`
- **Where:** [.gitignore](.gitignore) (147 KB)
- **Action:** Confirm everything in there is intentional; trim anything irrelevant.

---

## Code quality

### 🟡 12. Fake-async scaffolding adds complexity for no benefit
- **Where:** [lambda_function.py:204-210](lambda_functions/lambda_function.py)
- **Problem:** `run_async_in_executor` spins up a new asyncio event loop per call to wrap a synchronous `requests` call. The README claim of "async calls" isn't delivered. Lambda runs single-request-per-container anyway.
- **Fix:** Either remove (call `process_conversation` directly) or convert to real async with `aiohttp`.

### 🟡 13. Logger used before initialization ✅ Resolved (`ef3e83e`, incidental)
- **Where:** initial [`load_config("locale/en-US.lang")`](lambda_functions/lambda_function.py) at line 55 runs before `logger` is created at line 59.
- **Fix:** Move logger init to top of file (right after imports).

### 🟡 14. Defensive access on HA response shape
- **Where:** [lambda_function.py:323,334](lambda_functions/lambda_function.py)
- **Problem:** `response_data["response"]["response_type"]` and `["data"]["code"]` crash on unexpected shapes.
- **Fix:** `.get()` chains with sensible fallbacks.

### 🟡 15. `globals().get("keywords_*")` returns `None` → `.split` crashes ✅ Resolved (`ef3e83e`, incidental)
- **Where:** [lambda_function.py:260,267](lambda_functions/lambda_function.py)
- **Fix:** Use `LOCALE_STRINGS.get(key, "")` (after #2) before splitting.

### 🟡 16. Hardcoded Brazilian timezone
- **Where:** [lambda_function.py:152](lambda_functions/lambda_function.py)
- **Problem:** `timezone(timedelta(hours=-3))` for "first run of the day" — wrong for everyone outside UTC-3.
- **Fix:** Use `timezone.utc`, or derive from the Alexa request's `timestamp`/`device.timezone`.

### 🟡 17. URL building uses string concatenation
- **Where:** [:89](lambda_functions/lambda_function.py), [:305](lambda_functions/lambda_function.py), [:462-466](lambda_functions/lambda_function.py)
- **Problem:** `?kiosk` blindly appended; can produce `...?lovelace?kiosk` if the dashboard path already has a query string.
- **Fix:** `urllib.parse.urljoin` + `urlencode`.

### 🟡 18. No tests
- **Action:** Add `pytest` with at least:
  - Happy-path `process_conversation` against a mocked `requests`.
  - `extract_speech` with SSML/plain/missing.
  - `improve_response` decimal-comma conversion for `de-DE`.
  - `keywords_exec` for open-dashboard / close-skill matches and non-matches.

### 🟢 19. Replace `globals()` config pattern with a typed config object
- **Action:** Move env-var parsing into a `pydantic.BaseSettings` or `@dataclass`. Validate at cold start; fail fast on missing/invalid values.

### 🟢 20. CI lint/format/test gate
- **Action:** Add `ruff check`, `ruff format --check`, `pytest` steps to the release workflow before the zip step.

### 🟢 21. APL token reuse ✅ Resolved (`6fe241a`, incidental)
- **Where:** [lambda_function.py:73](lambda_functions/lambda_function.py)
- **Problem:** `apl_document_token = str(uuid.uuid4())` generated once at import, reused for every user/session. Cosmetic, not a security issue.
- **Fix:** Generate per-handler call.

---

## Remaining order to attack (after #1–#6 land)

1. #8 — kill the dead `int(status_code, 0)` branches (one-line fix).
2. #7 — redact HA payloads from debug logs.
3. #14 — defensive `.get()` chains on HA response shape.
4. #16 — drop the hardcoded Brazilian timezone (or remove the daily-greeting feature, which `ef3e83e` already did).
5. #17 — `urljoin` + `urlencode` for URL building.
6. #9 + #10 — modernize GH Actions release workflow + pin deps.
7. #18 — add minimal `pytest` suite.
8. #12, #19 — drop fake-async, replace `globals()` config pattern with a typed config object.
9. #20 — CI lint/format/test gate.
10. #11 — audit the giant `.gitignore`.
