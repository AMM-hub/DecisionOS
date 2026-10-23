<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Tenant integrity pattern (spec 22.2): composite (tenant_id, id) primary keys and
 * composite foreign keys enforcing containment. No single-column workspace_id FK trust.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('tenant', fn (Blueprint $t) => $t->uuid('id')->primary());

        Schema::create('workspace', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('id');
            $t->string('name');
            $t->primary(['tenant_id', 'id']);
            $t->foreign('tenant_id')->references('id')->on('tenant');
        });

        Schema::create('dataset', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('id');
            $t->string('name');
            $t->uuid('workspace_id');
            $t->unsignedInteger('published_revision')->nullable();
            $t->timestamp('published_at')->nullable();
            $t->uuid('published_by')->nullable();
            $t->primary(['tenant_id', 'id']);
            $t->foreign(['tenant_id', 'workspace_id'])->references(['tenant_id', 'id'])->on('workspace');
            $t->unique(['tenant_id', 'workspace_id', 'name']);
        });

        Schema::create('upload', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('id');
            $t->uuid('workspace_id');
            $t->uuid('created_by');
            $t->string('original_filename');
            $t->unsignedBigInteger('declared_size_bytes');
            $t->string('quarantine_key');
            $t->string('status');
            $t->jsonb('scan_result')->nullable();
            $t->jsonb('parse_preview')->nullable();
            $t->uuid('dataset_id')->nullable();
            $t->timestamp('expires_at');
            $t->timestamps();
            $t->primary(['tenant_id', 'id']);
            $t->foreign(['tenant_id', 'workspace_id'])->references(['tenant_id', 'id'])->on('workspace');
            $t->foreign(['tenant_id', 'dataset_id'])->references(['tenant_id', 'id'])->on('dataset')->nullOnDelete();
        });

        Schema::create('dataset_revision', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('dataset_id');
            $t->unsignedInteger('revision');
            $t->string('state'); // staged | validating | validated | published | failed
            $t->jsonb('manifest'); // object versions/hashes, schema, transform version, checkpoint
            $t->unsignedBigInteger('row_count');
            $t->unsignedBigInteger('rejected_row_count')->default(0);
            $t->uuid('lease_owner')->nullable();
            $t->timestamp('lease_expires_at')->nullable();
            $t->timestamps();
            $t->primary(['tenant_id', 'dataset_id', 'revision']);
            $t->foreign(['tenant_id', 'dataset_id'])->references(['tenant_id', 'id'])->on('dataset');
        });

        Schema::create('grain_confirmation', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('dataset_id');
            $t->jsonb('key_columns');
            $t->uuid('confirmed_by');
            $t->timestamp('confirmed_at');
            $t->primary(['tenant_id', 'dataset_id']);
            $t->foreign(['tenant_id', 'dataset_id'])->references(['tenant_id', 'id'])->on('dataset');
        });

        Schema::create('definition', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('id'); // use deterministic uuid for stable ids like metric-cycle-time in production
            $t->string('kind');
            $t->uuid('created_by');
            $t->timestamps();
            $t->primary(['tenant_id', 'id']);
        });

        Schema::create('definition_version', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('definition_id');
            $t->unsignedInteger('version');
            $t->jsonb('content');
            $t->uuid('created_by');
            $t->timestamp('created_at');
            $t->primary(['tenant_id', 'definition_id', 'version']);
            $t->foreign(['tenant_id', 'definition_id'])->references(['tenant_id', 'id'])->on('definition');
        });

        Schema::create('definition_publication', function (Blueprint $t) {
            $t->uuid('tenant_id');
            $t->uuid('definition_id');
            $t->unsignedInteger('version');
            $t->string('semantic_release_id');
            $t->timestamp('effective_from');
            $t->timestamp('effective_to')->nullable();
            $t->timestamp('published_at');
            $t->uuid('approved_by');
            $t->string('change_reason');
            $t->primary(['tenant_id', 'definition_id', 'version', 'effective_from']);
            $t->foreign(['tenant_id', 'definition_id', 'version'])->references(['tenant_id', 'definition_id', 'version'])->on('definition_version');
        });
        // Production: additionally enforce nonoverlapping intervals with a GiST exclusion
        // constraint on (tenant_id, definition_id) USING && (effective_from, effective_to).

        Schema::create('outbox_event', function (Blueprint $t) {
            $t->string('event_id')->primary();
            $t->string('event_type');
            $t->string('schema_version');
            $t->uuid('tenant_id');
            $t->string('aggregate_id');
            $t->unsignedBigInteger('aggregate_version');
            $t->timestamp('occurred_at');
            $t->jsonb('payload');
            $t->timestamp('dispatched_at')->nullable();
        });

        Schema::create('job', function (Blueprint $t) {
            $t->uuid('id')->primary();
            $t->string('type');
            $t->jsonb('payload');
            $t->string('state')->default('queued'); // spec 23.5
            $t->timestamps();
        });

        Schema::create('audit_event', function (Blueprint $t) {
            $t->id();
            $t->uuid('tenant_id');
            $t->uuid('actor');
            $t->string('action');
            $t->string('target');
            $t->string('result');
            $t->timestamp('occurred_at');
            $t->jsonb('context');
        });

        Schema::create('idempotency_keys', function (Blueprint $t) {
            $t->string('key')->primary();
            $t->string('request_digest');
            $t->unsignedSmallInteger('status_code');
            $t->text('response_body');
            $t->timestamp('created_at');
        });
    }

    public function down(): void
    {
        collect(['idempotency_keys', 'audit_event', 'job', 'outbox_event', 'definition_publication',
            'definition_version', 'definition', 'grain_confirmation', 'dataset_revision', 'upload', 'dataset', 'workspace', 'tenant'])
            ->each(fn ($table) => Schema::dropIfExists($table));
    }
};
