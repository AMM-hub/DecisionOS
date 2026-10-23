# Archived: DecisionOS Laravel API (`apps/api`)

**Archived:** 2026-10-24

## What it was

A hand-written Laravel 13 skeleton for the application control plane (identity,
membership, policies, artifact lifecycle, job coordination, audit — spec §21.2).
It exposed `/v1` upload, dataset, metric-definition, and metric-query routes and
delegated statistical work to the Python worker.

It was never a running service in this repository: PHP/Composer were not installed,
it had no deployment wiring, and nothing under `apps/web` or `services/` imported
or called it.

## Why it is archived

The FastAPI service in `services/analytics` owns the same `/v1` surface and is the
running control plane for uploads, datasets, metric definitions, metric execution,
monitoring, forecasting, and pilots. Keeping a second, half-dead implementation of
that surface risked contract drift and confused the deployment story.

`services/analytics` supersedes this app in full.

## Running it, if ever needed

PHP 8.4+ and Composer are required. From this `archive/apps-api` directory:

```bash
composer install
cp .env.example .env
php artisan key:generate
php artisan migrate   # requires PostgreSQL
php artisan serve
```

The original layout notes (routes, middleware, services, migrations) and the list
of deliberate omissions are preserved in the history of this file.

The canonical API is `services/analytics` — use it for anything new.
