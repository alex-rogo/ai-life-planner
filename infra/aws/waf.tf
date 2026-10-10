resource "aws_wafv2_ip_set" "allowed" {
  provider           = aws.us_east_1
  name               = "${local.name}-allowed-ipv4"
  description        = "IPv4 ranges allowed to use AI Planner"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = var.allowed_ipv4_cidrs
}

resource "aws_wafv2_web_acl" "app" {
  provider    = aws.us_east_1
  name        = local.name
  description = "Restrict the single-user application to approved IPv4 ranges"
  scope       = "CLOUDFRONT"

  default_action {
    block {}
  }

  rule {
    name     = "allow-approved-ipv4"
    priority = 1

    action {
      allow {}
    }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.allowed.arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-allowed-ipv4"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}
