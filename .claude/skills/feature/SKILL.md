---
name: feature
description: Workflow completo de implementação de feature.
  Da análise ao PR pronto.
argument-hint: [descrição-da-feature]
---
Siga este workflow para implementar a feature "$ARGUMENTS":

1. **Análise**: Leia requisitos, identifique componentes afetados
2. **Plan**: Crie checklist detalhado em plano de implementação
3. **Branch**: Crie branch `feature/$ARGUMENTS` a partir de develop
4. **Implement**: Execute o plano, step by step
5. **Test**: Escreva e rode testes unitários e de integração
6. **Verify**: Rode typecheck, lint, e testes
7. **Commit**: Commits atômicos com mensagens descritivas