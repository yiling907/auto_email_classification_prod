variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "bedrock_models" {
  description = "List of Bedrock model IDs to enable"
  type        = list(string)
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
