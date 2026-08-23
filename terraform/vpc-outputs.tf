#############################################
# Networking
#############################################

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "subnet_id" {
  description = "Public subnet ID"
  value       = aws_subnet.public.id
}

output "security_group_id" {
  description = "Security Group ID"
  value       = aws_security_group.web.id
}

#############################################
# EC2
#############################################

output "instance_id" {
  description = "EC2 Instance ID"
  value       = aws_instance.web_server.id
}

output "instance_arn" {
  description = "EC2 Instance ARN"
  value       = aws_instance.web_server.arn
}

output "instance_state" {
  description = "Current EC2 state"
  value       = aws_instance.web_server.instance_state
}

output "availability_zone" {
  description = "Availability Zone"
  value       = aws_instance.web_server.availability_zone
}

#############################################
# Connectivity
#############################################

output "public_ip" {
  description = "Public IP Address"
  value       = aws_instance.web_server.public_ip
}

output "private_ip" {
  description = "Private IP Address"
  value       = aws_instance.web_server.private_ip
}

output "public_dns" {
  description = "Public DNS Name"
  value       = aws_instance.web_server.public_dns
}

#############################################
# SSH
#############################################

output "ssh_command" {
  description = "SSH command to connect"

  value = format(
    "ssh -i ~/.ssh/web-key-llm-project ubuntu@%s",
    aws_instance.web_server.public_ip
  )
}

#############################################
# Useful URLs
#############################################

output "http_url" {
  description = "HTTP URL"

  value = format(
    "http://%s",
    aws_instance.web_server.public_ip
  )
}

output "https_url" {
  description = "HTTPS URL"

  value = format(
    "https://%s",
    aws_instance.web_server.public_ip
  )
}

#############################################
# AWS Console Links
#############################################

output "ec2_console_url" {
  description = "AWS Console EC2 page"

  value = format(
    "https://ap-southeast-1.console.aws.amazon.com/ec2/home?region=ap-southeast-1#InstanceDetails:instanceId=%s",
    aws_instance.web_server.id
  )
}

output "vpc_console_url" {
  description = "AWS Console VPC page"

  value = "https://ap-southeast-1.console.aws.amazon.com/vpcconsole/home?region=ap-southeast-1"
}