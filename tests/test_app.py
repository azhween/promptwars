import pytest
from app import app, tasks, messages

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        tasks.clear()
        messages.clear()
        yield client

def test_create_task(client):
    response = client.post('/api/tasks', json={
        'title': 'Test Task',
        'description': 'Description here',
        'priority': 'high',
        'status': 'To Do',
        'due_date': '2026-10-10',
        'is_blocked': True
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['title'] == 'Test Task'
    assert data['status'] == 'To Do'
    assert data['priority'] == 'high'
    assert data['due_date'] == '2026-10-10'
    assert data['is_blocked'] is True

def test_create_task_invalid_priority(client):
    response = client.post('/api/tasks', json={
        'title': 'Test Task',
        'priority': 'super-high'
    })
    assert response.status_code == 400
    data = response.get_json()
    assert 'error' in data

def test_update_task_fields(client):
    # First create
    res1 = client.post('/api/tasks', json={'title': 'To Update', 'is_blocked': False})
    task_id = res1.get_json()['id']
    
    # Update status and blocked state
    res2 = client.put(f'/api/tasks/{task_id}', json={
        'status': 'In Progress',
        'is_blocked': True,
        'due_date': '2026-11-11'
    })
    assert res2.status_code == 200
    data = res2.get_json()
    assert data['status'] == 'In Progress'
    assert data['is_blocked'] is True
    assert data['due_date'] == '2026-11-11'

def test_delete_task(client):
    res1 = client.post('/api/tasks', json={'title': 'To Delete'})
    task_id = res1.get_json()['id']
    
    res2 = client.delete(f'/api/tasks/{task_id}')
    assert res2.status_code == 204
    
    res3 = client.get('/api/tasks')
    assert len(res3.get_json()) == 0

def test_create_message(client):
    response = client.post('/api/messages', json={
        'author': 'Alice',
        'text': 'Hello FlowMate'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['author'] == 'Alice'
    assert data['text'] == 'Hello FlowMate'

def test_ai_standup_missing_text(client):
    response = client.post('/api/ai/standup', json={
        'author': 'Alice'
    })
    assert response.status_code == 400

def test_ai_plan_sprint_missing_goal(client):
    response = client.post('/api/ai/plan_sprint', json={})
    assert response.status_code == 400
