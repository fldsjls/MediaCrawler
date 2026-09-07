"""Settings entry points. The caller supplies the Repository, avoiding service imports."""
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from .repository import Repository
from .settings import BrowserSettings, BrowserSettingsPatch, SettingsRegistry


def create_settings_router(repository_provider: Callable[[], Repository]) -> APIRouter:
    router = APIRouter(prefix='/settings', tags=['settings'])

    def owner():
        repository = repository_provider()
        if repository is None:
            raise HTTPException(503, '工作台尚未启动')
        return SettingsRegistry(repository)

    @router.get('/sections')
    async def sections():
        return SettingsRegistry.sections()

    @router.get('/browser', response_model=BrowserSettings)
    async def read_browser():
        return owner().read_browser()

    @router.patch('/browser', response_model=BrowserSettings)
    async def patch_browser(patch: BrowserSettingsPatch):
        return owner().patch_browser(patch)

    return router
