terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.regiao
}

data "aws_vpc" "padrao" {
  default = true
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_security_group" "mvp" {
  name        = "${var.nome_projeto}-sg"
  description = "Somente web publica. Nenhuma porta de administracao aberta."
  vpc_id      = data.aws_vpc.padrao.id

  ingress {
    description = "HTTP publico do MVP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "mvp" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.tipo_instancia
  vpc_security_group_ids = [aws_security_group.mvp.id]
  iam_instance_profile   = "LabInstanceProfile"

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = <<-EOF
    #!/bin/bash
    export HOME=/root
    dnf install -y docker git
    systemctl enable --now docker
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    git clone https://github.com/ricardoVergani/GS-BIGDATA-2026.git /opt/mvp
    cd /opt/mvp
    docker compose -f docker-compose.mvp.yml up -d --build
  EOF

  tags = {
    Name = var.nome_projeto
  }
}

resource "aws_eip" "mvp" {
  instance = aws_instance.mvp.id
  domain   = "vpc"
}