# ADR-006: Estratégia de Deploy e IaC

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** Todos os módulos (deploy), CI/CD pipeline, gestão de ambientes

## Contexto

O sistema tem 6 Lambda functions, 8 ECS task definitions (agentes), 1 Aurora Serverless v2, 1 RDS Proxy, múltiplas tabelas DynamoDB, filas SQS FIFO/Standard, EventBridge rules, Step Functions, API Gateway HTTP APIs, e ECR repositories. Gerenciar isso manualmente ou via Console é inviável e não reproduzível.

Constraints:
- Time pequeno (2-4 devs): IaC deve ser simples de operar e auditar
- Ambientes separados: dev, staging, prod — state isolado, sem risco de mudança em dev afetar prod
- Pipeline CI/CD: deploy de Lambda deve ser rápido (< 5 min), não bloquear desenvolvimento
- Secrets: nunca armazenados no repositório nem no Terraform state
- Blue/green deploy: Lambda em produção não pode ter downtime em deploys

## Opções Consideradas

### Opção A: AWS CDK (Python)

**Prós:**
- IaC em Python — mesma linguagem do projeto, sem HCL para aprender
- Constructs de alto nível (ex: `PythonFunction` da CDK para Lambda em Python)
- `cdk diff` equivalente ao `terraform plan`
- Deploy direto: `cdk deploy`

**Contras:**
- CloudFormation como intermediário: `cdk synth` gera templates CF que são aplicados. Stack limit de CF (500 resources) pode ser atingido
- CloudFormation rollback automático em falha pode reverter mudanças boas junto com as ruins
- Abstrações de alto nível do CDK escondem o que está sendo criado — difícil debugar problemas de permissão
- Estabilidade: CDK tem breaking changes frequentes entre minor versions
- Drift detection: CloudFormation não detecta mudanças feitas fora do IaC tão bem quanto Terraform

### Opção B: Serverless Framework

**Prós:**
- Otimizado para Lambda: deploy de função com um comando
- Plugin ecosystem rico (serverless-python-requirements, serverless-offline)
- YAML simples para definir funções, events, resources

**Contras:**
- Limitado ao ecossistema Lambda/API Gateway — ECS Fargate (para agentes) requer Terraform adicional
- Não gerencia Aurora, RDS Proxy, DynamoDB de forma idiomática
- Versão 4 mudou para modelo de negócio pago para times — custo adicional
- Dois sistemas se houver recursos fora do scope do Serverless Framework

### Opção C: Terraform com módulos parametrizados

**Prós:**
- Determinismo total: `plan` mostra exatamente o que será criado/modificado/destruído
- Módulos reutilizáveis: `lambda-function` encapsula ECR, Lambda, IAM, Alias, Provisioned Concurrency
- State em S3 com versionamento + DynamoDB locking para concorrência segura
- Workspaces: dev/staging/prod com state isolado, mesmos módulos, variáveis diferentes
- Drift detection: `terraform plan` detecta mudanças feitas fora do IaC
- Gerencia todos os recursos do sistema: Lambda, ECS, Aurora, DynamoDB, SQS, EventBridge, API Gateway

**Contras:**
- HCL: linguagem separada, não é Python (baixo impacto — HCL é simples)
- Verbosidade: ~1500 linhas de Terraform para o sistema completo
- `terraform apply` pode demorar 3-8 minutos para mudanças grandes (Lambda update: ~30s)

## Decisão

**Escolha: Opção C — Terraform com módulos parametrizados + GitHub Actions CI/CD**

Terraform é escolhido pela maturidade, determinismo do `plan/apply` e ausência de layers de abstração que escondem o que está sendo criado. O módulo `lambda-function` parametrizado encapsula ECR repo, Lambda function (Container Image), IAM role, Log Group, Alias, Provisioned Concurrency config, e SQS event source mapping.

**Estrutura de ambientes:** Terraform Workspaces (`dev`, `staging`, `prod`) com variáveis de ambiente em `terraform.tfvars` por workspace. State em S3 bucket com versionamento + DynamoDB table para locking.

**Pipeline CI/CD (GitHub Actions):**
1. PR aberto → `terraform plan` automático, output postado como comentário no PR
2. Merge em `main` → deploy automático em `dev`
3. Tag `v*` → deploy em `staging` com aprovação manual → deploy em `prod` com aprovação manual
4. Deploy de Lambda: `terraform apply` atualiza a função após ECR image push
5. Deploy de agente ECS: `terraform apply` atualiza task definition; nova task lançada na próxima execução scheduled

**Blue/Green via Lambda Aliases:** alias `live` aponta para versão anterior; `terraform apply` cria nova versão e move alias apenas após health check.

## Consequências

**Positivas:**
- `terraform plan` em CI previne mudanças acidentais — visibilidade total antes de aplicar
- Módulo reutilizável para Lambda reduz código de IaC de 200 linhas para ~15 por função
- S3 backend com versionamento permite rollback de state em caso de `apply` problemático
- Workspaces isolam completamente dev/staging/prod

**Negativas / Trade-offs:**
- Verbosidade HCL: ~1500 linhas totais (aceitável, bem organizado em módulos)
- Secrets via AWS Secrets Manager requerem referência em Terraform com `data.aws_secretsmanager_secret_version`
- Deploy de nova imagem Docker passa por `terraform apply` — não tem hotswap nativo de Lambda

**Riscos e Mitigações:**
- Risco: State corruption no S3 se dois applies rodarem simultaneamente → Mitigação: DynamoDB locking previne applies concorrentes; GitHub Actions `concurrency` group por workspace
- Risco: Deploy de nova imagem Docker quebra Lambda em produção → Mitigação: Blue/green via Lambda Aliases; `live` alias move apenas após health check via `aws lambda invoke --function-name health-check`
- Risco: Secrets em `terraform.tfvars` commitados acidentalmente → Mitigação: `.gitignore` inclui `*.tfvars` locais; CI usa variáveis de ambiente do GitHub Secrets; `git-secrets` no pre-commit hook

## Implementação

```
infrastructure/
├── modules/
│   ├── lambda-function/
│   │   ├── main.tf           # ECR, Lambda, IAM, LogGroup, Alias, PC
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── ecs-agent/
│   │   ├── main.tf           # Task Definition, IAM, CloudWatch, EventBridge Schedule
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── sqs-queue/
│   │   ├── main.tf           # Queue, DLQ, Policy, CloudWatch Alarm
│   │   └── variables.tf
│   └── aurora-serverless/
│       ├── main.tf           # Aurora, RDS Proxy, Parameter Group
│       └── variables.tf
├── environments/
│   ├── dev/
│   │   ├── main.tf
│   │   └── terraform.tfvars  # gitignored
│   ├── staging/
│   │   └── main.tf
│   └── prod/
│       └── main.tf
├── global/
│   ├── ecr.tf                # ECR repos para cada imagem Docker
│   ├── s3.tf                 # Cold storage, deploy artifacts
│   └── iam.tf                # Roles compartilhados
└── scripts/
    ├── build-and-push.sh     # docker build + ECR push
    └── deploy.sh             # terraform workspace select + apply
```

```yaml
# .github/workflows/deploy.yml
name: Deploy Pipeline
on:
  push:
    branches: [main]
    tags: ['v*']

concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
    steps:
      - uses: actions/checkout@v4
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE }}
          aws-region: us-east-1
      - name: Build and push Docker images
        run: |
          aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY
          for module in m01_collector m02_ev_calculator m03_alert_dispatcher api agents; do
            docker build -t $ECR_REGISTRY/$module:$GITHUB_SHA src/$module/
            docker push $ECR_REGISTRY/$module:$GITHUB_SHA
          done

  deploy-dev:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: hashicorp/setup-terraform@v3
      - run: |
          terraform -chdir=infrastructure/environments/dev init
          terraform -chdir=infrastructure/environments/dev apply \
            -var="image_tag=${{ github.sha }}" -auto-approve

  deploy-staging:
    needs: deploy-dev
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    environment: staging  # requer aprovação manual no GitHub
    steps:
      - run: terraform apply -var="image_tag=${{ github.sha }}" -auto-approve
```

```hcl
# modules/lambda-function/main.tf
resource "aws_ecr_repository" "this" {
  name                 = var.function_name
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_lambda_function" "this" {
  function_name = var.function_name
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
  role          = aws_iam_role.lambda.arn
  timeout       = var.timeout_seconds
  memory_size   = var.memory_mb

  environment {
    variables = var.environment_variables
  }
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.this.function_name
  function_version = aws_lambda_function.this.version
}

resource "aws_lambda_provisioned_concurrency_config" "this" {
  count          = var.provisioned_concurrency > 0 ? 1 : 0
  function_name  = aws_lambda_function.this.function_name
  qualifier      = aws_lambda_alias.live.name
  provisioned_concurrent_executions = var.provisioned_concurrency
}
```
