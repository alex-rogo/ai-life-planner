locals {
  name = "${var.project_name}-${var.environment}"

  ecr_lifecycle_policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the most recent 20 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })

  common_environment = [
    { name = "DATABASE_HOST", value = aws_db_instance.postgres.address },
    { name = "DATABASE_PORT", value = tostring(aws_db_instance.postgres.port) },
    { name = "DATABASE_NAME", value = aws_db_instance.postgres.db_name },
    { name = "DATABASE_USER", value = aws_db_instance.postgres.username },
    { name = "AI_MODE", value = var.ai_mode },
    { name = "GEMINI_MODEL", value = var.gemini_model },
    { name = "CORS_ORIGINS", value = "https://${aws_cloudfront_distribution.app.domain_name}" }
  ]

  common_secrets = concat(
    [{
      name      = "DATABASE_PASSWORD"
      valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:password::"
    }],
    var.gemini_api_key_secret_arn == "" ? [] : [{
      name      = "GEMINI_API_KEY"
      valueFrom = var.gemini_api_key_secret_arn
    }]
  )
}
