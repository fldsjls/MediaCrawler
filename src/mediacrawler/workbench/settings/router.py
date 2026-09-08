"""Settings entry points. The caller supplies the Repository, avoiding service imports."""
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from mediacrawler.workbench.persistence.repository import Repository
from mediacrawler.workbench.settings import BrowserSettings, BrowserSettingsPatch, SettingsRegistry
from .defaults import read_defaults, save_defaults


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

    @router.get('/defaults')
    async def defaults():
        return read_defaults(owner().repo)

    @router.patch('/defaults')
    async def patch_defaults(patch: dict):
        try:
            return save_defaults(owner().repo, patch)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.get('/tools')
    async def tools():
        from mediacrawler.workbench.downloads.engines import inspect_tools
        return await inspect_tools(read_defaults(owner().repo))

    @router.get('/browser', response_model=BrowserSettings)
    async def read_browser():
        return owner().read_browser()

    @router.patch('/browser', response_model=BrowserSettings)
    async def patch_browser(patch: BrowserSettingsPatch):
        return owner().patch_browser(patch)

    return router
