---
name: commit
description: Review automático + commit com mensagem descritiva.
allowed-tools: Bash(git:*)
---
1. Verifique staged changes: !`git diff --cached --stat`
2. Analise se há:
   - Console.log / print de debug
   - Código comentado
   - TODOs que deveriam ser resolvidos
   - .env ou secrets acidentais
3. Se limpo, crie commit com mensagem descritiva: $ARGUMENTS
4. Se encontrar problemas, reporte antes de commitar