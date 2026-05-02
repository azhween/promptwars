# FlowMate

FlowMate is an AI-native team collaboration platform that deeply integrates Google's Gemini API with a sleek new design to supercharge your team's productivity.

## Chosen Vertical
**Team Collaboration Tool**

## Approach and Logic
FlowMate uses Gemini AI as the core engine powering its advanced features. Rather than a standalone chatbot, Gemini is integrated directly into the Kanban and chat workflows.
- **StandupAI** uses structured JSON extraction to map natural language to specific task IDs, updating statuses and generating chat summaries.
- **Sprint Risk Detector** heuristically evaluates the in-memory task database to detect overdue or unassigned critical tasks, caching the analysis to save API calls.
- **AI Sprint Planner** translates an abstract sprint goal into 5-8 concrete, structured tasks injected directly into the "To Do" column.
- **AI Team Summarizer** compiles the current state of the board into a concise team update.

## How the Solution Works
1. **StandupAI**: Type "I finished the login page, but I'm blocked on API keys." The AI identifies the login task, marks it 'Done', identifies the API keys task, marks it 'Blocked', and posts a summary.
2. **Sprint Risk Detector**: On load, FlowMate silently analyzes tasks. If risks are found (e.g., 2 overdue tasks), a yellow pulsing banner appears recommending mitigation strategies.
3. **AI Sprint Planner**: Enter a goal like "Launch user dashboard" in the header and click "Plan Sprint". The AI generates 5-8 tasks and drops them into "To Do".
4. **AI Team Summarizer**: Click "Team Summary" to generate a modal report of what was completed, what's in progress, and what to do next.

## Google Services Used
- **Gemini 1.5 Flash API**: Powers all four AI features (StandupAI, Sprint Risk Detector, AI Sprint Planner, AI Team Summarizer) using fast, structured JSON generation.
- **Google Cloud Run**: The application is fully containerized and configured for serverless deployment on Google Cloud Run.
- **Google Cloud Build**: Used to build and push the Docker image to the Google Container Registry.

## Assumptions Made
- **Storage**: Tasks and messages are stored in memory using Python dictionaries for fast O(1) lookups during the competition. Data resets on restart.
- **Workspace**: This assumes a single team workspace (no multi-tenant isolation).
- **Environment**: The `GEMINI_API_KEY` must be provided as an environment variable for AI features to function.

## Setup Instructions

1. **Install Dependencies**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Run Locally**
```bash
export GEMINI_API_KEY="your-api-key"
python app.py
```
Open `http://localhost:8080`.

3. **Deploy to Google Cloud Run**
```bash
# Build and submit the image
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/flowmate

# Deploy
gcloud run deploy flowmate \
  --image gcr.io/YOUR_PROJECT_ID/flowmate \
  --platform managed \
  --set-env-vars GEMINI_API_KEY="YOUR_GEMINI_API_KEY" \
  --allow-unauthenticated \
  --port 8080
```
