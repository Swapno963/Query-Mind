# Input Variables

# AWS Region
variable "aws_region" {
  description = "Region where AWS Resources will be created"
  type        = string
  default     = "ap-southeast-1"
}

# Environment Variable
variable "environment" {
  description = "Environment Variable used as a prefix (e.g., dev, prod)"
  type        = string
  default     = "dev"
}

# Business Division
variable "organization" {
  description = "Organization for organizational purposes"
  type        = string
  default     = "poridhi"
}
