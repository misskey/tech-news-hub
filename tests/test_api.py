from datetime import datetime, timezone
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import NewsItem

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'news.db'))
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-pass')
    monkeypatch.setenv('SCHEDULER_ENABLED', '0')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    with TestClient(create_app()) as client:
        client.app.state.db.upsert_items([NewsItem(source='hackernews', external_id=str(i), title=f'Rust news {i}', url=f'https://example.com/{i}', published_at=datetime.now(timezone.utc)) for i in range(25)])
        yield client

def test_pagination_search_and_detail(client):
    data = client.get('/api/v1/news?page_size=10').json()
    assert len(data['items']) == 10 and data['has_more']
    assert data['total'] == 25
    second = client.get('/api/v1/news?page_size=10&page=2').json()
    assert not {x['id'] for x in data['items']} & {x['id'] for x in second['items']}
    assert client.get('/api/v1/news?q=missing').json()['items'] == []
    item = client.get('/api/v1/news/' + str(data['items'][0]['id'])).json()
    assert item['short'] and item['long']
    assert 'model' not in item and 'extra' not in item

def test_api_private_and_missing(client):
    assert client.get('/api/v1/news/99999').status_code == 404
    client.app.state.settings = replace(client.app.state.settings, protect_site=True)
    assert client.get('/api/v1/news').status_code == 401
    assert client.get('/api/v1/news/1').status_code == 401

@pytest.mark.parametrize('query', ['page=0', 'page_size=1000', 'window=all', 'q=' + 'a'*101])
def test_validation(client, query):
    assert client.get('/api/v1/news?' + query).status_code == 422

def test_hidden_content_is_not_exposed(client):
    prefs = client.app.state.db.get_preferences()
    prefs.blocked_keywords = ['Rust']
    client.app.state.db.save_preferences(prefs)
    assert client.get('/api/v1/news').json()['items'] == []
    assert client.get('/api/v1/news/1').status_code == 404
