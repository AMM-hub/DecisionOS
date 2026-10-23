<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Symfony\Component\HttpFoundation\Response;

/**
 * Idempotency keys scoped to tenant + principal + endpoint + request digest (spec 23.1).
 * Same key with changed payload returns 409.
 */
class EnforceIdempotency
{
    public function handle(Request $request, Closure $next): Response
    {
        $key = $request->header('Idempotency-Key');
        if ($key === null) {
            return $next($request);
        }

        $scope = sha1(json_encode([
            'tenant' => $request->attributes->get('tenant_id'),
            'principal' => $request->user()?->id,
            'endpoint' => $request->method().':'.$request->path(),
            'digest' => sha1($request->getContent()),
        ]));

        $existing = DB::table('idempotency_keys')->where('key', "$key:$scope")->first();
        if ($existing !== null) {
            $digestMatches = $existing->request_digest === sha1($request->getContent());
            abort_unless($digestMatches, 409, json_encode(['code' => 'idempotency_payload_conflict']));

            return response($existing->response_body, $existing->status_code)
                ->header('Idempotent-Replay', 'true');
        }

        $response = $next($request);
        if ($response->isSuccessful()) {
            DB::table('idempotency_keys')->insert([
                'key' => "$key:$scope",
                'request_digest' => sha1($request->getContent()),
                'status_code' => $response->getStatusCode(),
                'response_body' => $response->getContent(),
                'created_at' => now(),
            ]);
        }

        return $response;
    }
}
