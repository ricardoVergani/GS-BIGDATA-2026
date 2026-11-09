output "url_mvp" {
  value = "http://${aws_eip.mvp.public_ip}"
}

output "instance_id" {
  value = aws_instance.mvp.id
}