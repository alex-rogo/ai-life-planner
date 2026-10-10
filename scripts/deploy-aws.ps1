param(
    [string]$Region = "us-west-2"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$terraformDirectory = Join-Path $repositoryRoot "infra/aws"

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    throw "Terraform 1.8 or newer is required."
}

Push-Location $terraformDirectory
try {
    terraform init
    if ($LASTEXITCODE -ne 0) { throw "Terraform setup failed." }

    terraform apply -var "aws_region=$Region"
    if ($LASTEXITCODE -ne 0) { throw "AWS deployment was cancelled or failed." }

    $website = terraform output -raw website
    $username = terraform output -raw username
    $password = terraform output -raw password
    $authorization = [Convert]::ToBase64String(
        [Text.Encoding]::ASCII.GetBytes("${username}:${password}")
    )

    Write-Host "Waiting for the server to finish setting up..."
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $website -Headers @{ Authorization = "Basic $authorization" } -UseBasicParsing -TimeoutSec 10
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 10
        }
    }

    Write-Host "Website: $website"
    Write-Host "Username: $username"
    Write-Host "Password: $password"
    if (-not $ready) {
        Write-Host "The server is still setting up. Try the website again in a few minutes."
    }
}
finally {
    Pop-Location
}
