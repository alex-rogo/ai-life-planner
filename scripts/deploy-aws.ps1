param(
    [string]$Region = "us-west-2",
    [string]$Environment = "production",
    [string]$ImageTag = "",
    [switch]$SkipBootstrap
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$terraformDirectory = Join-Path $repositoryRoot "infra/aws"

foreach ($command in @("aws", "docker", "terraform")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required and was not found on PATH."
    }
}

if (-not (Test-Path (Join-Path $terraformDirectory "terraform.tfvars"))) {
    throw "Create infra/aws/terraform.tfvars from terraform.tfvars.example before deploying."
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = (git -C $repositoryRoot rev-parse --short HEAD).Trim()
}

Push-Location $terraformDirectory
try {
    terraform init

    if (-not $SkipBootstrap) {
        terraform apply `
            -var "aws_region=$Region" `
            -var "environment=$Environment" `
            -var "image_tag=$ImageTag" `
            -var "service_desired_count=0"
    }

    $frontendRepository = terraform output -raw frontend_repository_url
    $backendRepository = terraform output -raw backend_repository_url
    $registry = $frontendRepository.Split("/")[0]

    aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry

    docker build --build-arg API_BASE_URL=http://backend.ai-planner.local:8000 -t "${frontendRepository}:${ImageTag}" (Join-Path $repositoryRoot "frontend")
    docker build -t "${backendRepository}:${ImageTag}" (Join-Path $repositoryRoot "backend")
    docker push "${frontendRepository}:${ImageTag}"
    docker push "${backendRepository}:${ImageTag}"

    terraform apply `
        -var "aws_region=$Region" `
        -var "environment=$Environment" `
        -var "image_tag=$ImageTag" `
        -var "service_desired_count=1"

    terraform output application_url
}
finally {
    Pop-Location
}
