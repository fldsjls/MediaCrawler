"""External infrastructure tests require an explicit pytest -m external run."""
import pytest


def pytest_collection_modifyitems(items):
    external = {'test_redis_cache.py', 'test_proxy_ip_pool.py', 'test_mongodb_integration.py'}
    for item in items:
        if item.path.name in external:
            item.add_marker(pytest.mark.external)
