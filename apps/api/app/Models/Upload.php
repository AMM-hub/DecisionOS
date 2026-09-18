<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Upload extends Model
{
    protected $keyType = 'string';
    public $incrementing = false;
    protected $fillable = [
        'id', 'tenant_id', 'workspace_id', 'created_by', 'original_filename',
        'declared_size_bytes', 'quarantine_key', 'quarantine_url', 'status', 'expires_at',
    ];
    protected $casts = [
        'expires_at' => 'datetime',
        'parse_preview' => 'array',
        'scan_result' => 'array',
    ];

    public function getRouteKeyName(): string
    {
        return 'id';
    }
}
