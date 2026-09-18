<?php

namespace App\Services;

use Illuminate\Support\Facades\DB;

class SemanticService
{
    public function listDefinitions(string $tenantId): array
    {
        $rows = DB::table('definition_version as dv')
            ->join('definition as d', fn ($j) => $j->on('d.tenant_id', '=', 'dv.tenant_id')->on('d.id', '=', 'dv.definition_id'))
            ->leftJoin('definition_publication as dp', fn ($j) => $j
                ->on('dp.tenant_id', '=', 'dv.tenant_id')
                ->on('dp.definition_id', '=', 'dv.definition_id')
                ->on('dp.version', '=', 'dv.version')
                ->whereNull('dp.effective_to'))
            ->where(['dv.tenant_id' => $tenantId, 'd.kind' => 'metric'])
            ->orderBy('dv.definition_id')
            ->orderBy('dv.version')
            ->select('dv.definition_id', 'dv.version', 'dv.content', 'dp.version as active_version')
            ->get();

        // name/kind live inside the immutable content JSON; status is derived from
        // an open (effective_to IS NULL) publication interval.
        return $rows->map(fn ($r) => array_merge(json_decode($r->content, true), [
            'metric_id' => $r->definition_id,
            'version' => (int) $r->version,
            'status' => $r->active_version !== null ? 'approved' : 'proposed',
        ]))->all();
    }

    public function propose(string $tenantId, string $userId, array $data): array
    {
        return DB::transaction(function () use ($tenantId, $userId, $data) {
            DB::table('definition')->insertOrIgnore([
                'tenant_id' => $tenantId, 'id' => $data['metric_id'], 'kind' => 'metric', 'created_by' => $userId,
            ]);
            $next = (int) DB::table('definition_version')->where(['tenant_id' => $tenantId, 'definition_id' => $data['metric_id']])->max('version') + 1;
            DB::table('definition_version')->insert([
                'tenant_id' => $tenantId,
                'definition_id' => $data['metric_id'],
                'version' => $next,
                'content' => json_encode($data),
                'created_by' => $userId,
                'created_at' => now(),
            ]);

            return array_merge($data, ['version' => $next, 'status' => 'proposed']);
        });
    }

    /** Approver must differ from proposer; nonoverlapping publication enforced by exclusion on insert. */
    public function approve(string $tenantId, string $userId, string $metricId, array $data): array
    {
        $version = DB::table('definition_version')->where(['tenant_id' => $tenantId, 'definition_id' => $metricId, 'version' => $data['version']])->first();
        abort_if($version === null, 404);
        abort_if($version->created_by === $userId, 403, json_encode(['code' => 'self_approval_not_allowed']));

        return DB::transaction(function () use ($tenantId, $userId, $metricId, $data, $version) {
            // Close any prior publication interval, then insert the new one without overlap.
            DB::table('definition_publication')->where(['tenant_id' => $tenantId, 'definition_id' => $metricId])->whereNull('effective_to')->update([
                'effective_to' => now(), 'updated_at' => now(),
            ]);
            DB::table('definition_publication')->insert([
                'tenant_id' => $tenantId,
                'definition_id' => $metricId,
                'version' => $data['version'],
                'semantic_release_id' => $data['semantic_release_id'] ?? 'release-dev',
                'effective_from' => now(),
                'effective_to' => null,
                'published_at' => now(),
                'approved_by' => $userId,
                'change_reason' => $data['change_reason'],
            ]);
            DB::table('audit_event')->insert([
                'tenant_id' => $tenantId, 'actor' => $userId, 'action' => 'definition.approve',
                'target' => "$metricId@v{$data['version']}", 'result' => 'success', 'occurred_at' => now(),
                'context' => json_encode(['change_reason' => $data['change_reason']]),
            ]);

            return array_merge(json_decode($version->content, true), ['metric_id' => $metricId, 'version' => $data['version'], 'status' => 'approved']);
        });
    }

    public function withdraw(string $tenantId, string $userId, string $metricId, array $data): void
    {
        DB::table('definition_publication')->where(['tenant_id' => $tenantId, 'definition_id' => $metricId, 'version' => $data['version']])->whereNull('effective_to')->update(['effective_to' => now()]);
        DB::table('audit_event')->insert([
            'tenant_id' => $tenantId, 'actor' => $userId, 'action' => 'definition.withdraw',
            'target' => "$metricId@v{$data['version']}", 'result' => 'success', 'occurred_at' => now(),
            'context' => json_encode($data),
        ]);
    }
}
