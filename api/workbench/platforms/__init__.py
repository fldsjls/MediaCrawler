"""Website definitions and declarative templates; execution stays in adapters/workers."""

from .catalog import PLATFORMS, PLATFORM_TYPES, TEMPLATES
from .registry import PlatformRegistry

__all__ = ['PLATFORMS', 'PLATFORM_TYPES', 'TEMPLATES', 'PlatformRegistry']
