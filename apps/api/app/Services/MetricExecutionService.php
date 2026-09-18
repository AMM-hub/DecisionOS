<?php

namespace App\Services;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

class MetricExecutionService
{
    public function __construct(private readonly WorkerClient $worker) {}

    /**
     * Resolves the approved definition version + published dataset revision, then
     * executes in the bounded analytics worker (DuckDB over authorized snapshots).
     * Compilation and statistics never happen in the web request process.
     */
    public function query(string $tenantId, string $userId, array $request): array
    {
        $publication = DB::table('definition_publication')
            ->where(['tenant_id' => $tenantId, 'definition_id' => $request['metric_id']])
            ->whereNull('effective_to')
            ->first();
        abort_if($publication === null, 422, json_encode(['code' => 'metric_not_certified', 'message' => 'No approved definition is currently effective']));

        $dataset = DB::table('dataset')->where(['tenant_id' => $tenantId, 'id' => $request['dataset_id'] ?? 'support_tickets'])->first();
        abort_if($dataset === null, 404);
        abort_if($dataset->published_revision === null, 422, json_encode(['code' => 'insufficient_data', 'message' => 'No published dataset revision']));

        $result = $this->worker->call('metric.query', [
            'tenant_id' => $tenantId,
            'request_id' => (string) Str::uuid(),
            'metric_request' => $request,
            'definition_version' => ['id' => $publication->definition_id, 'version' => $publication->version, 'content' => json_decode($publication->content ?? 'null', true)],
            'semantic_release_id' => $publication->semantic_release_id,
            'dataset_revision' => $dataset->published_revision,
            'permissions_checked_at' => now()->toIso8601String(),
        ]);

        DB::table('audit_event')->insert([
            'tenant_id' => $tenantId, 'actor' => $userId, 'action' => 'metric.query',
            'target' => $request['metric_id'], 'result' => $result['status'], 'occurred_at' => now(),
            'context' => json_encode(['evidence_ref' => $result['evidence_ref'] ?? null]),
        ]);

        return $result;
    }
}
