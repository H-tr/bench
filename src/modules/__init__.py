from src.modules.base import BaseModule
from src.modules.papers import PapersModule
from src.modules.intelligence import IntelligenceModule
from src.modules.news import NewsModule
from src.modules.assistant import AssistantModule
from src.modules.digest import DigestModule

ALL_MODULES: dict[str, type[BaseModule]] = {
    "papers": PapersModule,
    "intelligence": IntelligenceModule,
    "news": NewsModule,
    "assistant": AssistantModule,
    "digest": DigestModule,
}

__all__ = ["BaseModule", "ALL_MODULES"]
