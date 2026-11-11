# Project Context

## Architecture
- Flask API (`backend/app.py`) serves static SPA (`frontend/`) and JSON under `/api`.
- Core business logic resides in `backend/services/`; request handling is thin in `backend/routes/`.
- Frontend is a vanilla JavaScript SPA (`frontend/js/app.js`).

## File Map (one per line)
- README.md
- backend/app.py, config.py, db.py, common.py, seed.py
- backend/routes/auth_kb.py, submissions.py
- backend/services/* (analytics, badge, image_checker, llm, pdf, pipeline, rag, text_checker, workflow)
- frontend/index.html, css/style.css, js/app.js
- tests/test_api.py
- sample_data/brand_guidelines.md, product_facts.md
- data/ (runtime SQLite DB)

## Running the app
```bash
python -m backend.app
```
Server starts at `http://localhost:8000`.

## Testing
```bash
python -m unittest discover -s tests -v
```
All tests must pass.

## Conventions
- `services/` hold logic, `routes/` are thin, frontend is vanilla JS in `frontend/js/app.js`.