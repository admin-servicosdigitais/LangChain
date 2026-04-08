# ADR-005: Arquitetura dos Agentes LangChain — Padrão de Design

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** Todos os agentes (AGT-A a AGT-H), M01, M02, M03, M04, M05

## Contexto

LangChain em Python é o framework mandatório e inegociável para todos os 8 agentes. A decisão de design foca em como estruturar os agentes dentro do LangChain, não se usar LangChain.

Os 8 agentes têm padrões de execução distintos:
- **Reativo a eventos** (AGT-B, AGT-E, AGT-G): disparam em resposta a eventos SQS/EventBridge. Execução < 2min
- **Batch periódico** (AGT-A, AGT-D, AGT-F, AGT-H): executam em schedule (diário/semanal). Execução 5-30min
- **Interativo contextual** (AGT-E, AGT-C): respondem a inputs de usuário via Telegram, precisam de memória de conversação

O orçamento de LLM é ~$2-4K/mês para 1000 usuários Elite ativos (V2 completo). A seleção de modelo por agente é determinante para o custo.

## Opções Consideradas

### Opção A: AgentExecutor (ReAct Loop) para todos os agentes

**Prós:**
- Familiar, documentado, simples de implementar
- Funciona out-of-the-box com qualquer LLM compatível com tool-calling

**Contras:**
- **Deprecated** — LangChain recomenda migração para LangGraph
- Sem checkpointing: se o agente falhar na tool call 5 de 8, reinicia do zero
- Sem controle de fluxo condicional: impossível implementar branching complexo (ex: AGT-G selecionar 1 de 5 playbooks)
- Sem human-in-the-loop nativo para autonomy bounds de admin
- Sem suporte a streaming de partial outputs

### Opção B: LangGraph para todos os agentes

**Prós:**
- Grafo de estados com checkpointing via `MemorySaver` ou `PostgresSaver` — resiliência a falhas
- Controle de fluxo explícito: nós condicionais, edges com predicados, ciclos controlados
- Human-in-the-loop nativo com `interrupt_before`/`interrupt_after` — implementa autonomy bounds
- Suporte nativo a multi-agent (agentes como sub-grafos)
- AGT-G: grafo com nó de diagnóstico → escolha de playbook → execução → verificação → rollback

**Contras:**
- Curva de aprendizado maior: conceitos de StateGraph, nodes, edges, reducers
- Overhead de framework para agentes simples (AGT-B é classificador simples — LangGraph é overkill)
- Checkpointing via PostgresSaver requer conexão ao Aurora (ADR-002)

### Opção C: Híbrido — LangGraph para agentes complexos + LCEL para classificadores simples

**Prós:**
- AGT-B (Odds Movement Classifier): LCEL chain `prompt | llm | parser`. Sem estado, sem tools, sem ciclo. Latência < 3s
- AGT-G (AIOps): LangGraph com 5 nós (diagnose, select_playbook, execute, verify, rollback) — controle de fluxo crítico
- AGT-E (Onboarding Coach): LangGraph com memória de conversação e state de dia de onboarding
- Cada agente usa o mínimo de complexidade necessário
- AGT-A MVP: LCEL puro; V2 migra para LangGraph quando adiciona scoring adaptativo por série temporal

**Contras:**
- Dois padrões no codebase — novos desenvolvedores precisam entender ambos
- Risco de inconsistência: agente que começa como LCEL pode precisar virar LangGraph

## Decisão

**Escolha: Opção C — LangGraph para agentes com estado/fluxo complexo + LCEL para classificadores simples**

LangGraph é o padrão principal (6 de 8 agentes). LCEL puro apenas para AGT-B (classificador stateless, alta frequência) e AGT-A MVP (scoring simples que vira LangGraph em V2).

A migração LCEL→LangGraph para AGT-A em V2 é planejada desde o início: o LCEL chain já é encapsulado em classe `BaseAgent` com interface comum, permitindo trocar a implementação interna sem afetar consumers.

**Seleção de modelo por agente:**

| Agente | Modelo | Justificativa | Custo Est./mês |
|--------|--------|---------------|----------------|
| AGT-A | Claude Haiku 4.5 | Scoring numérico simples, alta frequência | $120 |
| AGT-B | Claude Haiku 4.5 | Classificação de 5 categorias por evento | $180 |
| AGT-C | Claude Sonnet 4.6 | Conselho financeiro personalizado, baixa frequência | $200 |
| AGT-D | Claude Sonnet 4.6 | Análise batch complexa de padrões de mercado | $300 |
| AGT-E | Claude Haiku 4.5 | Coach conversacional, 7 dias × N trial users | $250 |
| AGT-F | Claude Sonnet 4.6 | Narrativa de performance — qualidade importa | $350 |
| AGT-G | Claude Haiku 4.5 | Seleção de playbook (decisão estruturada, não criativa) | $80 |
| AGT-H | Claude Sonnet 4.6 | Análise de volume e smart money — análise sutil | $400 |
| **Total** | | | **~$1.880/mês** |

Com crescimento para 1000 usuários Elite ativos: ~$2.500-3.500/mês = 3-5% da receita Elite.

**Autonomy Bounds** via LangGraph `interrupt_before`: ações destrutivas (AGT-G: restart de serviço, rollback de deploy) requerem aprovação via SNS→Admin dashboard antes de executar. Configurável por playbook via DynamoDB config table (ver RF-ADM-C).

**Padrão de consumo de eventos SQS**: Lambda intermediária recebe evento SQS, extrai payload, instancia o agente LangChain e chama `agent.invoke()`. Para agentes batch, EventBridge Scheduler → ECS Task → agente roda como job standalone.

## Consequências

**Positivas:**
- LangGraph checkpointing garante resiliência de AGT-G em incidentes longos (pode retomar de onde parou)
- LCEL para AGT-B: latência de classificação < 3s, sem overhead de grafo
- Modelo por agente otimiza custo: Haiku para tasks estruturadas, Sonnet para análise narrativa
- Interface comum `BaseAgent` permite adicionar novos agentes sem alterar consumers
- `interrupt_before` implementa autonomy bounds sem código custom

**Negativas / Trade-offs:**
- Dois padrões (LangGraph + LCEL) aumentam onboarding de novos devs
- PostgresSaver para checkpointing requer conexão ao Aurora por agente LangGraph — +1 conexão no pool
- Claude Sonnet 4.6 para AGT-F/AGT-H aumenta custo se volume Elite crescer além de 2000 usuários

**Riscos e Mitigações:**
- Risco: LLM timeout em AGT-D (análise batch 30min) → Mitigação: LangGraph checkpointing salva estado a cada nó; timeout de LLM call configurado em 120s com retry exponencial
- Risco: Custo LLM explode com bug de loop infinito em LangGraph → Mitigação: `max_iterations=10` em todos os grafos; CloudWatch alarme em custo Anthropic/Bedrock diário > $150
- Risco: Claude Haiku 4.5 insuficiente para AGT-G selecionar playbook correto → Mitigação: Playbook selection usa structured output (JSON mode) com enum fixo de 5 opções; fallback para playbook conservador se confidence < 0.8
- Risco: AGT-E perde contexto de conversação entre sessões → Mitigação: LangGraph `MemorySaver` com PostgresSaver persiste state por `thread_id=user_id#onboarding_session`

## Implementação

```
src/agents/
├── base.py                        # BaseAgent interface comum
├── agt_a_data_quality/
│   ├── agent.py                   # LCEL V1, LangGraph V2
│   ├── tools.py                   # DynamoDB score lookup
│   └── prompts.py
├── agt_b_odds_classifier/
│   ├── agent.py                   # LCEL chain stateless
│   ├── schema.py                  # MovementClassification (Pydantic)
│   └── prompts.py
├── agt_e_onboarding_coach/
│   ├── agent.py                   # LangGraph StateGraph
│   ├── graph.py                   # nós por dia de onboarding
│   ├── tools.py                   # send_telegram, get_alert_history
│   └── state.py                   # OnboardingState TypedDict
├── agt_g_aiops_remediator/
│   ├── agent.py                   # LangGraph StateGraph
│   ├── graph.py                   # diagnose → select → execute → verify → rollback
│   ├── playbooks/
│   │   ├── plb_001_fallback_layer2.py
│   │   ├── plb_002_backoff_rate_limit.py
│   │   ├── plb_003_scale_lambda.py
│   │   ├── plb_004_exclude_bookmaker.py
│   │   └── plb_005_restart_ev_lambda.py
│   └── tools.py
└── shared/
    ├── llm_factory.py             # instancia Claude Haiku/Sonnet por agente
    ├── memory.py                  # PostgresSaver wrapper
    └── sqs_consumer.py            # Lambda handler → agent.invoke()
```

```python
# src/agents/base.py
from abc import ABC, abstractmethod
from typing import Any

class BaseAgent(ABC):
    agent_id: str
    version: str

    @abstractmethod
    async def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        """Executa o agente com o input dado. Nunca levanta exceção — retorna fallback."""
        ...

    @abstractmethod
    def get_runnable(self):
        """Retorna o LangGraph compilado ou LCEL runnable."""
        ...
```

```python
# src/agents/shared/llm_factory.py
from langchain_anthropic import ChatAnthropic

LLM_CONFIGS = {
    "haiku": {"model": "claude-haiku-4-5", "temperature": 0, "max_tokens": 1024},
    "sonnet": {"model": "claude-sonnet-4-6", "temperature": 0.1, "max_tokens": 4096},
}

def get_llm(tier: str) -> ChatAnthropic:
    config = LLM_CONFIGS[tier]
    return ChatAnthropic(**config)
```

```python
# src/agents/agt_b_odds_classifier/agent.py — LCEL puro
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from ..shared.llm_factory import get_llm
from ..base import BaseAgent
from .schema import MovementClassification

class OddsMovementClassifier(BaseAgent):
    agent_id = "AGT-B"
    version = "1.0.0"

    def __init__(self):
        llm = get_llm("haiku")
        parser = JsonOutputParser(pydantic_object=MovementClassification)
        prompt = ChatPromptTemplate.from_template(CLASSIFIER_PROMPT)
        self._chain = prompt | llm | parser

    async def invoke(self, input: dict) -> dict:
        try:
            result = await self._chain.ainvoke(input)
            return {"classification": result, "source": "agent_b"}
        except Exception:
            return {"classification": None, "source": "pending"}

    def get_runnable(self):
        return self._chain
```

```python
# src/agents/agt_g_aiops_remediator/graph.py — LangGraph com autonomy bounds
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from typing import TypedDict

class AIOpsState(TypedDict):
    incident: dict
    diagnosis: str
    selected_playbook: str | None
    execution_result: dict | None
    requires_approval: bool
    approved: bool

def build_aiops_graph(checkpointer: PostgresSaver) -> StateGraph:
    graph = StateGraph(AIOpsState)
    graph.add_node("diagnose", diagnose_incident)
    graph.add_node("select_playbook", select_playbook)
    graph.add_node("await_approval", await_human_approval)  # interrupt_before
    graph.add_node("execute", execute_playbook)
    graph.add_node("verify", verify_result)
    graph.add_node("rollback", rollback_action)

    graph.add_conditional_edges("select_playbook", route_by_autonomy, {
        "auto": "execute",
        "needs_approval": "await_approval",
        "escalate": END,
    })
    graph.add_edge("await_approval", "execute")
    graph.add_conditional_edges("verify", route_by_result, {
        "success": END,
        "failure": "rollback",
    })
    graph.add_edge("rollback", END)
    graph.set_entry_point("diagnose")

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["await_approval"]  # implementa autonomy bounds
    )
```
