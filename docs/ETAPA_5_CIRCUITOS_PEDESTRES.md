# Etapa 5 — circuitos pedestres fechados (incremento por coordenadas)

## Escopo deste incremento

Esta parte da etapa 5 calcula, **sob demanda**, o circuito pedestre **fechado e dirigido** de cada macro-parada já proposta. O circuito começa na base candidata (`candidate_base_point_id`), visita cada ponto de entrega do grupo exatamente uma vez e retorna à base. É um **rascunho de sequência de pontos**: não há geometria, instruções de manobra, voz nem estacionamento confirmado, e nenhuma economia operacional é prometida.

A **ordem veicular entre macro-paradas não foi implementada**: ela exige uma matriz veicular regional e um ponto de partida e chegada configurável.

## Fonte de custo e ordenação

Os únicos custos usados são as distâncias e durações dirigidas da matriz OSRM `foot` persistida da própria proposta. Nenhum endereço textual participa da ordenação nem do cálculo. A ordem canônica de referência é a da planilha (`source_row` mínimo) e o identificador do ponto.

A sequência escolhida minimiza a **distância pedestre dirigida** total, com desempate determinístico:

1. menor distância dirigida total;
2. menor duração dirigida acumulada **da mesma sequência**;
3. menor sequência canônica (ordem da planilha e identificador).

A resposta apresenta a distância e a duração acumuladas da sequência vencedora e as pernas dirigidas que a compõem, incluindo o retorno à base.

## Solução exata e fallback

- Grupos com até **9 pontos** (`exact_point_limit`) são resolvidos por enumeração exata de todas as ordens viáveis a partir da base. Para os grupos reais atuais (até 8 pacotes) a solução é exata.
- Grupos acima do limite usam heurística determinística (vizinho mais próximo com 2-opt), marcada como **não ótima** (`optimal=false`, `solution_method="heuristic_nearest_neighbor_2opt"`).
- **Nenhum circuito atravessa par inacessível.** A busca descarta qualquer sequência que use uma perna sem caminho. Se não existir circuito viável sem par inacessível, a resposta é recusada com erro claro.
- Quando a **heurística** não encontra circuito, a mensagem diz apenas que o método não o encontrou e que a existência de caminho não foi descartada; ela não afirma impossibilidade matemática. Na solução exata, a enumeração de todas as ordens prova a inexistência quando nenhuma é viável.

## Limite de ida e volta e aviso por circuito

O parâmetro `max_base_roundtrip_m` da etapa 4 limita **cada ida e volta individual** entre a base candidata e um endereço do grupo. Ele **não** limita a distância total do circuito fechado que visita vários pontos: um circuito pode somar mais que esse valor sem violar o agrupamento. O cálculo não bloqueia nem altera o agrupamento automaticamente.

Por isso a resposta traz:

- `max_base_roundtrip_m` e `base_roundtrip_limit_notice` no nível da proposta;
- `circuits_exceeding_base_roundtrip` com a contagem de circuitos acima do parâmetro;
- em cada circuito, `exceeds_base_roundtrip_limit` e `roundtrip_warning` (texto com a distância total e o limite quando a distância supera o parâmetro).

Esse aviso aparece no painel, no relatório privado agregado e na API, sem alterar nenhuma proposta persistida.

## API

```http
GET /api/v1/macro-plans/{plan_id}/circuits
```

O cálculo é determinístico e sem persistência nova: repetir a chamada com a mesma proposta e a mesma matriz devolve o mesmo `content_hash`. A resposta inclui:

- `plan_id`, `route_id`, `walking_matrix_id`, `planning_mode`, `provisional_draft`, `stale`;
- `algorithm_version`, `order_rule`, `distance_basis`, `exact_point_limit`, `content_hash`;
- `max_base_roundtrip_m` e `base_roundtrip_limit_notice` (semântica do parâmetro da etapa 4);
- `base_status="unverified"`, `base_notice`, `gps_notice`, `capability_notice`, `draft_notice`;
- `geometry_available=false`, `maneuvers_available=false`, `voice_available=false`;
- totais `total_distance_m` e `total_duration_s`, contagens `circuit_count`, `exact_circuit_count`, `heuristic_circuit_count`, `all_circuits_exact`, `circuits_exceeding_base_roundtrip`, `exact_coverage`;
- `circuits[]` com `stop_id`, `ordinal`, `candidate_base_point_id`, `base_status`, `delivery_point_ids`, `sequence_point_ids` (a base primeiro), `closed`, `point_count`, `package_count`, `distance_m`, `duration_s`, `solution_method`, `optimal`, `max_base_roundtrip_m`, `exceeds_base_roundtrip_limit`, `roundtrip_warning` e `legs[]` (pernas dirigidas, incluindo o retorno).

O `gps_notice` registra que **a partida real deve usar o GPS confirmado do veículo para uma rota final**. A base é uma coordenada de endereço candidata: `parking_status`/`base_status` permanecem `unverified`.

A resposta é recusada (HTTP 409) quando:

- a matriz é `estimate_only`;
- falta o snapshot auditável da matriz;
- a matriz está incompleta ou inconsistente;
- a matriz está desatualizada (`stale`) em relação aos pontos;
- um par obrigatório do circuito está inacessível;
- a proposta referencia ponto de outra rota ou não cobre cada ponto exatamente uma vez.

O modo `coordinate_preview` continua válido: os circuitos usam as coordenadas efetivas da proposta e **não** exigem confirmar as entradas pendentes nem alteram qualquer status de revisão.

## Painel

No detalhe de uma proposta, o botão **Calcular circuitos pedestres fechados** consulta o endpoint e mostra, por macro-parada, a sequência de pontos com partida e retorno à base, distância e duração acumuladas, se a solução é exata ou heurística não ótima, além dos avisos de base não verificada, GPS confirmado e ausência de geometria. O painel exibe o limite de ida e volta à base da etapa 4 e destaca, no circuito e no total, quando a distância completa supera esse parâmetro. Propostas desatualizadas mantêm o botão desabilitado.

## Limites e o que ainda falta

- A base é uma **entrada candidata**; não comprova vaga, acesso de veículo nem permissão de estacionar.
- Portões, travessias, capacidade da bag e tempos de serviço seguem sem validação física.
- O circuito é uma sequência de pontos sobre a matriz de custos: sem geometria, não há instruções de manobra nem navegação por voz.
- Nenhuma economia de distância é declarada: a planilha não registra o percurso a pé nem o estacionamento original.
- A ordem veicular entre macro-paradas depende de matriz veicular regional e de um ponto de partida e chegada configurável.

## Testes versionados

`tests/test_circuits.py` usa somente dados sintéticos e cobre: circuito mínimo dirigido não trivial, empate determinístico sem ordenação por endereço, ponto único, par inacessível obrigatório e desvio de par inacessível quando há alternativa, cobertura exata sem duplicação entre circuitos, fallback acima do limite exato, aviso por circuito acima do parâmetro de ida e volta sem bloquear o agrupamento, mensagem da heurística sem afirmar impossibilidade, `coordinate_preview` com entradas pendentes, marcação não homologada, recusa de matriz `estimate_only`/sem snapshot/incompleta/antiga, isolamento entre rotas, 404 e superfície do painel e do OpenAPI.

`tests/test_circuit_report.py` verifica que o relatório agregado nunca escreve nem imprime a URL de conexão (inclusive com uma URL sintética com senha, sem conectar a banco externo) e que o relatório real de uma proposta traz o parâmetro de ida e volta e o aviso por circuito.
