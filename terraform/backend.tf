# Terraform backend configuration
# Note: S3 bucket and DynamoDB table must be created manually first
# or comment out this block for initial deployment

# terraform {
#   backend "s3" {
#     bucket         = "insuremail-ai-terraform-state"
#     key            = "terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "insuremail-ai-terraform-locks"
#     encrypt        = true
#   }
# }
