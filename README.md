# Home Assistant Assist Alexa Skill (AWS Hosted)

Alexa Skill that integrates Home Assistant Assist or your preferred Generative AI.

---

_Note: This project is still in a very early alpha phase, this means not all features are fully functional yet and
features or usage can change significantly between releases._

### Table of Contents

1. [About](#about)
2. [Features](#features)
3. [Installation](#installation)
4. [Supported languages](#supported-languages)

## About

This is an Alexa skill model that integrates Home Assistant Assist or your preferred Generative AI through the conversation API and also allows you to open your favorite dashboard on Echo Show devices.

**Note: The difference between this **(AWS Hosted)** and the [Alexa Hosted](https://github.com/fabianosan/HomeAssistantAssist) version is that this skill does not have the `8 seconds` limitation, uses Alexa Account Linking and have async calls _(Enabling the use of more complex `and slow` AI models)_** 

## Features

- Voice command:
    - Interact with [Home Assistant Assist](https://www.home-assistant.io/voice_control)
    - Interact with [Open AI](https://www.home-assistant.io/integrations/openai_conversation) integration
    - Interact with [Extended Open AI](https://github.com/jekalmin/extended_openai_conversation) integration
    - Interact with [Google Generative AI](https://www.home-assistant.io/integrations/google_generative_ai_conversation) integration
- Open Home Assistant dashboard:
    - Say 'open home assistant' or 'open dashboard' to open your prefered dashboard in Home Assistant.
    - Or click on the sceen to open.
- Other:
    - Multi-language support _(see [Supported languages](#supported-languages))_

If you have a feature idea, open a issue to suggest your idea for implementation.

## Installation

For instructions how to set this skill up refer to the [installation](doc/en/INSTALLATION.md) or [update](doc/en/UPDATE.md) page.

## Supported languages

The skill has support for the following languages:

- Portuguese (Brazil)
- Portuguese (Portugal)
- English (United States)
- English (England)
- English (Canada)
- French
- Italian
- Spanish
- German
- Polish (Poland)
- Russian (Russia)

Note: If your language is not supported, please open an `issue` attaching your own version of the file [en-US.lang](lambda_functions/locale/en-US.lang).

---



# Home Assistant Assist Alexa Skill (AWS Hosted)

Skill Alexa que integra o Home Assistant Assist ou sua IA Generativa preferida.

---

_Nota: Este projeto ainda está em uma fase alfa muito inicial, o que significa que nem todos os recursos estão totalmente funcionais e os recursos ou o uso podem mudar significativamente entre as versões._

### Índice

1. [Sobre](#sobre)
2. [Recursos](#recursos)
3. [Instalação](#instalação)
4. [Idiomas suportados](#idiomas-suportados)

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
    - Diga 'abrir home assistant' ou 'abrir painel' para abrir seu painel preferido no Home Assistant.
    - Ou clique na tela para abrir.
- Outros:
    - Suporte a vários idiomas (veja [Idiomas suportados](#idiomas-suportados))

Se você tiver uma ideia de recurso, abra um issue para sugerir sua ideia para implementação.

## Instalação

Para obter instruções sobre como configurar essa skill, consulte a página de [instalação](doc/pt/INSTALLATION.md) ou [atualização](doc/pt/UPDATE.md).

## Idiomas suportados

A skill tem suporte para os seguintes idiomas:

- Português (Brasil)
- Português (Portugal)
- Inglês (Estados Unidos)
- Inglês (Inglaterra)
- Inglês (Canadá)
- Francês
- Italiano
- Espanhol
- Alemão
- Polonês (Polônia)
- Russo (Rússia)