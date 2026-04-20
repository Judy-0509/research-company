param(
    [Parameter(Mandatory)][string]$NewKey,
    [string]$BaseUrl = "http://localhost:3100",
    [string]$AdminToken = $env:PAPERCLIP_ADMIN_TOKEN
)

$CompanyId = "ca76e1f0-7d21-42ac-9524-3def6a302b5d"
$Headers = @{ "Content-Type" = "application/json" }
if ($AdminToken) { $Headers["Authorization"] = "Bearer $AdminToken" }

$agents = Invoke-RestMethod "$BaseUrl/api/companies/$CompanyId/agents" -Headers $Headers
$kimiAgents = $agents | Where-Object { $_.adapterType -eq "kimi_api" }

foreach ($agent in $kimiAgents) {
    $current = Invoke-RestMethod "$BaseUrl/api/agents/$($agent.id)" -Headers $Headers
    $mergedConfig = $current.adapterConfig.PSObject.Copy()
    $mergedConfig.apiKey = $NewKey

    $body = @{ adapterConfig = $mergedConfig } | ConvertTo-Json -Depth 10
    Invoke-RestMethod "$BaseUrl/api/agents/$($agent.id)" -Method Patch -Headers $Headers -Body $body
    Write-Host "Updated: $($agent.name) ($($agent.id))"
}
Write-Host "Done. $($kimiAgents.Count) agents updated."
