output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "links_table" {
  value = aws_dynamodb_table.links.name
}
