# AWS deployment

Terraform deploys AI Planner to CloudFront, AWS WAF, an Application Load Balancer, ECS Fargate, and RDS PostgreSQL. The containers and database run in private subnets. ECR stores images, Secrets Manager stores the database password, and CloudWatch receives container logs.

The application has no account system. AWS WAF therefore blocks every address except the IPv4 ranges listed in `allowed_ipv4_cidrs`. This is suitable for the current single-user design. Do not use `0.0.0.0/0`.

## Requirements

- An AWS account and AWS CLI credentials with permission to create the stack
- Terraform 1.8 or newer
- Docker Desktop
- A public IPv4 address, written as a `/32` CIDR

These resources incur AWS charges, including while the app is idle. The NAT gateway, load balancer, Fargate services, and RDS instance are the main fixed costs.

## Deploy

From the repository root in PowerShell:

```powershell
Copy-Item infra/aws/terraform.tfvars.example infra/aws/terraform.tfvars
```

Edit `infra/aws/terraform.tfvars` and replace `203.0.113.10/32` with your public IPv4 address followed by `/32`. Then run:

```powershell
.\scripts\deploy-aws.ps1
```

The script creates the infrastructure with zero running tasks, builds and pushes both images, starts one task for each service, and prints the CloudFront URL. Later releases can skip the bootstrap apply:

```powershell
.\scripts\deploy-aws.ps1 -SkipBootstrap
```

Terraform state contains infrastructure details and the generated origin header. Keep it private. For shared or production use, configure an encrypted S3 backend with state locking before the first deployment.

## Gemini

Create a Secrets Manager secret whose value is only the Gemini API key. Set these values in `terraform.tfvars`:

```hcl
ai_mode                  = "gemini"
gemini_api_key_secret_arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:ai-planner/gemini-AbCdEf"
```

The ECS execution role can read that secret. The key is not stored in a task definition or committed to Git.

## Access and operations

- Update `allowed_ipv4_cidrs` and run `terraform apply` when your public IP changes.
- View application logs in `/ecs/ai-planner-production/frontend` and `/ecs/ai-planner-production/backend`.
- RDS deletion protection is enabled by default. Disable it deliberately before destroying the stack.
- The Windows activity companion remains local-only because it sends activity to a loopback API. It is not part of the AWS stack.
