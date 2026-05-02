# Team Collaboration Tool

A full-stack web application for team collaboration featuring a Kanban board, team chat, and AI task summarizer.

## Tech Stack
- **Backend**: Python, Flask
- **Frontend**: Vanilla HTML/CSS/JS
- **AI**: Google Gemini API (`gemini-1.5-flash`)
- **Deployment**: Google Cloud Run

## Setup Instructions

### 1. Prerequisites
- Python 3.11+
- [Docker](https://docs.docker.com/get-docker/) (optional, for containerization)
- A Google Gemini API Key

### 2. Installation
Clone the repository (or navigate to the directory) and create a virtual environment:

```bash
cd team-collab-tool
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables
Set the Gemini API key in your environment to enable the AI Summarizer:
```bash
export GEMINI_API_KEY="your-api-key-here"
```

### 4. Running the App Locally
Run the Flask application:
```bash
python app.py
```
Or with gunicorn:
```bash
gunicorn --bind 0.0.0.0:8080 app:app
```
Then visit `http://localhost:8080` in your browser.

### 5. Running Tests
Run the pytest suite to ensure all backend endpoints are functioning correctly:
```bash
pytest tests/
```

### 6. Deployment to Google Cloud Run
This application is fully containerized and ready for Cloud Run.

Build and submit the Docker image:
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/team-collab-tool
```

Deploy to Cloud Run:
```bash
gcloud run deploy team-collab-tool \
    --image gcr.io/YOUR_PROJECT_ID/team-collab-tool \
    --platform managed \
    --set-env-vars GEMINI_API_KEY="your-api-key-here" \
    --allow-unauthenticated \
    --port 8080
```
