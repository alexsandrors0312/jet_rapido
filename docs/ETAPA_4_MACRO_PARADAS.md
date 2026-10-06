# Etapa 4 — macro-paradas

## Entrega técnica

O sistema cria e persiste propostas de macro-paradas a partir de uma matriz pedestre de qualidade `network`. A matriz deve cobrir todos os pares dirigidos, conter um snapshot e estar atual em relação aos pontos e à configuração do provedor. Estimativas em linha reta, matrizes antigas, pares inconsistentes e coordenadas efetivas inválidas são recusados nos dois modos.

Existem dois modos explícitos de entrada:

- **`strict` (padrão):** exige que todos os pontos estejam confirmados ou corrigidos. É o modo das chamadas existentes.
- **`coordinate_preview`:** agrupa pelas **coordenadas efetivas** mesmo com pontos `pending`. É sempre um rascunho não homologado: não altera o status de revisão, não confirma portões nem travessias e não valida estacionamento. O texto do endereço serve apenas de apoio de busca, apresentação e alerta.

Em ambos os modos, pontos `rejected` continuam bloqueados. No modo por coordenadas, a matriz ainda precisa ser `network`, completa, com snapshot e atual; pares necessários inacessíveis permanecem bloqueados.

Cada proposta conserva todos os pontos e pacotes exatamente uma vez. O limite inicial, confirmado pelo usuário para este rascunho, é **8 pacotes por saída da bag**. Ele é um número provisório porque a planilha não traz peso nem volume. Os limites padrão de 400 m entre entradas e 600 m para cada ida e volta à base são parâmetros de demonstração, ajustáveis na tela ou API. Eles não representam uma tolerância operacional homologada.

Uma base candidata é escolhida entre os pontos de entrega do grupo. Ela minimiza primeiro a maior ida e volta dirigida entre base e endereço e, em empate, a soma dessas idas e voltas. **A coordenada do endereço não comprova vaga, acesso de veículo nem permissão de estacionar.** A resposta sempre marca `parking_status=unverified`. A revisão humana aceita ou rejeita o *agrupamento*, sem validar estacionamento.

## Regra de agrupamento

O algoritmo começa com um grupo por ponto e funde grupos viáveis, escolhendo a fusão com menor máximo de ida e volta à base e menor distância dirigida entre pontos. Uma fusão só é aceita quando:

1. A soma de pacotes não excede a capacidade configurada.
2. Todos os pares dirigidos dentro do grupo têm caminho e distância até o limite entre entradas.
3. Existe uma base candidata no grupo cuja ida e volta a **cada** entrada está dentro do limite configurado.

A rua textual e a parada original são usadas para comparação, não impõem união. O método é guloso e determinístico; não garante o menor número global de macro-paradas nem calcula o circuito completo. O limite de ida e volta é medido para cada endereço isoladamente. A soma de uma visita a vários endereços ainda depende da etapa 5. Se um único ponto tiver mais pacotes que a capacidade, a proposta é recusada; a futura modelagem de múltiplas cargas da bag no mesmo local deverá tratar esse caso.

Cada macro-parada recebe um tipo descritivo: `single_address_stop` quando contém uma única entrada, ou `multi_address_walk_candidate` quando contém mais de uma. A resposta também conta agrupamentos entre ruas distintas e pacotes nesses agrupamentos. Um grupo de várias ruas **pode** ser caminhável; igualdade de rua não garante passagem. Esses tipos não afirmam que o estacionamento ou a travessia foram homologados. O veículo ainda precisa se deslocar entre macro-paradas.

## API e painel

Após `alembic upgrade head`, a raiz da API mostra o formulário **Macro-paradas**. Escolha o **modo de planejamento** (`Estrito` ou `Por coordenadas`), selecione uma matriz de rede atual, ajuste os três limites e gere a proposta. A tela exibe o número de entradas `pending` e um aviso curto quando o modo por coordenadas está ativo. Ainda é possível revisar ou corrigir cada ponto individualmente: uma revisão de coordenada invalida a matriz e as propostas anteriores. A tela lista endereços, pacotes, paradas originais, máximos de caminhada e estado da revisão. É possível aceitar ou rejeitar cada agrupamento com observação. Propostas antigas permanecem consultáveis e aparecem desatualizadas após revisão geográfica ou troca do provedor.

Para calcular a matriz provisória sem revisar tudo, marque **Calcular matriz provisória mesmo com entradas pendentes** (a API recebe `allow_unreviewed=true`). A estimativa em linha reta continua sendo recusada para planejar.

```http
POST /api/v1/routes/{route_id}/macro-plans
Content-Type: application/json

{"walking_matrix_id":"UUID","planning_mode":"strict","max_packages":8,"max_pairwise_m":400,"max_base_roundtrip_m":600}

GET /api/v1/routes/{route_id}/macro-plans
GET /api/v1/macro-plans/{plan_id}
PATCH /api/v1/macro-stops/{stop_id}/review
Content-Type: application/json

{"review_status":"accepted","review_note":"Agrupamento conferido"}
```

Repetir a criação com a mesma matriz, parâmetros **e modo** devolve a proposta existente, preservando as revisões. Uma nova matriz, mudança de limite ou troca de modo cria outro rascunho. Os agrupamentos não são editados individualmente nesta versão; rejeite o grupo e ajuste os limites para gerar uma nova proposta.

O modo escolhido é persistido em `macro_plans.planning_mode` (migração `20261006_0005`), entra no hash de idempotência e na resposta:

```http
POST /api/v1/routes/{route_id}/macro-plans
Content-Type: application/json

{"walking_matrix_id":"UUID","planning_mode":"coordinate_preview","max_packages":8,"max_pairwise_m":400,"max_base_roundtrip_m":600}
```

A resposta informa `planning_mode`, `provisional_draft`, `pending_point_count`, `reviewed_point_count`, `review_counts_basis` e um `review_notice`. As contagens vêm do snapshot imutável da matriz que originou a proposta (`plan_input_snapshot`), então uma proposta `stale` continua exibindo a entrada com que foi criada; planos legados sem snapshot usam o estado atual com sinalização (`legacy_current_points`) e permanecem `stale`. No modo por coordenadas, `provisional_draft=true` e o aviso registra que o rascunho não foi homologado. Cada `stop` continua com `parking_status=unverified`.

## Comparação e aceitação

A resposta mostra pacotes cobertos, pontos, número de paradas originais, macro-paradas propostas, pacotes sem parada original e quantas paradas originais foram divididas. Também mostra os limites medidos em cada macro-parada. A planilha não registra onde o veículo estacionou antes nem os percursos a pé da execução original; por isso a API informa `distance_comparison_available=false` e não declara economia de distância ou retornos.

As duas amostras foram **lidas localmente**, sem entrar no Git. A triagem abaixo usa apenas distância em linha reta entre coordenadas importadas e os mesmos limites numéricos padrão. É um **indicador de densidade**, não uma matriz de caminhada nem uma proposta operacional:

| Rota | Pacotes | Pontos de entrega | Ponto vizinho a até 100 m em linha reta | Grupos geométricos candidatos | Grupos com mais de uma entrada |
| --- | ---: | ---: | ---: | ---: | ---: |
| 30/09/2026 | 18 | 17 | 8 | 7 | 3 |
| 22/09/2026 | 38 | 35 | 34 | 6 | 6 |

A rota de 30/09 é mais dispersa e inclui visitas individuais; a de 22/09 apresenta mais potencial para caminhar entre endereços de ruas diferentes. Mesmo na primeira, a triagem encontra alguns bolsões próximos. Na triagem inicial, faltavam a matriz pedestre regional, a conferência dos acessos e a validação de estacionamento. Nenhum desses grupos foi aceito para operação. Os testes versionados usam somente dados sintéticos.

Em 01/10/2026, a preparação local do extrato pedestre e a auditoria automática das duas rotas produziram matrizes de rede atuais para 17 e 35 pontos, com 0 pares inacessíveis. Elas foram calculadas em modo **provisório**, pois a maior parte dos pontos ainda estava `pending`. Os relatórios detalhados, o extrato e o banco ficam somente em `outputs/` e `data/`, fora do Git. A conferência de portões, travessias, bases veiculares e capacidade física da bag segue pendente.

Em 02/10/2026, a revisão de entradas foi reexecutada com evidência OSM local (nomes de via e números de porta do recorte). Nenhuma confirmação ou correção automática foi aplicada — mapa não comprova portão — e os pontos pendentes permaneceram pendentes, com instruções por caso no relatório privado `outputs/revisao-entradas-osrm-20261002.md`. O gate estrito foi exercitado e recusou propostas enquanto houver pontos pendentes (HTTP 409).

Em 06/10/2026, o usuário decidiu que a conferência manual de todos os endereços é lenta demais e autorizou avançar com a **latitude e longitude efetivas como base**, deixando o endereço como apoio de busca, apresentação e alerta. Foi acrescentado o modo explícito `coordinate_preview` descrito acima. O estado local conferido nesta data é: **49 entradas `pending`** (32 na rota de 22/09 e 17 na de 30/09), 3 `corrected` na rota de 22/09 e nenhuma `rejected`. As matrizes de rede atuais são `1aa1242e…` (35×35) para 22/09 e `a9498e40…` (17×17) para 30/09, ambas com 0 pares inacessíveis e snapshot atual. O modo por coordenadas produz rascunhos não homologados sem marcar nenhum ponto como confirmado; portões, travessias, estacionamento e bag de 8 pacotes continuam sem validação física.

Para concluir a etapa em campo: preparar o extrato pedestre da região, conferir entradas e barreiras, obter a matriz de rede, revisar os agrupamentos e validar estacionamento e capacidade da bag. A ordem veicular e os circuitos fechados são da etapa 5.
