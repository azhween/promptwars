import os
import uuid
import json
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import flask_talisman
from flask_talisman import Talisman
from flask_cors import CORS
from google import genai
from google.genai import types
from typing import Tuple, Dict, Any, List

# Setup logging with Google Cloud fallback
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from google.cloud import logging as gcloud_logging
    gcloud_logger_client = gcloud_logging.Client()
    gcloud_logger_client.setup_logging()
    logger.info("Google Cloud Logging successfully configured.")
except ImportError:
    logger.warning("google-cloud-logging library not installed. Using standard logging.")
except Exception as e:
    logger.warning(f"Google Cloud Logging not configured. Using standard logging. Reason: {e}")

app = Flask(__name__, static_folder='static', static_url_path='')

# Security Configurations
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024 # 1MB limit

CORS(app, resources={r"/api/*": {"origins": ["http://localhost:8080", "https://*.run.app"]}})

csp = {
    'default-src': [
        '\'self\'',
        '\'unsafe-inline\'',
        'https://fonts.googleapis.com',
        'https://fonts.gstatic.com'
    ]
}
Talisman(
    app, 
    content_security_policy=csp, 
    force_https=False, 
    frame_options=flask_talisman.DENY
)

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
    default_limits=["100 per minute"],
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


@app.after_request
def apply_security_and_log(response):
    """Enforces strict security headers and logs every API call."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    if request.path.startswith('/api/'):
        logger.info(f"API Request: {request.method} {request.path} - Status: {response.status_code}")
    return response


def is_valid_uuid(val: str) -> bool:
    """
    Validates if a string is a valid UUIDv4.
    """
    try:
        uuid.UUID(str(val), version=4)
        return True
    except ValueError:
        return False


def strip_html(text: str) -> str:
    """
    Strips basic HTML tags from user input.
    """
    if not isinstance(text, str):
        return ""
    import re
    # Removes any HTML tag recursively
    clean = re.compile('<[^<]+?>')
    cleaned = re.sub(clean, '', text).strip()
    return cleaned


def parse_ai_response(response_text: str) -> Dict[str, Any]:
    """
    Safely parses JSON from Gemini API responses.
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
    return jsonify({"status": "ok"}), 200

@app.route('/')
def index() -> Any:
    return send_from_directory('static', 'index.html')

@app.route('/api/tasks', methods=['GET'])
def get_tasks() -> Tuple[Any, int]:
    return jsonify(list(tasks.values())), 200

@app.route('/api/tasks', methods=['POST'])
def create_task() -> Tuple[Any, int]:
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
    sprint_risk_cache['timestamp'] = 0
    return jsonify(new_task), 201


@app.route('/api/tasks/<task_id>', methods=['PATCH', 'PUT'])
def update_task(task_id: str) -> Tuple[Any, int]:
    if not is_valid_uuid(task_id):
        return jsonify({'error': 'Invalid Task ID format'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404

    task = tasks[task_id]
    old_status = task['status']
    
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

    sprint_risk_cache['timestamp'] = 0

    # Auto Congratulation if moved to Done
    if task['status'] == 'Done' and old_status != 'Done':
        client = get_gemini_client()
        if client:
            try:
                prompt = f"""
Task "{task['title']}" was just marked as Done!
Current pending tasks:
{json.dumps([t for t in tasks.values() if t['status'] != 'Done'], indent=2)}

Write a short, engaging congratulatory message to the team and suggest exactly 1 pending task they should focus on next based on priority.
"""
                start_time = time.time()
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt
                )
                logger.info(f"Gemini API /api/tasks (Auto-Done Hook) took {time.time() - start_time:.2f}s")
                messages.append({
                    'id': str(uuid.uuid4()),
                    'author': '🤖 FlowMate AI',
                    'text': response.text[:MAX_MESSAGE_LENGTH],
                    'created_at': datetime.utcnow().isoformat()
                })
            except Exception as e:
                logger.error(f"Failed to generate auto-done message: {str(e)}")

    return jsonify(task), 200


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id: str) -> Tuple[Any, int]:
    if not is_valid_uuid(task_id):
        return jsonify({'error': 'Invalid Task ID format'}), 400

    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
        
    del tasks[task_id]
    sprint_risk_cache['timestamp'] = 0
    return jsonify({"success": True}), 200


# ==========================================
# Team & Messages Routes
# ==========================================

@app.route('/api/team', methods=['GET'])
def get_team() -> Tuple[Any, int]:
    assignees = {t['assignee'] for t in tasks.values() if t.get('assignee')}
    return jsonify(list(assignees)), 200

@app.route('/api/messages', methods=['GET'])
def get_messages() -> Tuple[Any, int]:
    return jsonify(messages), 200

@app.route('/api/messages', methods=['POST'])
def create_message() -> Tuple[Any, int]:
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
            model='gemini-2.0-flash',
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
    "completed_task_ids": ["id1", "id2"],
    "blocked_task_ids": ["id3"],
    "new_tasks": [
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
            model='gemini-2.0-flash',
            contents=prompt,
            config=config
        )
        logger.info(f"Gemini API /api/ai/standup took {time.time() - start_time:.2f}s")
        result = parse_ai_response(response.text)
        
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

        sprint_risk_cache['timestamp'] = 0
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
            model='gemini-2.0-flash',
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
            
        sprint_risk_cache['timestamp'] = 0
        return jsonify({'tasks': new_tasks}), 201
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'AI Sprint Planner failed due to AI service error.'}), 500


@app.route('/api/ai/risk', methods=['GET'])
@limiter.limit("10 per minute")
def ai_risk_detector() -> Tuple[Any, int]:
    if not tasks:
        return jsonify({'at_risk': False}), 200

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
    "banner_message": "⚠️ Sprint at risk: 3 overdue tasks, 2 unassigned high priority items",
    "recommendation": "Detailed recommendation on how to fix the risks..."
}}
"""
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=config
        )
        logger.info(f"Gemini API /api/ai/risk took {time.time() - start_time:.2f}s")
        result = parse_ai_response(response.text)
        
        sprint_risk_cache['data'] = result
        sprint_risk_cache['timestamp'] = current_time
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'Risk Detector failed due to AI service error.'}), 500

@app.route('/api/ai/assistant', methods=['POST'])
@limiter.limit("20 per minute")
def ai_assistant() -> Tuple[Any, int]:
    """Answers arbitrary questions based on task context."""
    data = request.get_json()
    if not data or not data.get('question'):
        return jsonify({'error': 'Question is required'}), 400
    
    question = strip_html(data['question'])
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503
        
    prompt = f"""
You are the FlowMate AI Assistant. You answer team queries based on the current active tasks.
Current Date: {datetime.utcnow().date().isoformat()}
Active Tasks:
{json.dumps(list(tasks.values()), indent=2)}

User Question: "{question}"

Answer intelligently, concisely, and helpfully using the task context provided.
"""
    try:
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        logger.info(f"Gemini API /api/ai/assistant took {time.time() - start_time:.2f}s")
        return jsonify({'answer': response.text}), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'Assistant failed due to AI service error.'}), 500


@app.route('/api/ai/daily_briefing', methods=['GET'])
@limiter.limit("5 per minute")
def ai_daily_briefing() -> Tuple[Any, int]:
    """Generates a personalized daily briefing for the team."""
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503

    prompt = f"""
Current Date: {datetime.utcnow().date().isoformat()}
Active Tasks:
{json.dumps(list(tasks.values()), indent=2)}

Generate a "Daily Briefing".
Format exactly like this (with actual numbers/names based on context):
"Good morning! You have X high priority tasks, Y are overdue, Z is overloaded. Suggested focus: [task name]"
If no tasks, say: "Good morning! You have no active tasks. Consider planning a sprint."
"""
    try:
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        logger.info(f"Gemini API /api/ai/daily_briefing took {time.time() - start_time:.2f}s")
        return jsonify({'briefing': response.text}), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'Daily Briefing failed due to AI service error.'}), 500


@app.route('/api/ai/suggest_task', methods=['POST'])
@limiter.limit("30 per minute")
def ai_suggest_task() -> Tuple[Any, int]:
    """Auto-suggests priority and assignee based on title."""
    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({'error': 'Title is required'}), 400
        
    title = strip_html(data['title'])
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'AI features not configured'}), 503
        
    prompt = f"""
A user is typing the title for a new task: "{title}"
Current Active Tasks context:
{json.dumps([{{'title': t['title'], 'assignee': t['assignee'], 'priority': t['priority']}} for t in tasks.values()], indent=2)}

Predict the most likely priority (high, medium, low) and the best assignee for this new task.
Return ONLY a JSON object:
{{
    "priority": "medium",
    "assignee": "Name"
}}
"""
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        start_time = time.time()
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=config
        )
        logger.info(f"Gemini API /api/ai/suggest_task took {time.time() - start_time:.2f}s")
        return jsonify(parse_ai_response(response.text)), 200
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return jsonify({'error': 'Suggest Task failed due to AI service error.'}), 500


@app.errorhandler(429)
def ratelimit_handler(e: Any) -> Tuple[Any, int]:
    return jsonify({"error": "Rate limit exceeded."}), 429

@app.errorhandler(413)
def request_entity_too_large(e: Any) -> Tuple[Any, int]:
    return jsonify({"error": "Payload too large. Maximum size is 1MB."}), 413

@app.errorhandler(500)
def internal_error(e: Any) -> Tuple[Any, int]:
    logger.error(f"500 Internal Server Error: {str(e)}")
    return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
