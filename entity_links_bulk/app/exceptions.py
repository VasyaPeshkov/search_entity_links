class EntityLinksError(RuntimeError):
    """Базовая ошибка приложения."""


class InvalidModelResponse(EntityLinksError):
    """Модель вернула пустой или невалидный ответ."""


class SearchGroundingUnavailable(EntityLinksError):
    """Не удалось подтвердить использование Google Search."""


class UnsafeURL(EntityLinksError):
    """URL запрещён для crawler."""


class LLMQuotaExceeded(EntityLinksError):
    """Исчерпан суточный или локальный лимит LLM-вызовов."""
