terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "server_size" {
  description = "Lightsail plan. small_3_0 is the 2 GB plan."
  type        = string
  default     = "small_3_0"
}

variable "repository_url" {
  type    = string
  default = "https://github.com/alex-rogo/ai-life-planner.git"
}

resource "random_password" "app" {
  length  = 20
  special = false
}

resource "random_password" "database" {
  length  = 32
  special = false
}

resource "aws_lightsail_static_ip" "app" {
  name = "ai-planner-ip"
}

resource "aws_lightsail_instance" "app" {
  name              = "ai-planner"
  availability_zone = "${var.aws_region}a"
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = var.server_size

  user_data = templatefile("${path.module}/setup.sh.tftpl", {
    app_password      = random_password.app.result
    database_password = random_password.database.result
    public_ip         = aws_lightsail_static_ip.app.ip_address
    repository_url    = var.repository_url
  })
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name
}

resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
}

locals {
  hostname = "${replace(aws_lightsail_static_ip.app.ip_address, ".", "-")}.sslip.io"
}

output "website" {
  value = "https://${local.hostname}"
}

output "username" {
  value = "planner"
}

output "password" {
  value     = random_password.app.result
  sensitive = true
}

output "server_ip" {
  value = aws_lightsail_static_ip.app.ip_address
}
