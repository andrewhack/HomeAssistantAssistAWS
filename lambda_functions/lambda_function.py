# -*- coding: utf-8 -*-
import warnings
import sys

if not sys.warnoptions:
    warnings.filterwarnings("ignore", category=SyntaxWarning)

import os
import re
import logging
import json
import random
import asyncio
import uuid
from urllib.parse import urlparse

import requests
import requests.exceptions
import ask_sdk_core.utils as ask_utils

from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective, ExecuteCommandsDirective, OpenUrlCommand
from ask_sdk_model.services.directive import (
    SendDirectiveRequest, Header, SpeakDirective
)
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Logger — initialized first so module-level setup code can log.
# ---------------------------------------------------------------------------
# Strict truthiness on the debug env var: bool("False") == True is a footgun.
debug = os.environ.get('debug', '').strip().lower() == 'true'
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if debug else logging.INFO)

# ---------------------------------------------------------------------------
# Localization — locale strings live in a dedicated dict, NOT in globals().
# Loading user-supplied locale files into globals() would let any line in a
# .lang file overwrite arbitrary module config (e.g. home_assistant_url).
# ---------------------------------------------------------------------------
LOCALE_STRINGS: dict = {}

# Build allowlist of locales from the shipped locale/ directory at cold start.
# Used to validate the locale field in the Alexa request envelope before it
# reaches the filesystem path.
def _build_locale_allowlist():
    try:
        return {
            f[:-len(".lang")]
            for f in os.listdir("locale")
            if f.endswith(".lang")
        }
    except OSError as e:
        logger.error("Could not enumerate locale/ directory: %s", e)
        return set()

LOCALE_ALLOWLIST = _build_locale_allowlist()
DEFAULT_LOCALE = "en-US"

def pick_random_phrase(key):
    """Pick a random phrase from a semicolon-separated locale string."""
    raw = LOCALE_STRINGS.get(key, "")
    if not raw:
        return ""
    phrases = [p.strip() for p in raw.split(";") if p.strip()]
    return random.choice(phrases) if phrases else raw

def load_config(file_name):
    """Load a `key=value` locale file into LOCALE_STRINGS (not globals)."""
    if str(file_name).endswith(".lang") and not os.path.exists(file_name):
        file_name = f"locale/{DEFAULT_LOCALE}.lang"
    try:
        with open(file_name, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or '=' not in line:
                    continue
                name, value = line.split('=', 1)
                LOCALE_STRINGS[name] = value
    except Exception as e:
        logger.error(f"Error loading file: {str(e)}")

# Initial config load
load_config(f"locale/{DEFAULT_LOCALE}.lang")

# ---------------------------------------------------------------------------
# Static module config (read from env once at cold start).
# ---------------------------------------------------------------------------
executor = ThreadPoolExecutor(max_workers=5)

home_assistant_url = os.environ.get('home_assistant_url', "").strip("/")
assist_input_entity = os.environ.get('assist_input_entity', "input_text.assistant_input")
home_assistant_agent_id = os.environ.get('home_assistant_agent_id', None)
home_assistant_language = os.environ.get('home_assistant_language', None)
home_assistant_room_recognition = str(os.environ.get('home_assistant_room_recognition', 'False')).lower()
home_assistant_kioskmode = str(os.environ.get('home_assistant_kioskmode', 'False')).lower()
ask_for_further_commands = str(os.environ.get('ask_for_further_commands', 'False')).lower()
suppress_greeting = str(os.environ.get('suppress_greeting', 'False')).lower()
enable_acknowledgment_sound = str(os.environ.get('enable_acknowledgment_sound', 'False')).lower()

# HTTP request timeouts (connect, read). Without an explicit timeout, a hung
# HA instance hangs Lambda all the way to its hard limit.
HA_HTTP_TIMEOUT = (5, 25)

# Validate the HA URL scheme at cold start. http:// would transmit the per-user
# Bearer token in cleartext — refuse to send the request later if so.
def _validate_ha_url():
    if not home_assistant_url:
        logger.error("home_assistant_url env var is not set; skill will fail at request time.")
        return False
    parsed = urlparse(home_assistant_url)
    if parsed.scheme != "https":
        logger.critical(
            "home_assistant_url must use https:// (got %r). Bearer tokens "
            "would be transmitted in cleartext; refusing to call HA.",
            home_assistant_url,
        )
        return False
    return True

_HA_URL_OK = _validate_ha_url()

# ---------------------------------------------------------------------------
# Per-request helpers — take values explicitly instead of reading globals,
# so concurrent invocations in a warm Lambda container can't leak state
# across users.
# ---------------------------------------------------------------------------

def fetch_prompt_from_ha(account_linking_token):
    """Read the state of the assist_input_entity helper from HA."""
    if not _HA_URL_OK or not account_linking_token:
        return ""
    try:
        url = f"{home_assistant_url}/api/states/{assist_input_entity}"
        headers = {
            "Authorization": "Bearer {}".format(account_linking_token),
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=HA_HTTP_TIMEOUT)
        if resp.status_code == 200:
            return resp.json().get("state", "").strip()
        else:
            logger.error(f"HA state fetch failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Error fetching prompt from HA state: {e}")
    return ""

def _resolve_locale(handler_input):
    """Validate the request locale against the allowlist; fall back to default."""
    requested = getattr(handler_input.request_envelope.request, "locale", None) or ""
    if requested in LOCALE_ALLOWLIST:
        return requested
    if requested:
        logger.info("Locale %r not in allowlist; falling back to %s", requested, DEFAULT_LOCALE)
    return DEFAULT_LOCALE

def localize(handler_input):
    """Load locale strings for the request and return the country-code suffix
    (e.g. 'DE' for de-DE) used by improve_response()."""
    locale = _resolve_locale(handler_input)
    load_config(f"locale/{locale}.lang")
    parts = locale.split("-")
    return parts[1] if len(parts) > 1 else parts[0]

def _session_attrs(handler_input):
    return handler_input.attributes_manager.session_attributes


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        user_locale = localize(handler_input)
        session = _session_attrs(handler_input)

        # Per-user Account Linking token — kept on the request, never on a global.
        account_linking_token = handler_input.request_envelope.context.system.user.access_token

        # Verify token presence (no env-var fallback — a debug fallback risks
        # all users sharing one token if accidentally enabled in prod).
        if not account_linking_token:
            logger.error("Unable to get token from Alexa Account Linking.")
            speak_output = pick_random_phrase("alexa_speak_error")
            return handler_input.response_builder.speak(speak_output).response

        # Pre-set prompt path: HA can push a question into Alexa via input_text helper.
        prompt = fetch_prompt_from_ha(account_linking_token)
        if prompt and prompt.lower() != "none":
            speech, new_conv_id = process_conversation(
                prompt, account_linking_token, user_locale,
                session.get("conversation_id"),
            )
            if new_conv_id:
                session["conversation_id"] = new_conv_id
            return handler_input.response_builder.speak(speech).ask(
                pick_random_phrase("alexa_speak_question")
            ).response

        # APL render path (Echo Show etc.) — wrapped so a render failure
        # degrades to voice-only instead of killing the whole response.
        device = handler_input.request_envelope.context.system.device
        try:
            is_apl_supported = (
                getattr(getattr(device, "supported_interfaces", None),
                        "alexa_presentation_apl", None)
                is not None
            )
        except Exception:
            is_apl_supported = False

        request_locale = getattr(handler_input.request_envelope.request, "locale", None)
        logger.info(
            "LaunchRequest: locale=%s apl_supported=%s device=%r",
            request_locale, is_apl_supported, device,
        )

        if is_apl_supported:
            try:
                render_token = str(uuid.uuid4())
                handler_input.response_builder.add_directive(
                    RenderDocumentDirective(token=render_token, document=load_template("apl_openha.json"))
                )
            except Exception as e:
                logger.warning("APL render skipped (continuing with voice-only): %s", e, exc_info=True)

        speak_output = pick_random_phrase("alexa_speak_welcome_message")

        if suppress_greeting == "true":
            return handler_input.response_builder.ask("").response
        return handler_input.response_builder.speak(speak_output).ask(speak_output).response


def send_acknowledgment_sound(handler_input, request):
    """Send a progressive response ack sound while the slow LLM call runs."""
    if not request.request_id:
        logger.warning("Cannot send acknowledgment sound: missing request_id")
        return False
    processing_msg = pick_random_phrase("alexa_speak_processing")
    if not processing_msg:
        logger.warning("Cannot send acknowledgment sound: missing alexa_speak_processing")
        return False
    try:
        directive_header = Header(request_id=request.request_id)
        speak_directive = SpeakDirective(speech=processing_msg)
        directive_request = SendDirectiveRequest(
            header=directive_header, directive=speak_directive
        )
        directive_service_client = handler_input.service_client_factory.get_directive_service()
        directive_service_client.enqueue(directive_request)
        logger.debug("Acknowledgment sound sent via progressive response")
        return True
    except Exception as e:
        logger.warning(f"Failed to send acknowledgment sound: {e}")
        return False


def run_async_in_executor(func, *args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(loop.run_in_executor(executor, func, *args))
    finally:
        loop.close()


class GptQueryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("GptQueryIntent")(handler_input)

    def handle(self, handler_input):
        user_locale = localize(handler_input)
        session = _session_attrs(handler_input)

        request = handler_input.request_envelope.request
        context = handler_input.request_envelope.context
        response_builder = handler_input.response_builder

        account_linking_token = context.system.user.access_token
        if not account_linking_token:
            logger.error("Unable to get token from Alexa Account Linking.")
            return response_builder.speak(pick_random_phrase("alexa_speak_error")).response

        query = request.intent.slots["query"].value
        logger.info(f"Query received from Alexa: {query}")

        keyword_response = keywords_exec(query, handler_input)
        if keyword_response:
            return keyword_response

        device_id = ""
        if home_assistant_room_recognition == "true":
            device_id = f". device_id: {context.system.device.device_id}"

        if enable_acknowledgment_sound == "true":
            send_acknowledgment_sound(handler_input, request)

        full_query = query + device_id
        speech, new_conv_id = run_async_in_executor(
            process_conversation,
            full_query, account_linking_token, user_locale,
            session.get("conversation_id"),
        )
        if new_conv_id:
            session["conversation_id"] = new_conv_id

        logger.debug(f"Ask for further commands enabled: {ask_for_further_commands}")
        if ask_for_further_commands == "true":
            return response_builder.speak(speech).ask(pick_random_phrase("alexa_speak_question")).response
        return response_builder.speak(speech).set_should_end_session(True).response


def keywords_exec(query, handler_input):
    """Match keyword commands (open dashboard / close skill) before LLM call."""
    open_dash = LOCALE_STRINGS.get("keywords_to_open_dashboard", "").split(";")
    if any(ko.strip().lower() in query.lower() for ko in open_dash if ko.strip()):
        logger.info("Opening Home Assistant dashboard")
        open_page(handler_input)
        return handler_input.response_builder.speak(
            LOCALE_STRINGS.get("alexa_speak_open_dashboard", "")
        ).response

    close_skill = [k.strip().lower() for k in LOCALE_STRINGS.get("keywords_to_close_skill", "").split(";") if k.strip()]
    query_words = query.lower().split()
    if len(query_words) <= 3:
        for kc in close_skill:
            if re.search(r'\b' + re.escape(kc) + r'\b', query.lower()):
                logger.info("Closing skill from keyword command")
                return CancelOrStopIntentHandler().handle(handler_input)

    return None


def process_conversation(query, account_linking_token, user_locale, conversation_id_in=None):
    """Call HA's /api/conversation/process and shape the response for Alexa.

    Returns (speech_text, new_conversation_id). new_conversation_id is None
    if HA didn't return one (or the call failed); the caller should not
    overwrite the session value with None.
    """
    if not _HA_URL_OK:
        logger.error("HA URL invalid or insecure; refusing to call.")
        return pick_random_phrase("alexa_speak_error"), None
    if not home_assistant_url:
        logger.error("Please set 'home_assistant_url' AWS Lambda Functions environment variable.")
        return pick_random_phrase("alexa_speak_error"), None

    try:
        headers = {
            "Authorization": "Bearer {}".format(account_linking_token),
            "Content-Type": "application/json",
        }
        data = {"text": replace_words(query)}
        if home_assistant_language:
            data["language"] = home_assistant_language
        if home_assistant_agent_id:
            data["agent_id"] = home_assistant_agent_id
        if conversation_id_in:
            data["conversation_id"] = conversation_id_in

        ha_api_url = "{}/api/conversation/process".format(home_assistant_url)
        logger.debug(f"HA request url: {ha_api_url}")
        logger.debug(f"HA request data: {data}")

        response = requests.post(ha_api_url, headers=headers, json=data, timeout=HA_HTTP_TIMEOUT)

        logger.debug(f"HA response status: {response.status_code}")
        logger.debug(f"HA response data: {response.text}")

        contenttype = response.headers.get('Content-Type', '')
        logger.debug(f"Content-Type: {contenttype}")

        new_conv_id = None
        if contenttype == "application/json":
            response_data = response.json()
            speech = None
            is_ssml = False

            if response.status_code == 200 and "response" in response_data:
                new_conv_id = response_data.get("conversation_id")
                response_type = response_data["response"]["response_type"]

                if response_type in ("action_done", "query_answer"):
                    speech, is_ssml = extract_speech(response_data["response"]["speech"])
                    if speech and "device_id:" in speech:
                        speech = speech.split("device_id:")[0].strip()
                elif response_type == "error":
                    speech, is_ssml = extract_speech(response_data["response"]["speech"])
                    logger.error(f"Error code: {response_data['response']['data']['code']}")
                else:
                    speech = pick_random_phrase("alexa_speak_error")
                    is_ssml = False

            if not speech:
                if "message" in response_data:
                    message = response_data["message"]
                    logger.error(f"Empty speech: {message}")
                    return improve_response(
                        f"{LOCALE_STRINGS.get('alexa_speak_error', '')} {message}",
                        user_locale,
                    ), new_conv_id
                logger.error(f"Empty speech: {response_data}")
                return pick_random_phrase("alexa_speak_error"), new_conv_id

            if is_ssml:
                logger.debug("Returning SSML response")
                return speech, new_conv_id
            logger.debug("Returning plain text response with improvements")
            return improve_response(speech, user_locale), new_conv_id

        elif contenttype == "text/html" and response.status_code >= 400:
            errorMatch = re.search(r'<title>(.*?)</title>', response.text, re.IGNORECASE)
            if errorMatch:
                title = errorMatch.group(1)
                logger.error(f"HTTP error {response.status_code} ({title}): Unable to connect to your Home Assistant server")
            else:
                logger.error(f"HTTP error {response.status_code}: Unable to connect to your Home Assistant server. \n {response.text}")
            return pick_random_phrase("alexa_speak_error"), None
        elif contenttype == "text/plain" and response.status_code >= 400:
            logger.error(f"Error processing request: {response.text}")
            return pick_random_phrase("alexa_speak_error"), None
        else:
            logger.error(f"Error processing request: {response.text}")
            return pick_random_phrase("alexa_speak_error"), None

    except requests.exceptions.Timeout as te:
        logger.error(f"Timeout when communicating with Home Assistant: {str(te)}", exc_info=True)
        return LOCALE_STRINGS.get("alexa_speak_timeout", pick_random_phrase("alexa_speak_error")), None
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}", exc_info=True)
        return pick_random_phrase("alexa_speak_error"), None


def extract_speech(speech_data):
    """Extract speech from HA response, preferring SSML over plain text.
    Returns (speech_text, is_ssml)."""
    if "ssml" in speech_data and speech_data["ssml"].get("speech"):
        speech = speech_data["ssml"]["speech"]
        logger.debug(f"Using SSML response: {speech}")
        return speech, True
    if "plain" in speech_data and speech_data["plain"].get("speech"):
        speech = speech_data["plain"]["speech"]
        logger.debug(f"Using plain text response: {speech}")
        return speech, False
    return None, False


def replace_words(query):
    """Pre-rewrite known mis-transcriptions in the query before calling HA."""
    return query.replace('4.º', 'quarto')


def improve_response(speech, user_locale):
    """Shape plain-text speech for Alexa TTS. SSML responses bypass this."""
    speech = speech.replace(':\n\n', '').replace('\n\n', '. ').replace('\n', ',').replace('-', '').replace('_', ' ')
    if user_locale == "DE":
        speech = re.sub(r'(\d+)\.(\d{1,3})(?!\d)', r'\1,\2', speech)
    speech = re.sub(r'[^A-Za-z0-9çÇáàâãäéèêíïóôõöúüñÁÀÂÃÄÉÈÊÍÏÓÔÕÖÚÜÑ\sß.,!?°]', '', speech)
    return speech


def load_template(filepath):
    """Load and dynamically populate an APL template."""
    with open(filepath, encoding='utf-8') as f:
        template = json.load(f)

    if filepath == 'apl_openha.json':
        items = template['mainTemplate']['items'][0]['items']
        items[2]['text'] = LOCALE_STRINGS.get("echo_screen_welcome_text", "")
        items[3]['text'] = LOCALE_STRINGS.get("echo_screen_click_text", "")
        items[4]['onPress']['source'] = get_hadash_url()
        items[4]['item']['text'] = LOCALE_STRINGS.get("echo_screen_button_text", "")

    return template


def open_page(handler_input):
    """Open the HA dashboard in Silk via APL OpenUrlCommand."""
    device = handler_input.request_envelope.context.system.device
    try:
        apl_ok = (
            getattr(getattr(device, "supported_interfaces", None),
                    "alexa_presentation_apl", None)
            is not None
        )
    except Exception:
        apl_ok = False
    if not apl_ok:
        return

    token = str(uuid.uuid4())
    try:
        handler_input.response_builder.add_directive(
            RenderDocumentDirective(token=token, document=load_template("apl_empty.json"))
        )
        handler_input.response_builder.add_directive(
            ExecuteCommandsDirective(
                token=token,
                commands=[OpenUrlCommand(source=get_hadash_url())]
            )
        )
    except Exception as e:
        logger.warning("open_page APL directives skipped: %s", e, exc_info=True)


def get_hadash_url():
    """Build the HA dashboard URL for the APL Open button."""
    ha_dashboard_url = home_assistant_url
    ha_dashboard_url += "/{}".format(os.environ.get("home_assistant_dashboard", "lovelace"))
    if home_assistant_kioskmode == "true":
        ha_dashboard_url += '?kiosk'
    logger.debug(f"ha_dashboard_url: {ha_dashboard_url}")
    return ha_dashboard_url


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        speak_output = pick_random_phrase("alexa_speak_help")
        return handler_input.response_builder.speak(speak_output).ask(speak_output).response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input)

    def handle(self, handler_input):
        speak_output = pick_random_phrase("alexa_speak_exit") or LOCALE_STRINGS.get("alexa_speak_exit", "")
        return handler_input.response_builder.speak(speak_output).set_should_end_session(True).response


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CanFulfillIntentRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("CanFulfillIntentRequest")(handler_input)

    def handle(self, handler_input):
        localize(handler_input)
        intent_name = handler_input.request_envelope.request.intent.name if handler_input.request_envelope.request.intent else None
        if intent_name == "GptQueryIntent":
            return handler_input.response_builder.can_fulfill("YES").add_can_fulfill_intent("YES").response
        return handler_input.response_builder.can_fulfill("NO").add_can_fulfill_intent("NO").response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(exception, exc_info=True)
        speak_output = pick_random_phrase("alexa_speak_error")
        return handler_input.response_builder.speak(speak_output).ask(speak_output).response


sb = CustomSkillBuilder(api_client=DefaultApiClient())
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(GptQueryIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_request_handler(CanFulfillIntentRequestHandler())
sb.add_exception_handler(CatchAllExceptionHandler())
lambda_handler = sb.lambda_handler()
