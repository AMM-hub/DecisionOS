# DecisionOS API (Laravel 13) — application control plane

Owns identity, membership, policies, artifact lifecycle, job coordination, and audit
(spec §21.2). Statistical work belongs to `services/analytics`.

## Status: skeleton

PHP/Composer are not installed on the current machine, so this is a hand-written
Laravel 13 slim-structure skeleton. To materialize:

```bash
composer install
cp .env.example .env && php artisan key:generate
php artisan migrate   # requires PostgreSQL (see infra/docker-compose.yml)
php artisan serve
```

## Layout

- `routes/api.php` — `/v1` endpoint groups for the E2E flow (uploads, datasets, definitions, metrics).
- `app/Http/Controllers/V1/*` — thin request validation; no business statistics here.
- `app/Http/Middleware/ResolveTenantContext.php` — server-side tenant/workspace resolution; demo headers only in `local` with `DECISIONOS_TRUST_DEMO_HEADERS=true`.
- `app/Http/Middleware/EnforceIdempotency.php` — keys scoped to tenant+principal+endpoint+digest (§23.1).
- `app/Services/WorkerClient.php` — documented Laravel↔Python RPC protocol (no shared queue wire format).
- `database/migrations/*core_tenant_integrity.php` — composite `(tenant_id, id)` PKs and containment FKs (§22.2).

## Deliberate omissions (tracked, not hidden)

- User/membership models and Sanctum config are stubs referenced by middleware.
- GiST exclusion constraint for nonoverlapping publication intervals (§22.3) must be added with `btree_gist` setup.
- Object storage presigning is a placeholder; wire to S3-compatible store via `config/decisionos.php`.
- Feature tests for the authorization matrix (QA-025..QA-027) come with the identity provider.
