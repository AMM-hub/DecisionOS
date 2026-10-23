<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * Resolves the effective tenant + workspace scope from authenticated membership.
 * LOCAL DEMO NOTE: header-based context below is only for contract testing without
 * a provisioned identity provider. Production must derive tenant from membership
 * records server-side and never trust client-supplied identity (spec 10.3, 24).
 */
class ResolveTenantContext
{
    public function handle(Request $request, Closure $next): Response
    {
        if (app()->environment('local') && config('decisionos.trust_demo_headers')) {
            $request->attributes->set('tenant_id', (string) $request->header('X-Tenant'));
            $request->attributes->set('workspace_id', (string) $request->header('X-Workspace'));
            // Demo identity resolver so ->user()->id works without a provisioned
            // user store. NEVER enable outside local contract-testing mode.
            $demoUser = (object) ['id' => (string) $request->header('X-User', 'demo.user')];
            $request->setUserResolver(fn () => $demoUser);

            return $next($request);
        }

        $user = $request->user();
        abort_if($user === null, 401);
        $membership = $user->activeMemberships()->first();
        abort_if($membership === null, 403, json_encode(['code' => 'no_active_membership']));
        $request->attributes->set('tenant_id', $membership->tenant_id);
        $request->attributes->set('workspace_id', $request->header('X-Workspace') ?? $membership->default_workspace_id);
        abort_unless($user->belongsWorkspace($request->attributes->get('workspace_id')), 404);

        return $next($request);
    }
}
