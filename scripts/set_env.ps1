# Usage: . .\scripts\set_env.ps1
# Sets required environment variables for local runs

$env:SUPABASE_URL = "https://supabase.bildee.com.br"
$env:SUPABASE_KEY = "<SERVICE_ROLE_JWT>"

Write-Host "SUPABASE_URL and SUPABASE_KEY set in current session."