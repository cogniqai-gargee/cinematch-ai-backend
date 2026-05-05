# CineMatch AI Backend

Stack:

- FastAPI
- Supabase Postgres and Supabase Auth
- TMDB API
- Gemma 4 31B through a provider abstraction
- Supabase pgvector later

Routes:

- `GET /health`
- `POST /chat`
- `POST /recommendations`
- `GET /recommendations`
- `POST /saved-movies`
- `GET /saved-movies`
- `DELETE /saved-movies/{id}`

## Run Locally

From the `backend` directory, create and activate a virtual environment, install the package, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

```powershell
python -m uvicorn app.main:app --reload
```

The current implementation uses TMDB when `TMDB_API_KEY` is available and calls Gemma through OpenRouter when `GEMMA_API_KEY` is present. There is no mock LLM provider and the backend does not invent movie candidates when TMDB or OpenRouter fails.

The mobile app stores user watchlists and completed recommendation sessions directly in Supabase with Supabase Auth and Row Level Security. The backend saved-movies routes remain available for local development compatibility until authenticated backend user tokens are introduced.

## Supabase Schema

The initial SQL migration lives at:

```text
supabase/migrations/20260503_000001_initial_schema.sql
supabase/migrations/20260503_000002_health_check.sql
supabase/migrations/20260503_000003_health_check_returns_ok.sql
supabase/migrations/20260504_000004_harden_mobile_persistence.sql
```

Paste Supabase values into `backend/.env`:

```env
SUPABASE_URL=your-project-url
SUPABASE_ANON_KEY=your-anon-key
TMDB_API_KEY=your-tmdb-api-key
```

To apply the schema:

1. Open your Supabase project dashboard.
2. Go to `SQL Editor`.
3. Run each SQL file in `supabase/migrations/` in filename order.
4. Check `Table Editor` for `profiles`, `conversations`, `messages`, `movie_preferences`, `recommendations`, and `saved_movies`.

Row Level Security is enabled in the migration. The included policies restrict authenticated users to their own rows through `auth.uid() = user_id`.

Run `20260503_000003_health_check_returns_ok.sql` in the Supabase SQL Editor if `GET /health` reports that `public.health_check` does not exist. It creates `public.health_check()`, which returns `ok` without querying protected app tables. The backend reports Supabase `connected: true` only when this RPC returns `ok`.

## TMDB

TMDB calls are backend-only. Put `TMDB_API_KEY` in `backend/.env`; never add it to the Expo app.

The backend service supports:

- movie search
- movie details
- discover by genre
- discover by original language
- discover by year
- discover by minimum rating
- discover by popularity
- normalization into the app `MovieCandidate` shape

If TMDB is unavailable or `TMDB_API_KEY` is missing, the backend returns a clean unavailable state instead of fake movie recommendations.

## Gemma Through OpenRouter

Gemma/OpenRouter calls are backend-only. Put these values in `backend/.env`:

```env
GEMMA_API_URL=https://openrouter.ai/api/v1/chat/completions
GEMMA_API_KEY=your-openrouter-key
GEMMA_MODEL=google/gemma-4-31b-it:free
```

`OpenRouterGemmaProvider` sends conversation history, extracted preferences, and TMDB movie candidates to OpenRouter, then returns clean ranked recommendations to the Expo app. `GEMMA_API_KEY` is required. If it is missing, or if OpenRouter fails or returns malformed JSON, the backend returns `LLM_UNAVAILABLE` and the Expo app shows a clean retry message. If OpenRouter returns `429`, the backend waits 2 seconds, retries once, then returns `RATE_LIMITED` if the retry fails.
