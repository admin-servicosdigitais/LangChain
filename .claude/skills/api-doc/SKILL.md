---
name: api-doc
description: Gera documentação de API endpoint a partir do código.
argument-hint: [path-do-endpoint]
allowed-tools: Read, Grep, Glob
---
Documente o endpoint em $ARGUMENTS:

1. Leia o handler, schema de validação, e middleware
2. Gere documentação incluindo:
   - Método HTTP e URL
   - Headers obrigatórios
   - Request body (com tipos e exemplos)
   - Response (sucesso e erros possíveis)
   - Rate limits e autenticação necessária
3. Formato: OpenAPI-compatible em Markdown