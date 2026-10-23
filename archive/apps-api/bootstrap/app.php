<?php

use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware) {
        $middleware->alias([
            'tenant.context' => \App\Http\Middleware\ResolveTenantContext::class,
            'idempotency' => \App\Http\Middleware\EnforceIdempotency::class,
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions) {
        // Error envelope per spec 23.4: no paths, secrets, stack traces, or foreign tenant names.
    })->create();
