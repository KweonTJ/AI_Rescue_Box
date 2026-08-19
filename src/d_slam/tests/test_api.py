import importlib.util, pytest
pytestmark=pytest.mark.skipif(importlib.util.find_spec('fastapi') is None,reason='fastapi not installed')
def test_fastapi_health():
    from fastapi.testclient import TestClient
    from jetson_app.api import create_app
    client=TestClient(create_app()); response=client.get('/api/v1/health'); assert response.status_code==200 and response.json()['stage']=='stage01'
