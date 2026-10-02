# Etapa 4 — macro-paradas

## Entrega técnica

O sistema cria e persiste propostas de macro-paradas a partir de uma matriz pedestre de qualidade `network`. A matriz deve cobrir todos os pares dirigidos, conter um snapshot e estar atual em relação aos pontos e à configuração do provedor. Todos os pontos precisam estar confirmados ou corrigidos. Estimativas em linha reta, matrizes antigas, pares inconsistentes e pontos sem revisão são recusados.

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

Após `alembic upgrade head`, a raiz da API mostra o formulário **Macro-paradas**. Selecione uma matriz de rede atual, ajuste os três limites e gere a proposta. A tela lista endereços, pacotes, paradas originais, máximos de caminhada e estado da revisão. É possível aceitar ou rejeitar cada agrupamento com observação. Propostas antigas permanecem consultáveis e aparecem desatualizadas após revisão geográfica ou troca do provedor.

```http
POST /api/v1/routes/{route_id}/macro-plans
Content-Type: application/json

{"walking_matrix_id":"UUID","max_packages":8,"max_pairwise_m":400,"max_base_roundtrip_m":600}

GET /api/v1/routes/{route_id}/macro-plans
GET /api/v1/macro-plans/{plan_id}
PATCH /api/v1/macro-stops/{stop_id}/review
Content-Type: application/json

{"review_status":"accepted","review_note":"Agrupamento conferido"}
```

Repetir a criação com a mesma matriz e parâmetros devolve a proposta existente, preservando as revisões. Uma nova matriz ou mudança de limite cria outro rascunho. Os agrupamentos não são editados individualmente nesta versão; rejeite o grupo e ajuste os limites para gerar uma nova proposta.

## Comparação e aceitação

A resposta mostra pacotes cobertos, pontos, número de paradas originais, macro-paradas propostas, pacotes sem parada original e quantas paradas originais foram divididas. Também mostra os limites medidos em cada macro-parada. A planilha não registra onde o veículo estacionou antes nem os percursos a pé da execução original; por isso a API informa `distance_comparison_available=false` e não declara economia de distância ou retornos.

As duas amostras foram **lidas localmente**, sem entrar no Git. A triagem abaixo usa apenas distância em linha reta entre coordenadas importadas e os mesmos limites numéricos padrão. É um **indicador de densidade**, não uma matriz de caminhada nem uma proposta operacional:

| Rota | Pacotes | Pontos de entrega | Ponto vizinho a até 100 m em linha reta | Grupos geométricos candidatos | Grupos com mais de uma entrada |
| --- | ---: | ---: | ---: | ---: | ---: |
| 30/09/2026 | 18 | 17 | 8 | 7 | 3 |
| 22/09/2026 | 38 | 35 | 34 | 6 | 6 |

A rota de 30/09 é mais dispersa e inclui visitas individuais; a de 22/09 apresenta mais potencial para caminhar entre endereços de ruas diferentes. Mesmo na primeira, a triagem encontra alguns bolsões próximos. Na triagem inicial, faltavam a matriz pedestre regional, a conferência dos acessos e a validação de estacionamento. Nenhum desses grupos foi aceito para operação. Os testes versionados usam somente dados sintéticos.

Em 01/10/2026, a preparação local do extrato pedestre e a auditoria automática das duas rotas produziram matrizes de rede atuais para 17 e 35 pontos, com 0 pares inacessíveis. Elas foram calculadas em modo **provisório**, pois 51 dos 52 pontos ainda estão `pending`. Assim, a condição de entrada da etapa 4 continua bloqueada. Os relatórios detalhados, o extrato e o banco ficam somente em `outputs/` e `data/`, fora do Git. A conferência de portões, travessias, bases veiculares e capacidade física da bag segue pendente.

Para concluir a etapa em campo: preparar o extrato pedestre da região, conferir entradas e barreiras, obter a matriz de rede, revisar os agrupamentos e validar estacionamento e capacidade da bag. A ordem veicular e os circuitos fechados são da etapa 5.
