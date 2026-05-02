import pytest
from app import app, tasks, messages, sprint_risk_cache

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        # Clear global state
        tasks.clear()
        messages.clear()
        sprint_risk_cache['timestamp'] = 0
        sprint_risk_cache['data'] = None
        yield client

# 1. test_health_check — GET /health returns 200
def test_health_check(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ok'

# 2. test_get_tasks_empty — GET /api/tasks returns list
def test_get_tasks_empty(client):
    response = client.get('/api/tasks')
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)
    assert len(response.get_json()) == 0

# 3. test_create_task_success — POST /api/tasks with valid data returns 201
def test_create_task_success(client):
    response = client.post('/api/tasks', json={
        'title': 'Test Task',
        'description': 'Test Description',
        'priority': 'high',
        'status': 'To Do'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['title'] == 'Test Task'
    assert data['id'] in tasks

# 4. test_create_task_missing_title — POST /api/tasks without title returns 400
def test_create_task_missing_title(client):
    response = client.post('/api/tasks', json={
        'description': 'Test Description',
        'priority': 'high'
    })
    assert response.status_code == 400
    assert 'error' in response.get_json()

# 5. test_create_task_title_too_long — POST /api/tasks with 201 char title returns 400
def test_create_task_title_too_long(client):
    response = client.post('/api/tasks', json={
        'title': 'a' * 201,
        'description': 'Test'
    })
    assert response.status_code == 400
    assert 'error' in response.get_json()

# 6. test_update_task_success — PATCH /api/tasks/{id} updates status
def test_update_task_success(client):
    res1 = client.post('/api/tasks', json={'title': 'To Update'})
    task_id = res1.get_json()['id']
    
    res2 = client.patch(f'/api/tasks/{task_id}', json={'status': 'In Progress'})
    assert res2.status_code == 200
    assert res2.get_json()['status'] == 'In Progress'

# 7. test_update_task_not_found — PATCH /api/tasks/fakeid returns 404
def test_update_task_not_found(client):
    response = client.patch('/api/tasks/fakeid', json={'status': 'Done'})
    assert response.status_code == 404

# 8. test_delete_task_success — DELETE /api/tasks/{id} returns 200
def test_delete_task_success(client):
    res1 = client.post('/api/tasks', json={'title': 'To Delete'})
    task_id = res1.get_json()['id']
    
    res2 = client.delete(f'/api/tasks/{task_id}')
    assert res2.status_code == 200
    assert task_id not in tasks

# 9. test_delete_task_not_found — DELETE /api/tasks/fakeid returns 404
def test_delete_task_not_found(client):
    response = client.delete('/api/tasks/fakeid')
    assert response.status_code == 404

# 10. test_get_team — GET /api/team returns members list
def test_get_team(client):
    client.post('/api/tasks', json={'title': 'Task 1', 'assignee': 'Alice'})
    client.post('/api/tasks', json={'title': 'Task 2', 'assignee': 'Bob'})
    client.post('/api/tasks', json={'title': 'Task 3', 'assignee': 'Alice'})
    
    response = client.get('/api/team')
    assert response.status_code == 200
    team = response.get_json()
    assert isinstance(team, list)
    assert len(team) == 2
    assert 'Alice' in team
    assert 'Bob' in team

# 11. test_post_message_success — POST /api/messages with valid data returns 201
def test_post_message_success(client):
    response = client.post('/api/messages', json={
        'author': 'Alice',
        'text': 'Hello team'
    })
    assert response.status_code == 201
    assert response.get_json()['author'] == 'Alice'

# 12. test_post_message_missing_fields — POST /api/messages without text returns 400
def test_post_message_missing_fields(client):
    response = client.post('/api/messages', json={
        'author': 'Alice'
    })
    assert response.status_code == 400
    assert 'error' in response.get_json()
