variable "env" {
  description = "Environment name, e.g. dev or prod"
  type        = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "base_url" {
  description = "Public base URL for short links. Leave empty to use the API Gateway URL."
  type        = string
  default     = ""
}

variable "rate_limit_per_minute" {
  description = "Links each caller can create per minute"
  type        = number
  default     = 20
}

variable "alert_email" {
  description = "Email for CloudWatch alarms (optional)"
  type        = string
  default     = ""
}
