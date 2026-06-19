# Carbon Footprint Education Platform

Django app covering three pillars: **Understand** (education), **Track** (logging), **Reduce** (recommendations + goals), with NVIDIA NIM (free-tier LLM) powering personalized insights and Q&A.

## Setup

```bash
# 1. Create venv
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY (any random string for dev) and NVIDIA_API_KEY
# Get a free NVIDIA key: https://build.nvidia.com -> sign in -> pick a model -> "Get API Key"

# 4. Run migrations
python manage.py migrate

# 5. Seed starter data (emission factors, lessons, glossary, recommendations)
python manage.py seed_data

# 6. Create an admin user (optional, for /admin/)
python manage.py createsuperuser

# 7. Run the dev server
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` — sign up for an account, log an activity, check the dashboard, visit `/learn/` and `/insights/`.

## What's implemented

- **Auth**: full Django signup/login/logout
- **Track**: activity logging form (htmx category→activity dropdown), dashboard with Chart.js breakdown, activity history
- **Understand**: static lesson library (`/learn/`), glossary (`/glossary/`), LLM-powered Q&A widget (rate-limited 10/day/user)
- **Reduce**: rule-based insights (vs. national averages), static recommendations filtered by top-emission category, monthly goal + progress bar
- **LLM**: NVIDIA NIM API, `meta/llama-3.1-8b-instruct`, used only for personalized tip phrasing + Q&A — never for emission calculations or core facts. Caches tips 24h. Validates output doesn't contain invented numbers, falls back to a static message if validation fails or the API call errors.

## Known limitations / honest notes

- `EmissionFactor` values in `seed_data.py` are reasonable MVP approximations (DEFRA/EPA-style), **not audited figures** — replace with sourced, region-specific data before any real-world use.
- `NATIONAL_AVG` benchmarks in `core/views.py` are placeholders — same caveat.
- No real LLM key configured by default — without one, the Insights page gracefully falls back to a static message instead of crashing (tested).
- SQLite is fine for MVP/local dev; switch to PostgreSQL before any multi-user production deploy.
- No Celery/async — LLM calls are synchronous. Fine at MVP scale; revisit if latency becomes a real problem (see design doc section 9.2).

## Project structure

```
carbon_platform/
├── carbon_platform/        # Django project (settings, urls, wsgi)
├── core/
│   ├── models.py            # EmissionFactor, ActivityLog, Recommendation, Goal, EducationContent, GlossaryTerm, QAUsage
│   ├── views.py              # all three pillars
│   ├── forms.py
│   ├── admin.py
│   ├── services/llm.py       # NVIDIA NIM integration, caching, validation, rate-limit
│   └── management/commands/seed_data.py
├── templates/core/           # all HTML templates (Tailwind CDN + htmx + Chart.js)
├── requirements.txt
├── .env.example
└── manage.py
```
