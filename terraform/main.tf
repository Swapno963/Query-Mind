
########################################################
# IAM role assumed by the EC2 instance
########################################################

resource "aws_iam_role" "production_ec2_ecr_pull" {
  name = "production-ec2-ecr-pull-role"

  # Allow EC2 to assume this IAM role.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

########################################################
# Grant permission to pull private ECR images
########################################################

resource "aws_iam_role_policy_attachment" "production_ec2_ecr_pull" {
  role = aws_iam_role.production_ec2_ecr_pull.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly"
}

########################################################
# EC2 requires an instance profile containing the role
########################################################

resource "aws_iam_instance_profile" "production_ec2" {
  name = "production-ec2-instance-profile"
  role = aws_iam_role.production_ec2_ecr_pull.name
}
#############################################
# VPC
#############################################

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "production-vpc"
  }
}

#############################################
# Internet Gateway
#############################################

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "production-igw"
  }
}

#############################################
# Public Subnet
#############################################

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "ap-southeast-1a"
  map_public_ip_on_launch = true

  tags = {
    Name = "public-subnet"
  }
}

#############################################
# Public Route Table
#############################################

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "public-route-table"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

#############################################
# SSH Key
#############################################

resource "aws_key_pair" "web_key" {
  key_name   = "web-key-llm-project"
  public_key = file("/root/.ssh/web-key-llm-project.pub")
}

#############################################
# Security Group
#############################################

resource "aws_security_group" "web" {
  name        = "web-security-group"
  description = "Allow SSH, HTTP and HTTPS"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"

    # Change to your office/home IP in production
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"

    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"

    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"

    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "web-security-group"
  }
}

#############################################
# EC2 Instance
#############################################

# data "aws_ami" "ubuntu" {
#   most_recent = true

#   owners = ["099720109477"] # Canonical

#   filter {
#     name   = "name"
#     values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
#   }

#   filter {
#     name   = "virtualization-type"
#     values = ["hvm"]
#   }
# }

data "aws_ami" "ubuntu" {
  most_recent = true

  owners = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
# "t4g.micro"
resource "aws_instance" "web_server" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public.id
  key_name               = aws_key_pair.web_key.key_name
  vpc_security_group_ids = [aws_security_group.web.id]

  associate_public_ip_address = true
  # Attach the IAM role to the EC2 instance.
  iam_instance_profile = aws_iam_instance_profile.production_ec2.name
  user_data            = <<-EOF
#!/bin/bash

set -euxo pipefail
exec > >(tee /var/log/user-data.log | logger -t user-data) 2>&1

########################################################
# Update packages
########################################################

apt-get update

########################################################
# Install prerequisites
########################################################

apt-get install -y \
    ca-certificates \
    curl \
    gnupg

########################################################
# Add Docker's official GPG key
########################################################

install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

chmod a+r /etc/apt/keyrings/docker.gpg

########################################################
# Add Docker repository
########################################################

echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
| tee /etc/apt/sources.list.d/docker.list > /dev/null

########################################################
# Install Docker Engine + Compose + Buildx
########################################################

apt-get update

apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

########################################################
# Enable Docker
########################################################

systemctl enable docker
systemctl start docker

########################################################
# Allow ubuntu user to use Docker
########################################################

usermod -aG docker ubuntu

########################################################
# Create application directory
########################################################

mkdir -p /opt/app
chown -R ubuntu:ubuntu /opt/app



echo "Docker installation completed successfully."

# newly added
apt-get install -y amazon-ecr-credential-helper
mkdir -p /home/ubuntu/.docker

cat >/home/ubuntu/.docker/config.json <<CONFIG
{
  "credsStore": "ecr-login"
}
CONFIG

chown -R ubuntu:ubuntu /home/ubuntu/.docker

EOF

  tags = {
    Name = "production-web-server"
  }
}

