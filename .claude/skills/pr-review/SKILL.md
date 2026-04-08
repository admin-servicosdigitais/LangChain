---
name: pr-review
description: Review completo de Pull Request com checklist estruturado.
context: fork
agent: code-reviewer
---
## Contexto do PR
- Branch base detectada: !`git remote show origin | grep 'HEAD branch' | awk '{print $NF}'`
- Diff: !`git diff $(git merge-base HEAD origin/HEAD)...HEAD`
- Arquivos alterados: !`git diff --name-only $(git merge-base HEAD origin/HEAD)...HEAD`
- Commits: !`git log --oneline $(git merge-base HEAD origin/HEAD)...HEAD`

## Checklist de Review
1. Mudanças fazem sentido em relação ao objetivo?
2. Testes adequados para novos cenários?
3. Types corretos, sem any ou type assertions desnecessárias?
4. Error handling completo?
5. Performance: queries N+1, re-renders, memory leaks?
6. Segurança: input validation, auth checks?
7. Breaking changes documentadas?

Classifique: 🟢 Approved | 🟡 Request Changes | 🔴 Blocked