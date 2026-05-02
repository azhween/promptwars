import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from google import genai

app = Flask(__name__, static_folder='static', static_url_path='')

# In-memory data store
tasks = []
messages = []

# Valid columns/statuses
VALID_STATUSES = ['To Do', 'In Progress', 'Done']
VALID_PRIORITIES = ['high', 'medium', 'low']

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(tasks)

@app.route('/api/tasks', methods=['POST'])
def create_task():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    priority = data.get('priority', 'low').lower()
    assignee = data.get('assignee', '').strip()
    status = data.get('status', 'To Do')

    if not title:
        return jsonify({'error': 'Title is required'}), 400
    
    if priority not in VALID_PRIORITIES:
        return jsonify({'error': 'Invalid priority level'}), 400

    if status not in VALID_STATUSES:
        return jsonify({'error': 'Invalid status'}), 400

    new_task = {
        'id': str(uuid.uuid4()),
        'title': title,
        'description': description,
        'priority': priority,
        'assignee': assignee,
        'status': status,
        'created_at': datetime.utcnow().isoformat()
    }
    tasks.append(new_task)
    return jsonify(new_task), 201

@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    task_idx = next((i for i, t in enumerate(tasks) if t['id'] == task_id), None)
    if task_idx is None:
        return jsonify({'error': 'Task not found'}), 404

    task = tasks[task_idx]
    
    # Update fields if provided
    if 'title' in data:
        title = data['title'].strip()
        if not title:
            return jsonify({'error': 'Title cannot be empty'}), 400
        task['title'] = title
    
    if 'description' in data:
        task['description'] = data['description'].strip()
        
    if 'priority' in data:
        priority = data['priority'].lower()
        if priority not in VALID_PRIORITIES:
            return jsonify({'error': 'Invalid priority level'}), 400
        task['priority'] = priority
        
    if 'assignee' in data:
        task['assignee'] = data['assignee'].strip()
        
    if 'status' in data:
        status = data['status']
        if status not in VALID_STATUSES:
            return jsonify({'error': 'Invalid status'}), 400
        task['status'] = status

    return jsonify(task), 200

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    global tasks
    initial_length = len(tasks)
    tasks = [t for t in tasks if t['id'] != task_id]
    
    if len(tasks) == initial_length:
        return jsonify({'error': 'Task not found'}), 404
        
    return '', 204

@app.route('/api/messages', methods=['GET'])
def get_messages():
    return jsonify(messages)

@app.route('/api/messages', methods=['POST'])
def create_message():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    author = data.get('author', '').strip()
    text = data.get('text', '').strip()
    
    if not author:
        return jsonify({'error': 'Author name is required'}), 400
    if not text:
        return jsonify({'error': 'Message text is required'}), 400
        
    new_msg = {
        'id': str(uuid.uuid4()),
        'author': author,
        'text': text,
        'created_at': datetime.utcnow().isoformat()
    }
    messages.append(new_msg)
    return jsonify(new_msg), 201

@app.route('/api/summarize', methods=['POST'])
def summarize_tasks():
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI Summarizer is not configured (GEMINI_API_KEY missing)'}), 503

    if not tasks:
        return jsonify({'summary': 'There are no active tasks to summarize.'}), 200

    prompt = "Summarize the following current tasks and suggest what the team should prioritize next based on priorities and statuses:\n\n"
    for t in tasks:
        prompt += f"- {t['title']} (Priority: {t['priority']}, Status: {t['status']}, Assignee: {t.get('assignee', 'Unassigned')})\n  Description: {t.get('description', 'N/A')}\n\n"

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        summary = response.text
        return jsonify({'summary': summary}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to generate summary: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
