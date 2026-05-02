import os
import uuid
import json
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from google import genai
from google.genai import types
from typing import Tuple, Dict, Any, List

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')

# Configuration & Constants
MAX_TITLE_LENGTH = 200
MAX_DESC_LENGTH = 1000
MAX_STANDUP_LENGTH = 2000
MAX_MESSAGE_LENGTH = 500

VALID_STATUSES = ['To Do', 'In Progress', 'Done']
VALID_PRIORITIES = ['high', 'medium', 'low']

# Rate Limiter Configuration
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["1000 per day"],
    storage_uri="memory://"
)

# In-memory data store using dicts for efficient O(1) lookups
tasks: Dict[str, Dict[str, Any]] = {}
messages: List[Dict[str, Any]] = []

# Global dict cache for sprint risk analysis
sprint_risk_cache: Dict[str, Any] = {
    'timestamp': 0,
    'data': None
}

# Ensure API Key is present at startup
if not os.environ.get("GEMINI_API_KEY"):
    logger.warning("WARNING: GEMINI_API_KEY environment variable is missing. AI features will fail.")


def strip_html(text: str) -> str:
    """
    Strips basic HTML tags from user input.

    Args:
        text (str): The raw input string.

    Returns:
        str: The sanitized string.
    """
    if not isinstance(text, str):
        return ""
    import re
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text).strip()


def parse_ai_response(response_text: str) -> Dict[str, Any]:
    """
    Safely parses JSON from Gemini API responses, stripping markdown blocks if present.

    Args:
        response_text (str): The raw text response from the API.

    Returns:
        Dict[str, Any]: The parsed JSON dictionary.
        
    Raises:
        json.JSONDecodeError: If the response cannot be parsed into JSON.
    """
    text = response_text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    return json.loads(text.strip())


def get_gemini_client() -> Any:
    """
    Retrieves the configured Gemini client.

    Returns:
        genai.Client or None: Returns the authenticated client if the key is present, None otherwise.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


# ==========================================
# Task Routes
# ==========================================

@app.route('/health', methods=['GET'])
def health_check() -> Tuple[Any, int]:
    """
    Health check endpoint.

    Returns:
        tuple: JSON status and 200 HTTP code.
    """
    return jsonify({"status": "ok"}), 200


@app.route('/')
def index() -> Any:
    """
    Serves the main frontend application.

    Returns:
        Response: The static index.html file.
    """
    return send_from_directory('static', 'index.html')


@app.route('/api/tasks', methods=['GET'])
def get_tasks() -> Tuple[Any, int]:
    """
    Retrieves all current tasks.

    Returns:
        tuple: A JSON list of tasks and 200 HTTP code.
    """
    return jsonify(list(tasks.values())), 200


@app.route('/api/tasks', methods=['POST'])
def create_task() -> Tuple[Any, int]:
    """
    Creates a new task with validation and sanitization.

    Returns:
        tuple: The created task JSON and 201 HTTP code, or an error JSON and 400.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    title = strip_html(data.get('title', ''))
    description = strip_html(data.get('description', ''))
    priority = strip_html(data.get('priority', 'low')).lower()
    assignee = strip_html(data.get('assignee', ''))
    status = strip_html(data.get('status', 'To Do'))
    due_date = strip_html(data.get('due_date', ''))
    is_blocked = bool(data.get('is_blocked', False))

    if not title:
        return jsonify({'error': 'Title is required'}), 400
    
    if len(title) > MAX_TITLE_LENGTH:
        return jsonify({'error': f'Title exceeds max length of {MAX_TITLE_LENGTH}'}), 400
        
    if len(description) > MAX_DESC_LENGTH:
        return jsonify({'error': f'Description exceeds max length of {MAX_DESC_LENGTH}'}), 400
    
    if priority not in VALID_PRIORITIES:
        return jsonify({'error': 'Invalid priority level'}), 400

    if status not in VALID_STATUSES:
        return jsonify({'error': 'Invalid status'}), 400

    task_id = str(uuid.uuid4())
    new_task = {
        'id': task_id,
        'title': title,
        'description': description,
        'priority': priority,
        'assignee': assignee,
        'status': status,
        'due_date': due_date,
        'is_blocked': is_blocked,
        'created_at': datetime.utcnow().isoformat()
    }
    tasks[task_id] = new_task
    
    # Invalidate cache
    sprint_risk_cache['timestamp'] = 0
    
    return jsonify(new_task), 201


@app.route('/api/tasks/<task_id>', methods=['PATCH', 'PUT'])
def update_task(task_id: str) -> Tuple[Any, int]:
    """
    Updates an existing task with partial data.

    Args:
        task_id (str): The unique identifier of the task.

    Returns:
        tuple: The updated task JSON and 200 HTTP code, or an error and 400/404.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404

    task = tasks[task_id]
    
    if 'title' in data:
        title = strip_html(data['title'])
        if not title:
            return jsonify({'error': 'Title cannot be empty'}), 400
        if len(title) > MAX_TITLE_LENGTH:
            return jsonify({'error': f'Title exceeds max length of {MAX_TITLE_LENGTH}'}), 400
        task['title'] = title
    
    if 'description' in data:
        desc = strip_html(data['description'])
        if len(desc) > MAX_DESC_LENGTH:
            return jsonify({'error': f'Description exceeds max length of {MAX_DESC_LENGTH}'}), 400
        task['description'] = desc
        
    if 'priority' in data:
        priority = strip_html(data['priority']).lower()
        if priority not in VALID_PRIORITIES:
            return jsonify({'error': 'Invalid priority level'}), 400
        task['priority'] = priority
        
    if 'assignee' in data:
        task['assignee'] = strip_html(data['assignee'])
        
    if 'status' in data:
        status = strip_html(data['status'])
        if status not in VALID_STATUSES:
            return jsonify({'error': 'Invalid status'}), 400
        task['status'] = status
        
    if 'due_date' in data:
        task['due_date'] = strip_html(data['due_date'])
        
    if 'is_blocked' in data:
        task['is_blocked'] = bool(data['is_blocked'])

    # Invalidate cache
    sprint_risk_cache['timestamp'] = 0

    return jsonify(task), 200


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id: str) -> Tuple[Any, int]:
    """
    Deletes a task by its ID.

    Args:
        task_id (str): The unique identifier of the task.

    Returns:
        tuple: Empty response and 200 HTTP code, or error and 404.
    """
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
        
    del tasks[task_id]
    
    # Invalidate cache
    sprint_risk_cache['timestamp'] = 0
    
    return jsonify({"success": True}), 200


# ==========================================
# Team Routes
# ==========================================

@app.route('/api/team', methods=['GET'])
def get_team() -> Tuple[Any, int]:
    """
    Retrieves a list of unique team members (assignees) from active tasks.

    Returns:
        tuple: A JSON list of unique assignees and 200 HTTP code.
    """
    assignees = {t['assignee'] for t in tasks.values() if t.get('assignee')}
    return jsonify(list(assignees)), 200


# ==========================================
# Message Routes
# ==========================================

@app.route('/api/messages', methods=['GET'])
def get_messages() -> Tuple[Any, int]:
    """
    Retrieves all chat messages.

    Returns:
        tuple: JSON list of messages and 200 HTTP code.
    """
    return jsonify(messages), 200


@app.route('/api/messages', methods=['POST'])
def create_message() -> Tuple[Any, int]:
    """
    Creates a new chat message.

    Returns:
        tuple: The new message JSON and 201 HTTP code, or an error and 400.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    author = strip_html(data.get('author', ''))
    text = strip_html(data.get('text', ''))
    
    if not author:
        return jsonify({'error': 'Author name is required'}), 400
    if not text:
        return jsonify({'error': 'Message text is required'}), 400
        
    if len(text) > MAX_MESSAGE_LENGTH:
        return jsonify({'error': f'Message exceeds max length of {MAX_MESSAGE_LENGTH}'}), 400
        
    new_msg = {
        'id': str(uuid.uuid4()),
        'author': author,
        'text': text,
        'created_at': datetime.utcnow().isoformat()
    }
    messages.append(new_msg)
    return jsonify(new_msg), 201


# ==========================================
# AI Routes
# ==========================================

@app.route('/api/summarize', methods=['POST'])
@limiter.limit("10 per minute")
def summarize_tasks() -> Tuple[Any, int]:
    """
    Calls Gemini API to summarize all current tasks. Rate limited to 10/min.

    Returns:
        tuple: JSON with summary and 200 HTTP code, or error and 500/503.
    """
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI Summarizer is not configured'}), 503

    if not tasks:
        return jsonify({'summary': 'There are no active tasks to summarize.'}), 200

    prompt = "Summarize the following team tasks and suggest what to prioritize next:\n\n"
    for t in tasks.values():
        prompt += f"- [{t['id']}] {t['title']} (Priority: {t['priority']}, Status: {t['status']}, Blocked: {t['is_blocked']})\n"

    try:
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        logger.info(f"Gemini API /api/summarize took {time.time() - start_time:.2f}s")
        return jsonify({'summary': response.text}), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'Failed to generate summary due to AI service error.'}), 500


@app.route('/api/ai/standup', methods=['POST'])
@limiter.limit("10 per minute")
def ai_standup() -> Tuple[Any, int]:
    """
    Analyzes natural language standup updates using Gemini API. Rate limited to 10/min.

    Returns:
        tuple: JSON with updates and 200 HTTP code, or error and 400/500/503.
    """
    data = request.get_json()
    if not data or not data.get('author') or not data.get('text'):
        return jsonify({'error': 'Author and text are required'}), 400

    author = strip_html(data['author'])
    text = strip_html(data['text'])

    if len(text) > MAX_STANDUP_LENGTH:
        return jsonify({'error': f'Standup text exceeds max length of {MAX_STANDUP_LENGTH}'}), 400

    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503

    prompt = f"""
The user ({author}) provided the following standup update:
"{text}"

Current tasks:
{json.dumps(list(tasks.values()), indent=2)}

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
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=config
        )
        logger.info(f"Gemini API /api/ai/standup took {time.time() - start_time:.2f}s")
        result = parse_ai_response(response.text)
        
        # Apply updates using dict lookups O(1)
        for tid in result.get('completed_task_ids', []):
            if tid in tasks:
                tasks[tid]['status'] = 'Done'
            
        for tid in result.get('blocked_task_ids', []):
            if tid in tasks:
                tasks[tid]['is_blocked'] = True
            
        for nt in result.get('new_tasks', []):
            new_id = str(uuid.uuid4())
            tasks[new_id] = {
                'id': new_id,
                'title': strip_html(nt.get('title', 'New Task'))[:MAX_TITLE_LENGTH],
                'description': strip_html(nt.get('description', ''))[:MAX_DESC_LENGTH],
                'priority': nt.get('priority', 'medium') if nt.get('priority') in VALID_PRIORITIES else 'medium',
                'assignee': strip_html(nt.get('assignee', author)),
                'status': 'To Do',
                'due_date': '',
                'is_blocked': False,
                'created_at': datetime.utcnow().isoformat()
            }

        sprint_risk_cache['timestamp'] = 0 # Invalidate cache

        # Post summary message
        msg_text = result.get('summary_message', text)
        new_msg = {
            'id': str(uuid.uuid4()),
            'author': f"🤖 StandupAI ({author})",
            'text': msg_text[:MAX_MESSAGE_LENGTH],
            'created_at': datetime.utcnow().isoformat()
        }
        messages.append(new_msg)

        return jsonify({'success': True, 'message': new_msg}), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'StandupAI failed due to AI service error.'}), 500


@app.route('/api/ai/plan_sprint', methods=['POST'])
@limiter.limit("10 per minute")
def ai_plan_sprint() -> Tuple[Any, int]:
    """
    Generates new sprint tasks using Gemini API based on a goal. Rate limited to 10/min.

    Returns:
        tuple: JSON with new tasks and 201 HTTP code, or error and 400/500/503.
    """
    data = request.get_json()
    if not data or not data.get('goal'):
        return jsonify({'error': 'Goal is required'}), 400

    goal = strip_html(data['goal'])
    if len(goal) > MAX_TITLE_LENGTH:
        return jsonify({'error': f'Goal exceeds max length of {MAX_TITLE_LENGTH}'}), 400

    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503
    
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
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=config
        )
        logger.info(f"Gemini API /api/ai/plan_sprint took {time.time() - start_time:.2f}s")
        result = parse_ai_response(response.text)
        
        new_tasks = []
        for nt in result.get('tasks', []):
            new_id = str(uuid.uuid4())
            t = {
                'id': new_id,
                'title': strip_html(nt.get('title', 'Generated Task'))[:MAX_TITLE_LENGTH],
                'description': strip_html(nt.get('description', ''))[:MAX_DESC_LENGTH],
                'priority': nt.get('priority', 'medium') if nt.get('priority') in VALID_PRIORITIES else 'medium',
                'assignee': strip_html(nt.get('assignee', 'Unassigned')),
                'status': 'To Do',
                'due_date': strip_html(nt.get('due_date', '')),
                'is_blocked': False,
                'created_at': datetime.utcnow().isoformat()
            }
            tasks[new_id] = t
            new_tasks.append(t)
            
        sprint_risk_cache['timestamp'] = 0 # Invalidate cache
        return jsonify({'tasks': new_tasks}), 201
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'AI Sprint Planner failed due to AI service error.'}), 500


@app.route('/api/ai/risk', methods=['GET'])
@limiter.limit("10 per minute")
def ai_risk_detector() -> Tuple[Any, int]:
    """
    Evaluates sprint risks using Gemini API. Caches response for 60 seconds. Rate limited to 10/min.

    Returns:
        tuple: JSON with risk analysis and 200 HTTP code, or error and 500/503.
    """
    if not tasks:
        return jsonify({'at_risk': False}), 200

    # Return cached response if valid (under 60 seconds old)
    current_time = time.time()
    if sprint_risk_cache['data'] and (current_time - sprint_risk_cache['timestamp'] < 60):
        return jsonify(sprint_risk_cache['data']), 200

    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503

    prompt = f"""
Analyze the following active tasks for sprint risks.
A sprint might be at risk if:
- There are multiple blocked tasks.
- High priority tasks are unassigned.
- Many tasks are overdue (due_date in the past relative to today, which is {datetime.utcnow().date().isoformat()}).

Tasks:
{json.dumps(list(tasks.values()), indent=2)}

Return ONLY a JSON object with this structure:
{{
    "at_risk": true/false, // Boolean indicating if sprint is at risk
    "banner_message": "⚠️ Sprint at risk: 3 overdue tasks, 2 unassigned high priority items", // A short warning message (max 1 sentence)
    "recommendation": "Detailed recommendation on how to fix the risks..."
}}
"""
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=config
        )
        logger.info(f"Gemini API /api/ai/risk took {time.time() - start_time:.2f}s")
        result = parse_ai_response(response.text)
        
        # Update cache
        sprint_risk_cache['data'] = result
        sprint_risk_cache['timestamp'] = current_time
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'Risk Detector failed due to AI service error.'}), 500


@app.errorhandler(429)
def ratelimit_handler(e: Any) -> Tuple[Any, int]:
    """
    Custom handler for rate limiting errors.

    Args:
        e: The exception context.

    Returns:
        tuple: JSON error message and 429 HTTP code.
    """
    return jsonify({"error": "Rate limit exceeded. Maximum 10 requests per minute."}), 429


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
