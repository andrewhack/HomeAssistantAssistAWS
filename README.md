# Home Assistant Assist Alexa Skill (AWS Hosted)

Alexa Skill that integrates Home Assistant Assist or your preferred Generative AI via the conversation API and also allows you to open your favorite dashboard on Echo Show.

---

> **About this fork.** This repository diverges from the upstream
> `fabianosan/HomeAssistantAssistAWS` with a security review pass and HA-driven
> interactive conversation features. See [What's different in this fork](#whats-different-in-this-fork)
> below for the behavioral changes existing users should know about, and
> [`doc/en/ARCHITECTURE.md`](doc/en/ARCHITECTURE.md) /
> [`doc/en/INTERACTIVE_HA.md`](doc/en/INTERACTIVE_HA.md) /
> [`TODO.md`](TODO.md) for the technical details.

_Note: This project is still in a very early alpha phase, this means not all features are fully functional yet and
features or usage can change significantly between releases._

### Table of Contents

1. [About](#about)
2. [What's different in this fork](#whats-different-in-this-fork)
3. [Features](#features)
4. [Configuration (environment variables)](#configuration-environment-variables)
5. [Documentation](#documentation)
6. [Installation](#installation)
7. [How to use](#how-to-use)
8. [Supported languages](#supported-languages)

## About

This is an Alexa skill model that integrates Home Assistant Assist or your preferred Generative AI through the conversation API and also allows you to open your favorite dashboard on Echo Show devices.

**Note: The difference between this **(AWS Hosted)** and the [Alexa Hosted](https://github.com/fabianosan/HomeAssistantAssist) version is that this skill does not have the `8 seconds` limitation, uses Alexa Account Linking and have async calls _(Enabling the use of more complex `and slow` AI models)_**

## What's different in this fork

### Security & robustness fixes
- **Per-user state isolation.** Conversation state, locale, and the Account Linking token are no longer module globals — they could leak across users in warm Lambda containers in the upstream version.
- **`load_config` writes to a dedicated dict**, not Python `globals()`. A line in a `.lang` file can no longer overwrite arbitrary runtime config.
- **Locale field is allowlisted** against the shipped `locale/*.lang` files; falls back to `en-US` on mismatch.
- **HTTP timeout** added to the main HA call (`(5, 25)` connect/read).
- **HTTPS enforced** on `home_assistant_url` — `http://` URLs are refused at request time so the Bearer token never travels in cleartext.
- **`debug` env var fixed.** The string `"False"` no longer enables debug mode (previously `bool("False") == True` did, silently turning on a debug-only token fallback). The fallback was also removed.
- **Defensive APL handling** for Echo Show: render failures degrade to voice-only instead of killing the whole `LaunchRequest`. Per-render APL token avoids cross-session state confusion. INFO-level diagnostic logged at `LaunchRequest` entry to make debugging device-specific issues easy in CloudWatch.
- **Debug logs no longer dump HA payloads** (room layout, presence, sensor readings) to CloudWatch — metadata only.
- **Pinned `requests==2.32.3`**, modernized `release.yml` (replaced archived `actions/create-release@v1` + `actions/upload-release-asset@v1` with `softprops/action-gh-release@v2`, narrowed permissions). The `.gitignore` shrank from 1801 enumerated lines to ~48 patterns.

### New features — HA-driven interactive conversations
- **Cross-session conversation memory** (optional). Set `persistence_table_name` to a DynamoDB table and the HA conversation agent's `conversation_id` is preserved across "Alexa, ask &lt;skill&gt;" invocations. Continuity window is configurable.
- **Mid-session prompt injection.** When `ask_for_further_commands=true`, the skill re-polls the staged-prompt entity after each turn — HA can inject follow-up questions into an ongoing conversation. The skill speaks them with a connective ("Also, ...", "By the way, ...").
- **Auto-clear staged prompts** so the same question never replays.
- **`started_from_ha_prompt`** session flag for downstream code.

### Behavioral changes existing users should notice
- **Welcome phrase plays each session.** The "first run of the day" greeting feature was removed — it was already broken across users in warm containers and re-implementing it correctly required persistent storage. Set `suppress_greeting=true` if you want silence.
- **`http://` URLs are refused.** If your `home_assistant_url` was http, you'll see a CRITICAL log line at cold start and the skill returns the error phrase. Switch to https.
- **`home_assistant_token` env-var fallback removed.** Previously, when `debug=true` and Account Linking was missing, the Lambda would use this env var as the bearer token — risky if accidentally enabled in prod. Account Linking is now the only path.

## Features

- Voice command:
    - Interact with [Home Assistant Assist](https://www.home-assistant.io/voice_control)
    - Interact with [Open AI](https://www.home-assistant.io/integrations/openai_conversation) integration
    - Interact with [Extended Open AI](https://github.com/jekalmin/extended_openai_conversation) integration
    - Interact with [Google Generative AI](https://www.home-assistant.io/integrations/google_generative_ai_conversation) integration
- Open Home Assistant dashboard:
    - Open your prefered Home Assistant dashboard in Echo Show screen.
    - Click on the Echo Show sceen to open your dashboard.

- Supports SSML in Intent Scripts

- Others:
    - Start a conversation with prompt from Home Assistant (thanks to [t07que](https://github.com/t07que))
    - **Mid-session prompt injection** — HA can interrupt an ongoing conversation _(this fork)_
    - **Cross-session conversation memory** via DynamoDB _(this fork, optional)_
    - Multi-language support _(see [Supported languages](#supported-languages))_

If you have a feature idea, open a issue to suggest your idea for implementation.

## Configuration (environment variables)

Set on the Lambda function. All flags are case-insensitive strings; truthy is the literal `"true"`.

### Required
| Variable | Purpose |
|---|---|
| `home_assistant_url` | Base **HTTPS** URL of your Home Assistant instance. Trailing slash optional. http:// is refused. |

### Conversation behavior
| Variable | Default | Purpose |
|---|---|---|
| `home_assistant_agent_id` | — | Specific HA conversation agent (e.g. an OpenAI / Gemini agent). Recommended for memory across turns. |
| `home_assistant_language` | — | Forwarded as `language` to `/api/conversation/process`. |
| `ask_for_further_commands` | `False` | Keep the session open after each turn. Required for mid-session prompt re-poll. |
| `suppress_greeting` | `False` | Don't speak the welcome message on `LaunchRequest`. |
| `enable_acknowledgment_sound` | `False` | Send a progressive "one moment" while a slow LLM agent thinks. |
| `home_assistant_room_recognition` | `False` | Append `device_id: …` to the query for HA-side room awareness. |

### HA-driven interactive features _(this fork)_
| Variable | Default | Purpose |
|---|---|---|
| `assist_input_entity` | `input_text.assistant_input` | Entity polled for staged HA prompts. |
| `persistence_table_name` | — | DynamoDB table name for cross-session conversation memory. Leave unset to disable. See [`doc/en/INTERACTIVE_HA.md`](doc/en/INTERACTIVE_HA.md) §2.3 for the schema and IAM policy. |
| `conversation_continuity_minutes` | `5` | Resume previous `conversation_id` only if the user invokes within this window. |

### APL dashboard (Echo Show)
| Variable | Default | Purpose |
|---|---|---|
| `home_assistant_dashboard` | `lovelace` | Path appended for the "Open HA" button. |
| `home_assistant_kioskmode` | `False` | Append `?kiosk` to the dashboard URL. |

### Debug
| Variable | Default | Purpose |
|---|---|---|
| `debug` | `false` | Verbose logging. Must be the literal `"true"` (case-insensitive) — `"False"` no longer enables it. |

## Documentation

- [`doc/en/INSTALLATION.md`](doc/en/INSTALLATION.md) — Setting up the skill from scratch.
- [`doc/en/UPDATE.md`](doc/en/UPDATE.md) — Updating an existing deployment.
- [`doc/en/ARCHITECTURE.md`](doc/en/ARCHITECTURE.md) — _(this fork)_ End-to-end internals with Mermaid diagrams of the request flow, handler dispatch, localization, APL pipeline, and CI release flow.
- [`doc/en/INTERACTIVE_HA.md`](doc/en/INTERACTIVE_HA.md) — _(this fork)_ HA-driven conversations: setup with Alexa Media Player, full HA YAML scenarios (doorbell, dryer reminder, vacation prompt, mid-session injection), debugging guide.
- [`TODO.md`](TODO.md) — Security & quality review backlog with status per item.

## Installation

For instructions how to set this skill up refer to the [installation](doc/en/INSTALLATION.md) or [update](doc/en/UPDATE.md) page.

## How to use

- Say `Alexa, open home smart` (or your defined skill invoication name):
    - Turn on the kitchen lights.
    - Open home assistant.
    
- Or say `Alexa, ask smart home to turn on kitchen lights` or `Alexa, ask smart home to open home assistant`:

## Supported languages

The skill has support for the following languages:

- German (Germany)
- English (Australia)
- English (Canada)
- English (England)
- English (United States)
- Dutch (Netherlands)
- Spanish (Spain)
- Spanish (Mexico)
- Spanish (United States)
- French (Canada)
- French (France)
- Italian (Italy)
- Polish (Poland)
- Portuguese (Brazil)
- Portuguese (Portugal)
- Russian (Russia)
- Slovak (Slovakia)

Note: If your language is not supported, please open an `issue` attaching your own version of the file [en-US.lang](lambda_functions/locale/en-US.lang).

---



# Home Assistant Assist Alexa Skill (AWS Hosted)

Skill Alexa que integra o Home Assistant Assist ou sua IA Generativa preferida via a API de conversação e também permite abrir seu painel favorito no Echo Show

---

_Nota: Este projeto ainda está em uma fase alfa muito inicial, o que significa que nem todos os recursos estão totalmente funcionais e os recursos ou o uso podem mudar significativamente entre as versões._

### Índice

1. [Sobre](#sobre)
2. [Recursos](#recursos)
3. [Instalação](#instalação)
4. [Como usar](#como-usar)
5. [Idiomas suportados](#idiomas-suportados)

## Sobre

Este é um modelo de skill Alexa que integra o Home Assistant Assist ou sua IA Generativa preferida através da API de conversação e também permite abrir seu painel favorito em dispositivos Echo Show.

**Observação: a diferença entre esta versão **(hospedada na AWS)** e a versão [hospedada na Alexa](https://github.com/fabianosan/HomeAssistantAssist) é que esta habilidade não tem a limitação de `8 segundos`, usa o Alexa Account Linking e tem chamadas assíncronas _(permitindo o uso de modelos de IA `e lentos` mais complexos)_**

## Recursos

- Comando de voz:
    - Interagir com o [Home Assistant Assist](https://www.home-assistant.io/voice_control)
    - Interagir com a integração [Open AI](https://www.home-assistant.io/integrations/openai_conversation)
    - Interagir com a integração [Extended Open AI](https://github.com/jekalmin/extended_openai_conversation)
    - Interagir com a integração [Google Generative AI](https://www.home-assistant.io/integrations/google_generative_ai_conversation)
- Abrir painel do Home Assistant:
    - Abra seu dashboard preferido do Home Assistant na tela do Echo Show.
    - Clique na tela do Echo Show para abrir seu dashboard.
- Outros:
    - Iniciar uma conversa com a Alexa de um prompt do Home Assistant (agradecimento ao [t07que](https://github.com/t07que))
    - Suporte a vários idiomas (veja [Idiomas suportados](#idiomas-suportados))

Se você tiver uma ideia de recurso, abra um issue para sugerir sua ideia para implementação.

## Instalação

Para obter instruções sobre como configurar essa skill, consulte a página de [instalação](doc/pt/INSTALLATION.md) ou [atualização](doc/pt/UPDATE.md).

## Como usar

- Diga `Alexa, abrir casa inteligente` (ou o nome de invocação definido para a skill):
    - Acenda as luzes da cozinha.
    - Abra o home assistant.
    
- Ou diga `Alexa, peça para casa inteligente acender as luzes da cozinha` ou `Alexa, peça para casa inteligente abrir o Home Assistant`

## Idiomas suportados

A skill tem suporte para os seguintes idiomas:

- Alemão (Alemanha)
- Inglês (Austrália)
- Inglês (Canadá)
- Inglês (Inglaterra)
- Inglês (Estados Unidos)
- Espanhol (Espanha)
- Espanhol (México)
- Espanhol (Estados Unidos)
- Francês (Canadá)
- Francês (França)
- Italiano (Itália)
- Holandês (Holanda)
- Polonês (Polônia)
- Português (Brasil)
- Português (Portugal)
- Russo (Rússia)
- Eslovaco (Eslováquia)

