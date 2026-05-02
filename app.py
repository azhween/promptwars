import os
import uuid
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from google import genai
from google.genai import types

app = Flask(__name__, static_folder='static', static_url_path='')

# In-memory data store
tasks = []
messages = []

VALID_STATUSES = ['To Do', 'In Progress', 'Done']
VALID_PRIORITIES = ['high', 'medium', 'low']

def parse_ai_response(response_text):
    text = response_text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    return json.loads(text.strip())

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
    due_date = data.get('due_date', '').strip()
    is_blocked = bool(data.get('is_blocked', False))

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
        'due_date': due_date,
        'is_blocked': is_blocked,
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
        
    if 'due_date' in data:
        task['due_date'] = data['due_date'].strip()
        
    if 'is_blocked' in data:
        task['is_blocked'] = bool(data['is_blocked'])

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
        return jsonify({'error': 'AI Summarizer is not configured'}), 503

    if not tasks:
        return jsonify({'summary': 'There are no active tasks to summarize.'}), 200

    prompt = "Summarize the following team tasks and suggest what to prioritize next:\n\n"
    for t in tasks:
        prompt += f"- [{t['id']}] {t['title']} (Priority: {t['priority']}, Status: {t['status']}, Blocked: {t['is_blocked']})\n"

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        return jsonify({'summary': response.text}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to generate summary: {str(e)}'}), 500

@app.route('/api/ai/standup', methods=['POST'])
def ai_standup():
    data = request.get_json()
    if not data or not data.get('author') or not data.get('text'):
        return jsonify({'error': 'Author and text are required'}), 400

    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503

    author = data['author']
    text = data['text']

    prompt = f"""
The user ({author}) provided the following standup update:
"{text}"

Current tasks:
{json.dumps(tasks, indent=2)}

Analyze the standup text and the current tasks. Return a JSON object with the following structure:
{{
    "completed_task_ids": ["id1", "id2"], // Task IDs that the user indicates they have finished
    "blocked_task_ids": ["id3"], // Task IDs that the user indicates are blocking them
    "new_tasks": [ // Any new tasks the user implies they will do
        {{"title": "...", "description": "...", "priority": "medium", "assignee": "{author}", "status": "To Do", "is_blocked": false}}
    ],
    "summary_message": "A concise, formatted summary of what was done, what's new, and what's blocked, written from the perspective of the user to the team."
}}
Return ONLY valid JSON.
"""

    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=config
        )
        result = parse_ai_response(response.text)
        
        # Apply updates
        for tid in result.get('completed_task_ids', []):
            t = next((t for t in tasks if t['id'] == tid), None)
            if t: t['status'] = 'Done'
            
        for tid in result.get('blocked_task_ids', []):
            t = next((t for t in tasks if t['id'] == tid), None)
            if t: t['is_blocked'] = True
            
        for nt in result.get('new_tasks', []):
            tasks.append({
                'id': str(uuid.uuid4()),
                'title': nt.get('title', 'New Task'),
                'description': nt.get('description', ''),
                'priority': nt.get('priority', 'medium'),
                'assignee': nt.get('assignee', author),
                'status': 'To Do',
                'due_date': '',
                'is_blocked': False,
                'created_at': datetime.utcnow().isoformat()
            })

        # Post summary message
        msg_text = result.get('summary_message', text)
        new_msg = {
            'id': str(uuid.uuid4()),
            'author': f"🤖 StandupAI ({author})",
            'text': msg_text,
            'created_at': datetime.utcnow().isoformat()
        }
        messages.append(new_msg)

        return jsonify({'success': True, 'message': new_msg}), 200
    except Exception as e:
        return jsonify({'error': f'StandupAI failed: {str(e)}'}), 500

@app.route('/api/ai/plan_sprint', methods=['POST'])
def ai_plan_sprint():
    data = request.get_json()
    if not data or not data.get('goal'):
        return jsonify({'error': 'Goal is required'}), 400

    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503

    goal = data['goal']
    
    prompt = f"""
We are planning a new sprint. The goal is: "{goal}"
Generate 5 to 8 tasks needed to accomplish this goal.
Return ONLY a JSON object with this structure:
{{
    "tasks": [
        {{"title": "...", "description": "...", "priority": "high/medium/low", "assignee": "Unassigned", "due_date": "YYYY-MM-DD"}}
    ]
}}
"""
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=config
        )
        result = parse_ai_response(response.text)
        
        new_tasks = []
        for nt in result.get('tasks', []):
            t = {
                'id': str(uuid.uuid4()),
                'title': nt.get('title', 'Generated Task'),
                'description': nt.get('description', ''),
                'priority': nt.get('priority', 'medium') if nt.get('priority') in VALID_PRIORITIES else 'medium',
                'assignee': nt.get('assignee', 'Unassigned'),
                'status': 'To Do',
                'due_date': nt.get('due_date', ''),
                'is_blocked': False,
                'created_at': datetime.utcnow().isoformat()
            }
            tasks.append(t)
            new_tasks.append(t)
            
        return jsonify({'tasks': new_tasks}), 201
    except Exception as e:
        return jsonify({'error': f'AI Sprint Planner failed: {str(e)}'}), 500

@app.route('/api/ai/risk', methods=['GET'])
def ai_risk_detector():
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503

    if not tasks:
        return jsonify({'at_risk': False}), 200

    prompt = f"""
Analyze the following active tasks for sprint risks.
A sprint might be at risk if:
- There are multiple blocked tasks.
- High priority tasks are unassigned.
- Many tasks are overdue (due_date in the past relative to today, which is {datetime.utcnow().date().isoformat()}).

Tasks:
{json.dumps(tasks, indent=2)}

Return ONLY a JSON object with this structure:
{{
    "at_risk": true/false, // Boolean indicating if sprint is at risk
    "banner_message": "⚠️ Sprint at risk: 3 overdue tasks, 2 unassigned high priority items", // A short warning message (max 1 sentence)
    "recommendation": "Detailed recommendation on how to fix the risks..."
}}
"""
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=config
        )
        result = parse_ai_response(response.text)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': f'Risk Detector failed: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
