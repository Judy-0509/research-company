param(
  [string]$CompanyId = "ca76e1f0-7d21-42ac-9524-3def6a302b5d",
  [string]$BaseUrl = "http://localhost:3100",
  [string]$PromptPath = "$PSScriptRoot\prompts\online_researcher_prompt.json"
)

$Headers = @{ "Content-Type" = "application/json" }

$payload = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8 | ConvertFrom-Json
$systemPrompt = $payload.systemPrompt
if (-not $systemPrompt) { throw "Prompt file must contain systemPrompt" }

$agents = Invoke-RestMethod "$BaseUrl/api/companies/$CompanyId/agents" -Headers $Headers
$matches = @($agents | Where-Object { $_.name -eq "Online Researcher" })
if ($matches.Count -ne 1) { throw "Expected exactly one 'Online Researcher', found $($matches.Count)" }

$body = @{ adapterConfig = @{ systemPrompt = $systemPrompt } } | ConvertTo-Json -Depth 5
Invoke-RestMethod "$BaseUrl/api/agents/$($matches[0].id)" -Method Patch -Headers $Headers -Body $body | Out-Null

Write-Host "Online Researcher prompt updated: $($matches[0].id)"
