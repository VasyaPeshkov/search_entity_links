from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EntityType = Literal["person", "organization", "unknown"]
ResultStatus = Literal["success", "unresolved", "failed"]


class EntityInput(BaseModel):
    entity_id: str
    name: str
    entity_type: EntityType = "unknown"


class EntityLink(BaseModel):
    platform: str
    url: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    source: str = "unknown"
    source_urls: list[str] = Field(default_factory=list)


class GeminiBatchItem(BaseModel):
    entity_id: str
    canonical_name: str | None = None
    ambiguous: bool = False
    ambiguity_notes: list[str] = Field(default_factory=list)
    aliases_used: list[str] = Field(default_factory=list)
    links: list[EntityLink] = Field(default_factory=list)


class GeminiBatchPayload(BaseModel):
    results: list[GeminiBatchItem] = Field(default_factory=list)


class GeminiBatchSearchResult(BaseModel):
    items: list[GeminiBatchItem] = Field(default_factory=list)
    search_used: bool = False
    search_queries: list[str] = Field(default_factory=list)
    grounding_sources: list[str] = Field(default_factory=list)


class EntityLinksResult(BaseModel):
    entity_id: str | None = None
    input_name: str
    canonical_name: str | None = None
    entity_type: EntityType

    ambiguous: bool = False
    ambiguity_notes: list[str] = Field(default_factory=list)
    aliases_used: list[str] = Field(default_factory=list)

    links: list[EntityLink] = Field(default_factory=list)

    search_used: bool = False
    search_queries: list[str] = Field(default_factory=list)
    grounding_sources: list[str] = Field(default_factory=list)

    minjust_record_ids: list[str] = Field(default_factory=list)
    minjust_registry_numbers: list[int] = Field(default_factory=list)
    minjust_registry_names: list[str] = Field(default_factory=list)
    minjust_match_score: float | None = None
    minjust_has_active_record: bool | None = None

    resolution_sources: list[str] = Field(default_factory=list)
    needs_human_review: bool = False


class MinjustRegistryRecord(BaseModel):
    record_id: str
    registry_number: int | None = None
    display_name: str
    normalized_name: str
    token_key: str
    search_names: list[str] = Field(default_factory=list)
    entity_type: EntityType
    category: str = ""
    resources_raw: str = ""
    links: list[EntityLink] = Field(default_factory=list)
    date_included: str = ""
    date_excluded: str = ""
    inn: str = ""
    ogrn: str = ""
    birth_date: str = ""
    participants_raw: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return not bool(self.date_excluded.strip())


class StoredResult(BaseModel):
    cache_key: str
    input_name: str
    entity_type: EntityType
    status: ResultStatus
    result: EntityLinksResult | None = None
    attempts: int = 0
    last_error: str | None = None


class LLMUsage(BaseModel):
    usage_date: str
    model: str
    requests: int = 0
    entities_sent: int = 0
    successful_entities: int = 0
    failed_requests: int = 0
