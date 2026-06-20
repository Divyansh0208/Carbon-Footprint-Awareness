# Carbon Footprint Education Platform

Django app covering three pillars: **Understand** (education), **Track** (logging), **Reduce** (recommendations + goals), with NVIDIA NIM (free-tier LLM) powering personalized insights and Q&A.

![Tests](https://img.shields.io/badge/Tests-146%20passing-brightgreen)
![Coverage](https://img.shields.io/badge/Coverage-99%25-brightgreen)

## Local setup (SQLite + LocMemCache — quick dev loop)

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
# Leave DATABASE_URL and REDIS_URL unset for this path — falls back to SQLite/LocMemCache.

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

## Local setup with Postgres + Redis (matches production)

Use this if you want to test against the same datastores as the live deploy, before pushing.

```bash
docker run -d --name carbon-pg -e POSTGRES_USER=carbon -e POSTGRES_PASSWORD=carbonpass -e POSTGRES_DB=carbon_db -p 5432:5432 postgres:16
docker run -d --name carbon-redis -p 6379:6379 redis:7
```

In `.env`:
```env
DATABASE_URL=postgres://carbon:carbonpass@localhost:5432/carbon_db
REDIS_URL=redis://localhost:6379/0
```

Then run the same `migrate` / `seed_data` / `runserver` steps above. Confirm it's actually using Postgres/Redis, not falling back silently:
```bash
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE']); print(settings.CACHES['default']['BACKEND'])"
```
Should print `django.db.backends.postgresql` and `django_redis.cache.RedisCache`.

## Running tests

```bash
python manage.py test core --verbosity=2
```

146 tests, 99% coverage. To generate a local HTML report:

```bash
pip install coverage
coverage run --source=core manage.py test core
coverage html   # open htmlcov/index.html
```

The two uncovered lines (`core/forms.py`) are a defensive `except` branch unreachable via HTTP — Django coerces POST values to strings before the form sees them.

## What's implemented

- **Auth**: full Django signup/login/logout
- **Track**: activity logging form (htmx category→activity dropdown), dashboard with Chart.js breakdown, activity history
- **Understand**: lesson library (`/learn/`), glossary (`/glossary/`), LLM-powered Q&A widget (rate-limited 10/day/user) — content depth is still MVP-level, flagged as a known limitation below
- **Reduce**: rule-based insights (vs. national averages), static recommendations filtered by top-emission category, monthly goal + progress bar
- **LLM**: NVIDIA NIM API, `mistralai/mistral-large-3-675b-instruct-2512`, used only for personalized tip phrasing + Q&A — never for emission calculations or core facts. Caches tips 24h. Validates output doesn't contain invented numbers; falls back to a static message if validation fails or the API call errors.

## Production readiness

- **Database**: `DATABASE_URL` env var switches to Postgres (`dj-database-url` + `psycopg2-binary`); unset falls back to SQLite for local dev only. SQLite's single-writer lock makes it unsafe for concurrent real users.
- **Cache**: `REDIS_URL` env var switches to Redis (`django-redis`); unset falls back to Django's `LocMemCache`, which fragments across multiple worker processes and is local-dev-only.
- **LLM client timeout**: the NVIDIA/OpenAI client has `timeout=10.0` and `max_retries=1` set explicitly — without this, a hung API call can block a worker thread for the SDK's ~10-minute default, starving other requests.
- **Security headers**: when `DEBUG=False`, `settings.py` automatically enables `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_*` (off by default via `SECURE_HSTS_SECONDS=0` until explicitly raised post-verification), `X_FRAME_OPTIONS`, and `SECURE_PROXY_SSL_HEADER` (needed behind Render's TLS-terminating proxy).
- **Admin URL**: configurable via `ADMIN_URL` env var (defaults to `admin/`); set to a non-default slug in production to reduce automated scanning noise. Not a substitute for a strong superuser password.
- **WSGI server**: `gunicorn` is in `requirements.txt` for production; `runserver` remains dev-only.

## Known limitations / honest notes

- `EmissionFactor` values in `seed_data.py` are reasonable MVP approximations (DEFRA/EPA-style), **not audited figures** — replace with sourced, region-specific data before any real-world use.
- `NATIONAL_AVG` benchmarks in `core/views.py` are placeholders — same caveat.
- No real LLM key configured by default — without one, the Insights page gracefully falls back to a static message instead of crashing (tested).
- **Understand content is still thin** — a handful of short static articles, not yet personalized to a user's own logged data. Visual design for this section is done; content depth is a follow-up task.
- No Celery/async — LLM calls are synchronous with a bounded timeout. Fine at MVP/low-concurrency scale; revisit if latency under load becomes a real problem.
- No email verification on signup.
- Render's free tier: web service cold-starts after inactivity (~30-50s), and free Postgres instances expire after 90 days unless upgraded.

## Project structure

```
carbon_platform/
├── carbon_platform/          # Django project (settings, urls, wsgi)
│   ├── settings.py            # env-driven DATABASES/CACHES, prod security block
│   └── urls.py                 # env-configurable ADMIN_URL
├── core/
│   ├── models.py               # EmissionFactor, ActivityLog, Recommendation, Goal, EducationContent, GlossaryTerm, QAUsage
│   ├── views.py                 # all three pillars
│   ├── forms.py
│   ├── admin.py
│   ├── tests.py                  # 146 tests
│   ├── services/llm.py          # NVIDIA NIM integration, caching, validation, rate-limit, timeout
│   └── management/commands/seed_data.py
├── templates/core/              # Tailwind CDN + htmx + Chart.js, custom design tokens (paper/ink/moss/rust palette)
├── requirements.txt              # includes gunicorn, dj-database-url, psycopg2-binary, django-redis
├── .env.example
├── .gitignore
└── manage.py
```