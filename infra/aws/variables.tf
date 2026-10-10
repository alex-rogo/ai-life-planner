variable "aws_region" {
  description = "AWS region for the application stack."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Short name used to prefix AWS resources."
  type        = string
  default     = "ai-planner"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "production"
}

variable "image_tag" {
  description = "Container tag deployed by both ECS services."
  type        = string
  default     = "latest"
}

variable "allowed_ipv4_cidrs" {
  description = "Public IPv4 CIDR ranges allowed to use the single-user application. Do not use 0.0.0.0/0."
  type        = list(string)

  validation {
    condition = (
      length(var.allowed_ipv4_cidrs) > 0 &&
      !contains(var.allowed_ipv4_cidrs, "0.0.0.0/0") &&
      alltrue([for cidr in var.allowed_ipv4_cidrs : can(cidrhost(cidr, 0))])
    )
    error_message = "Provide at least one valid restricted IPv4 CIDR; 0.0.0.0/0 is not allowed."
  }
}

variable "service_desired_count" {
  description = "Initial task count for each ECS service. Use zero during the first infrastructure bootstrap."
  type        = number
  default     = 1

  validation {
    condition     = var.service_desired_count >= 0
    error_message = "service_desired_count must be zero or greater."
  }
}

variable "service_max_count" {
  description = "Maximum task count used by ECS target tracking."
  type        = number
  default     = 4
}

variable "frontend_cpu" {
  type    = number
  default = 512
}

variable "frontend_memory" {
  type    = number
  default = 1024
}

variable "backend_cpu" {
  type    = number
  default = 1024
}

variable "backend_memory" {
  type    = number
  default = 2048
}

variable "database_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_multi_az" {
  description = "Enable a standby RDS instance in another Availability Zone."
  type        = bool
  default     = false
}

variable "database_deletion_protection" {
  description = "Protect the RDS instance from accidental deletion."
  type        = bool
  default     = true
}

variable "ai_mode" {
  description = "Assistant mode: demo or gemini."
  type        = string
  default     = "demo"

  validation {
    condition     = contains(["demo", "gemini"], var.ai_mode)
    error_message = "ai_mode must be demo or gemini."
  }
}

variable "gemini_model" {
  type    = string
  default = "gemini-2.5-flash"
}

variable "gemini_api_key_secret_arn" {
  description = "Optional Secrets Manager ARN containing the Gemini API key as plain text. Required when ai_mode is gemini."
  type        = string
  default     = ""

  validation {
    condition     = var.ai_mode != "gemini" || var.gemini_api_key_secret_arn != ""
    error_message = "gemini_api_key_secret_arn is required when ai_mode is gemini."
  }
}

variable "log_retention_days" {
  type    = number
  default = 30
}
