import pytest
from app import app, tasks, messages

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        # Clear data before each test
        tasks.clear()
        messages.clear()
        yield client

def test_create_task(client):
    response = client.post('/api/tasks', json={
        'title': 'Test Task',
        'description': 'Description here',
        'priority': 'high',
        'status': 'To Do'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['title'] == 'Test Task'
    assert data['status'] == 'To Do'
    assert data['priority'] == 'high'

def test_create_task_invalid_priority(client):
    response = client.post('/api/tasks', json={
        'title': 'Test Task',
        'priority': 'super-high'
    })
    assert response.status_code == 400
    data = response.get_json()
    assert 'error' in data

def test_update_task(client):
    # First create
    res1 = client.post('/api/tasks', json={'title': 'To Update'})
    task_id = res1.get_json()['id']
    
    # Update status
    res2 = client.put(f'/api/tasks/{task_id}', json={'status': 'In Progress'})
    assert res2.status_code == 200
    assert res2.get_json()['status'] == 'In Progress'

def test_delete_task(client):
    # First create
    res1 = client.post('/api/tasks', json={'title': 'To Delete'})
    task_id = res1.get_json()['id']
    
    # Delete
    res2 = client.delete(f'/api/tasks/{task_id}')
    assert res2.status_code == 204
    
    # Verify
    res3 = client.get('/api/tasks')
    assert len(res3.get_json()) == 0

def test_create_message(client):
    response = client.post('/api/messages', json={
        'author': 'Alice',
        'text': 'Hello world'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['author'] == 'Alice'
    assert data['text'] == 'Hello world'
