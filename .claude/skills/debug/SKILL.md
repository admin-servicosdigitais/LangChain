---
name: debug
description: Investigação sistemática de bugs. 
  Use quando reportarem um bug ou comportamento inesperado.
argument-hint: [descrição-do-bug]
---
Investigue o bug: $ARGUMENTS

## Processo
1. **Reproduzir**: Identifique os passos para reproduzir
2. **Isolar**: Use bisect mental — encontre o componente responsável
3. **Diagnosticar**: Leia logs, traces, e estado relevante
4. **Root cause**: Identifique a causa raiz (não o sintoma)
5. **Fix**: Implemente correção mínima e precisa
6. **Prevent**: Adicione teste que falha sem o fix
7. **Verify**: Rode testes e confirme que o bug não retorna