# Interactive Communication: HA-Driven Conversations

Make Home Assistant a more active participant in Alexa conversations — push
questions into the skill, keep conversation context across invocations, and
combine with Alexa Media Player (AMP) for a near-proactive experience.

This document covers what the skill supports today (after the `improved`
branch lands), how to configure it, and complete HA scenarios you can copy
and adapt.

---

## 1. What's possible — and the architectural ceiling

**A custom Alexa skill cannot speak unprompted.** Amazon's platform is
strictly reactive: the user says the wake word, Alexa routes to a skill, the
skill responds. There's no API for a skill to push speech into a device.

Three facilities make HA-driven conversations work despite that:

1. **Alexa Media Player** (HA custom integration) gets Echo to *say*
   something proactively, by reverse-engineering Amazon's apps. **It does
   not invoke this skill** — it just makes the device speak.

2. **`fetch_prompt_from_ha`** (this skill) lets HA *stage a question* in an
   `input_text` helper. When the user invokes the skill (manually or after
   AMP nudges them), the staged question becomes the user's input
   automatically.

3. **Persistent `conversation_id`** (this skill, optional) keeps the HA
   conversation agent's memory alive between invocations, so each new
   "Alexa, ask smart assist" is a continuation, not a fresh start.

The combination yields the user-facing flow:

```
HA event fires
   ↓
HA writes question to input_text.assistant_input
   ↓
HA calls notify.alexa_media → Echo says "I have a question for you"
   ↓
User: "Alexa, ask smart assist"
   ↓
This skill fetches the staged question, sends to HA Conversation API,
   speaks HA's response, keeps session open for follow-up
   ↓
User answers; HA agent responds with full context preserved
```

---

## 2. Setup

### 2.1 Lambda environment variables

| Variable | Required | Default | What it does |
|---|---|---|---|
| `home_assistant_url` | yes | — | Base HTTPS URL of your HA instance. |
| `assist_input_entity` | no | `input_text.assistant_input` | Entity polled for staged prompts. |
| `ask_for_further_commands` | no | `False` | Set `true` to keep the session open after each turn. **Required for mid-session prompt re-poll.** |
| `persistence_table_name` | no | — | DynamoDB table name for cross-session persistence. Leave unset to disable. |
| `conversation_continuity_minutes` | no | `5` | Resume the prior `conversation_id` only if the user invokes within this window. |
| `home_assistant_agent_id` | no | — | Specific HA conversation agent (e.g. an OpenAI / Gemini agent) — usually needed for memory across turns. |

### 2.2 Home Assistant helper

Add a single `input_text` helper. Either via UI (Settings → Devices &
Services → Helpers → Create Helper → Text) or in `configuration.yaml`:

```yaml
input_text:
  assistant_input:
    name: Alexa staged prompt
    initial: "none"
    max: 255
```

The skill reads this entity at the start of every Alexa session and after
every turn (when `ask_for_further_commands=true`). It resets it back to
`"none"` after consuming, so the same question never replays.

### 2.3 DynamoDB table for persistence (optional)

Skip this section if you don't need cross-session conversation memory.

Schema (matches the `ask-sdk-dynamodb-persistence-adapter` defaults so a
future migration is trivial):

```bash
aws dynamodb create-table \
  --table-name AssistantPersistence \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

IAM — attach to the Lambda execution role:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
    "Resource": "arn:aws:dynamodb:*:*:table/AssistantPersistence"
  }]
}
```

Then set the Lambda env var `persistence_table_name=AssistantPersistence`
and redeploy.

### 2.4 Alexa Media Player — already installed

Since you already have AMP, you have `notify.alexa_media` available. Quick
sanity check:

```yaml
service: notify.alexa_media
data:
  message: "Hello from Home Assistant"
  target: media_player.kitchen_echo
  data:
    type: tts
```

`type: tts` makes the Echo speak the message immediately, regardless of
volume / DnD settings (within AMP's caveats). `type: announce` plays a
chime first.

---

## 3. The four moving parts in this skill (what changed in `improved`)

| Mechanism | Where in code | What it does |
|---|---|---|
| `fetch_prompt_from_ha` | [`lambda_function.py`](../../lambda_functions/lambda_function.py) | Reads `assist_input_entity` state; non-empty / non-`"none"` becomes the user's input. |
| Mid-session re-poll | `GptQueryIntentHandler.handle` | After each user turn (when `ask_for_further_commands=true`), polls the prompt entity again; appends any fresh prompt to the spoken response with a connective phrase. |
| `clear_prompt_in_ha` | top of file | After consuming a prompt, calls `input_text.set_value` to reset to `"none"`. Best-effort; HA can also clear it itself in the same automation. |
| Persistent `conversation_id` | `_persistent_load` / `_persistent_save` | When `persistence_table_name` is set, `conversation_id` is stored per Alexa user-id with a timestamp; resumed only within `conversation_continuity_minutes`. |
| `started_from_ha_prompt` session flag | `LaunchRequestHandler.handle` | Set to `True` when the launch was triggered by an HA-staged prompt. Available to future code as `session.get("started_from_ha_prompt")`. |

---

## 4. Scenarios

### 4.1 Doorbell question

> Goal: when someone rings the doorbell while the user is at home, ask
> them via Echo whether to unlock the door.

```yaml
# automation.yaml
automation:
  - alias: "Doorbell — ask user via Alexa"
    trigger:
      - platform: state
        entity_id: binary_sensor.front_doorbell
        to: "on"
    condition:
      # Only ask if someone is home
      - condition: state
        entity_id: group.family
        state: "home"
    action:
      # 1. Stage the question for the skill
      - service: input_text.set_value
        data:
          entity_id: input_text.assistant_input
          value: >
            Someone is at the front door.
            Should I unlock it for them?

      # 2. Get the user's attention via AMP
      - service: notify.alexa_media
        data:
          message: >
            <audio src="soundbank://soundlibrary/doorbells/general/doorbell"/>
            Someone is at the front door.
            Say: ask smart assist for details.
          target:
            - media_player.kitchen_echo
            - media_player.living_room_echo
          data:
            type: tts

      # Optional: time out the staged prompt after 2 minutes
      - delay: "00:02:00"
      - condition: template
        value_template: >
          {{ states('input_text.assistant_input') != 'none' }}
      - service: input_text.set_value
        data:
          entity_id: input_text.assistant_input
          value: "none"
```

**User experience:**
1. Doorbell rings → Echo plays a chime then speaks "Someone is at the front door. Say: ask smart assist for details."
2. User: *"Alexa, ask smart assist."*
3. Skill fetches the staged prompt, sends to HA conversation agent.
4. HA agent (assuming it's an LLM agent with knowledge of the home) replies: *"Someone is at the front door. Should I unlock it?"*
5. User: *"Yes, unlock it."*
6. Same conversation continues — agent has context, calls `lock.unlock` on the front door, replies *"Done. The front door is unlocked."*

For step 6 to work, the HA agent needs the conversation to flow as one
context. This is where persistent `conversation_id` matters: turn 4 and
turn 6 share the same `conversation_id`, so the LLM agent has memory of
"this is about unlocking the front door".

### 4.2 Dryer-finished reminder

> Goal: when the dryer finishes, nudge the user; if they invoke the
> skill, hand them a follow-up question.

```yaml
automation:
  - alias: "Dryer finished"
    trigger:
      - platform: state
        entity_id: sensor.dryer_state
        to: "complete"
        for: "00:01:00"
    action:
      - service: input_text.set_value
        data:
          entity_id: input_text.assistant_input
          value: "The dryer just finished. Want me to set a reminder to fold the laundry?"
      - service: notify.alexa_media
        data:
          message: "The dryer is done."
          target: media_player.kitchen_echo
          data:
            type: tts
```

User can ignore the AMP announcement entirely. If they *do* invoke the
skill — for any reason, even hours later (within
`conversation_continuity_minutes`) — they hear the staged question instead
of the welcome message.

### 4.3 Multi-step decision with conversation memory

> Goal: HA detects an ambiguous condition and asks the user a question;
> the user's answer feeds further HA logic.

```yaml
automation:
  - alias: "Vacation mode prompt"
    trigger:
      - platform: state
        entity_id: device_tracker.user_phone
        to: "not_home"
        for: "12:00:00"
    action:
      - service: input_text.set_value
        data:
          entity_id: input_text.assistant_input
          value: >
            You've been away for over 12 hours. Should I switch the house
            to vacation mode? That turns down the heating and sets the
            lights on a randomized schedule.
      - service: notify.alexa_media
        data:
          message: "I have a question about vacation mode."
          target: media_player.bedroom_echo
          data:
            type: tts
```

User invokes the skill, hears the question, replies *"Yes, switch to
vacation mode."* The HA conversation agent (configured with knowledge of
your scripts) calls `script.activate_vacation_mode` and confirms.

**Why persistent `conversation_id` matters here:** if the user replies *"What does that change exactly?"* before deciding, the HA agent answers, and the user's eventual *"OK, go ahead"* still resolves correctly because the conversation context survives across turns.

### 4.4 Mid-session prompt injection

> Goal: while the user is already talking to the skill, HA fires an
> event and wants to interrupt with a follow-up.

This requires `ask_for_further_commands=true` and is **fully automatic** —
no special HA automation needed beyond writing to `input_text.assistant_input`.

Walk-through:
1. User: *"Alexa, ask smart assist."*
2. Skill: *"Hi, how can I help?"*
3. User: *"Turn on the kitchen lights."*
4. Skill: *"Done."* — at this moment, while the response is being computed, an HA automation writes to the prompt entity: *"By the way, the dryer just finished."*
5. Skill (after delivering "Done"): polls the entity, finds new content, appends with a connective: *"Done. Also, the dryer just finished."*
6. User: *"OK, remind me in 30 minutes."*
7. Conversation continues normally with full HA context.

Add the connective to your locale file (`lambda_functions/locale/en-US.lang`):

```
alexa_speak_also=Also,;By the way,;Oh, and:;On another note:
```

The skill picks one at random. Without it, a default `"Also,"` is used.

---

## 5. Configuration matrix — which features need what

| Feature | `ask_for_further_commands` | `persistence_table_name` | DynamoDB | AMP | HA helper |
|---|:-:|:-:|:-:|:-:|:-:|
| HA stages a question (4.1, 4.2) | optional | optional | optional | recommended | **required** |
| Multi-turn within one session | **`true`** | optional | optional | — | — |
| Conversation memory across sessions (4.3) | optional | **set** | **required** | optional | — |
| Mid-session prompt injection (4.4) | **`true`** | optional | optional | optional | **required** |
| Echo proactively speaks | — | — | — | **required** | — |

---

## 6. Debugging

### CloudWatch log lines you'll see

- `LaunchRequest: locale=... apl_supported=... device=...` — confirms the request reached Lambda.
- `Persistence enabled: table=AssistantPersistence continuity=5min` — set at cold start when persistence is configured.
- `Resumed conversation_id from persistent store (within continuity window).` — confirms cross-session resume worked.
- `HA request url=... text_len=... has_conv_id=...` — DEBUG only; metadata of the call to HA's conversation API.
- `clear_prompt_in_ha failed: ...` — clearing the prompt entity didn't work; the same prompt may replay on the next invocation. HA can clear it itself as a safety net.

### Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Skill greets normally, never picks up the staged prompt | `assist_input_entity` mismatch, or value is the literal `"none"` | Check the entity name matches the env var; check current state in HA. |
| Conversation forgets context between invocations | Persistence not configured, or invocation outside continuity window | Set `persistence_table_name`; widen `conversation_continuity_minutes`; ensure the HA agent itself supports memory (Assist's local agent has limited memory). |
| Same question replays every time | `clear_prompt_in_ha` failing | Check IAM / token; clear from the HA automation as a fallback (`input_text.set_value` to `"none"` after the AMP announce). |
| AMP works but the staged prompt is ignored | The user invoked the skill *before* HA finished writing the prompt | Stage the prompt **before** calling `notify.alexa_media`, as the scenarios above show. |
| `notify.alexa_media` works for normal cases but not from this automation | AMP rate-limiting or DnD on the target device | Echo's per-account "Do Not Disturb" overrides AMP's `type: tts` for some message types — check Alexa app settings for the device. |

---

## 7. What this skill still cannot do

- **Truly proactive speech** — only AMP makes Echo speak unprompted.
- **Bidirectional notifications without AMP** — without an AMP-equivalent, the user must invoke the skill manually.
- **Cross-device continuity** — `conversation_id` is per Alexa user-id, but the HA agent's behavior on different devices in the same household depends on the HA-side agent.
- **Long-running async tasks** — the skill responds within one Lambda invocation; if HA takes >25s, the skill returns the timeout phrase. Tune `HA_HTTP_TIMEOUT` in code if your agent is slow.

---

## 8. Quick-start checklist

1. Add `input_text.assistant_input` helper in HA. Set initial value to `"none"`.
2. Set Lambda env vars:
   - `ask_for_further_commands=true`
   - `home_assistant_agent_id=<your-LLM-agent>` (recommended)
3. *(Optional, recommended for memory)* Create `AssistantPersistence` DynamoDB table, attach IAM, set `persistence_table_name`.
4. *(Optional)* Add `alexa_speak_also=Also,;By the way,` to your locale file.
5. Deploy.
6. Test with the doorbell scenario (4.1) — easiest to validate end-to-end.
