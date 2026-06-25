from __future__ import annotations

import json

from pydantic import ValidationError

from ..config import AppConfig
from ..exceptions import (
    InvalidModelResponse,
    SearchGroundingUnavailable,
)
from ..models import (
    EntityInput,
    GeminiBatchPayload,
    GeminiBatchSearchResult,
)
from ..utils.json_utils import extract_json_object
from ..utils.retry import call_with_retry
from .grounding import extract_grounding_info
from .rate_limiter import (
    PersistentLLMBudget,
    SlidingWindowRateLimiter,
)


class GeminiBatchSearch:
    def __init__(
        self,
        config: AppConfig,
        rate_limiter: SlidingWindowRateLimiter,
        budget: PersistentLLMBudget,
    ):
        # Ленивый импорт позволяет пользоваться режимом LLM_ENABLED=false
        # даже без установленного google-genai.
        from google import genai
        from google.genai import types

        self.config = config
        self.types = types
        self.rate_limiter = rate_limiter
        self.budget = budget
        self.client = genai.Client(
            api_key=config.gemini_api_key,
        )

    def search_batch(
        self,
        entities: list[EntityInput],
    ) -> GeminiBatchSearchResult:
        if not entities:
            return GeminiBatchSearchResult()

        if len(entities) > self.config.llm_batch_size:
            raise ValueError(
                "Размер пакета превышает LLM_BATCH_SIZE."
            )

        return call_with_retry(
            lambda: self._search_once(entities),
            max_attempts=self.config.llm_max_attempts,
            base_delay_seconds=(
                self.config.llm_retry_base_delay_seconds
            ),
        )

    def _search_once(
        self,
        entities: list[EntityInput],
    ) -> GeminiBatchSearchResult:
        self.rate_limiter.acquire()
        usage_date = self.budget.reserve(len(entities))

        try:
            response = self.client.models.generate_content(
                model=self.config.gemini_model,
                contents=self._build_prompt(entities),
                config=self.types.GenerateContentConfig(
                    system_instruction=(
                        "You are a careful OSINT verifier. "
                        "Use Google Search. Never invent URLs. "
                        "Keep results for different entity_id values "
                        "strictly separated. Return only valid JSON."
                    ),
                    tools=[
                        self.types.Tool(
                            google_search=self.types.GoogleSearch()
                        )
                    ],
                    temperature=self.config.llm_temperature,
                    max_output_tokens=(
                        self.config.llm_max_output_tokens
                    ),
                ),
            )

            grounding = extract_grounding_info(response)

            if (
                self.config.llm_require_grounding
                and not grounding.search_used
            ):
                raise SearchGroundingUnavailable(
                    "Gemini вернула пакет без технических "
                    "признаков Google Search."
                )

            if not response.text:
                raise InvalidModelResponse(
                    "Gemini вернула пустой пакетный ответ."
                )

            raw = extract_json_object(response.text)

            try:
                payload = GeminiBatchPayload.model_validate(raw)
            except ValidationError as exc:
                raise InvalidModelResponse(
                    "Пакетный ответ Gemini не соответствует схеме:\n"
                    f"{exc}"
                ) from exc

            allowed_ids = {
                entity.entity_id
                for entity in entities
            }
            seen_ids: set[str] = set()
            clean_items = []

            for item in payload.results:
                if item.entity_id not in allowed_ids:
                    continue
                if item.entity_id in seen_ids:
                    continue

                seen_ids.add(item.entity_id)

                for link in item.links:
                    link.source = "gemini_google_search_batch"

                clean_items.append(item)

            result = GeminiBatchSearchResult(
                items=clean_items,
                search_used=grounding.search_used,
                search_queries=grounding.search_queries,
                grounding_sources=grounding.source_urls,
            )

        except Exception:
            self.budget.complete(
                usage_date=usage_date,
                successful_entities=0,
                failed=True,
            )
            raise

        self.budget.complete(
            usage_date=usage_date,
            successful_entities=len(result.items),
            failed=False,
        )
        return result

    @staticmethod
    def _build_prompt(
        entities: list[EntityInput],
    ) -> str:
        entity_data = [
            {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "entity_type": entity.entity_type,
            }
            for entity in entities
        ]

        input_json = json.dumps(
            entity_data,
            ensure_ascii=False,
            indent=2,
        )

        return f"""
Use Google Search to find official websites and official social media
profiles for every entity in the input array.

Input entities:
{input_json}

Process every entity independently. Preserve each entity_id exactly.
The results array must contain exactly one object for every input entity,
in the same order. If nothing reliable is found, return that entity with
an empty links array. Never omit an entity.

Search useful name variants:
- people: full name, reversed full name, name without patronymic,
  Latin transliteration and confirmed public pseudonyms;
- organizations: full and short names, abbreviations, Russian and
  English variants.

Find official websites and official Telegram, Instagram, Facebook,
X/Twitter, YouTube, VK, LinkedIn, TikTok, OK, Threads, Boosty,
Patreon and similar entity-owned profiles.

Rules:
1. Do not invent or autocomplete URLs.
2. Do not mix links between entities.
3. Do not return articles, news pages, individual posts, status pages,
   videos, hashtags, search pages, mirrors or fan pages.
4. If namesakes cannot be separated reliably, set ambiguous=true.
5. Return no more than 12 links per entity.
6. Use confidence from 0 to 1 conservatively.
7. source_urls must contain pages supporting the ownership conclusion.
8. Return only one JSON object, without Markdown or explanation.

Required JSON shape:
{{
  "results": [
    {{
      "entity_id": "exact input entity_id",
      "canonical_name": "string or null",
      "ambiguous": false,
      "ambiguity_notes": [],
      "aliases_used": [],
      "links": [
        {{
          "platform": "website",
          "url": "https://example.com",
          "confidence": 0.90,
          "evidence": "Why the resource belongs to this entity",
          "source": "gemini_google_search_batch",
          "source_urls": ["https://supporting-page.example"]
        }}
      ]
    }}
  ]
}}
""".strip()
