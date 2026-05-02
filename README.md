# FlowMate - AI Collaboration Platform

FlowMate is an AI-native team collaboration platform (an evolution of the Team Collaboration Tool) featuring a dynamic Kanban board, team chat, and deeply integrated AI features powered by Google's Gemini API (`gemini-1.5-flash`).

## Core AI Features
- **StandupAI**: Natural language standups automatically parse blockers, completed tasks, and new assignments, displaying a structured summary in chat.
- **Sprint Risk Detector**: Automatically evaluates all tasks and blocks, showing a dynamic yellow warning banner if the sprint is at risk.
- **AI Team Summarizer**: Instantly generates a comprehensive team summary of progress and next steps.
- **AI Sprint Planner**: Type a goal and AI auto-generates 5-8 structured tasks, fully populating your To Do column.

## Tech Stack
- **Backend**: Python, Flask, Google GenAI SDK
- **Frontend**: Vanilla HTML/CSS/JS (Deep Navy UI, Glassmorphism, Syne/Inter fonts)
- **Deployment**: Google Cloud Run

## Setup Instructions

### 1. Prerequisites
- Python 3.11+
- A Google Gemini API Key

### 2. Installation
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables
Set the Gemini API key in your environment:
```bash
export GEMINI_API_KEY="your-api-key-here"
```

### 4. Running Locally
Run the application using Python or Gunicorn:
```bash
python app.py
```
Visit `http://localhost:8080` to experience FlowMate.

### 5. Running Tests
Run the pytest suite to ensure backend logic is fully validated:
```bash
PYTHONPATH=. pytest tests/
```

### 6. Deployment to Google Cloud Run
Build and submit the Docker image:
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/flowmate
```

Deploy:
```bash
gcloud run deploy flowmate \
    --image gcr.io/YOUR_PROJECT_ID/flowmate \
    --platform managed \
    --set-env-vars GEMINI_API_KEY="your-api-key-here" \
    --allow-unauthenticated \
    --port 8080
```
