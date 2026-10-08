# Etapa 5 — ordem veicular aberta entre macro-paradas

## Escopo deste incremento

Esta parte da etapa 5 calcula, para uma proposta de macro-paradas existente, a
**ordem veicular aberta**:

```
partida -> cada base candidata exatamente uma vez -> chegada
```

A ordem usa **somente** uma matriz dirigida de rede OSRM de perfil veicular
(`car`). A matriz pedestre e a estimativa em linha reta **não** substituem a via:
chamar um extrato pedestre com `/driving` não muda o perfil de extração, portanto
o conjunto de dados veicular precisa ser extraído com `car.lua` e ter endpoint,
revisão e raio próprios. Endereços e rótulos são apenas apresentação; nunca
entram no objetivo.

É um **rascunho**: a base é a coordenada de entrega candidata da macro-parada,
não um estacionamento validado. Não há geometria, instruções de manobra, voz nem
economia operacional declarada.

## Fonte de custo e ordenação

Os custos vêm das entradas persistidas da matriz veicular da rota, cobrindo
`origin`, `destination` e todos os pontos de entrega. A ordem canônica de
referência é a da planilha (`source_row` mínimo) e o identificador do ponto.

A sequência minimiza a **distância dirigida** total, com desempate determinístico:

1. menor distância dirigida total;
2. menor duração dirigida acumulada **da mesma sequência**;
3. menor sequência canônica (ordem da planilha e identificador).

A resposta traz a ordem com papéis (`origin`, `candidate_base`, `destination`),
a macro-parada de cada base, as pernas dirigidas com distância e duração e os
totais.

## Solução exata e fallback

- Até **12 bases** (`exact_base_limit`, configurável) a solução é exata por
  programação dinâmica (Held-Karp) sobre o caminho aberto. As propostas reais
  atuais têm 8 e 11 bases, então o resultado é ótimo.
- Acima do limite há heurística determinística (vizinho mais próximo com 2-opt)
  marcada como **não ótima** (`optimal=false`,
  `solution_method="heuristic_nearest_neighbor_2opt"`).
- **Nenhuma ordem atravessa par inacessível.** A busca descarta qualquer
  sequência que use uma perna sem caminho. Na solução exata, a enumeração por
  programação dinâmica prova a inexistência quando nenhuma ordem é viável; na
  heurística a mensagem apenas diz que o método não encontrou e que a existência
  de caminho não foi descartada.

## Matriz veicular

A matriz veicular é um objeto persistido e auditável (`vehicle_matrices` /
`vehicle_matrix_entries`, migração `20261007_0006`). O snapshot de entrada
registra provedor, perfil, qualidade, **revisão do conjunto de dados** e chave de
cache, além da partida, da chegada e dos pontos (identificador, coordenadas
efetivas, revisão e situação). Rótulos não entram no hash: renomear a partida não
cria uma matriz nova. Qualquer revisão de ponto, troca de endpoint ou mudança de
revisão do extrato torna a matriz **desatualizada**.

## API

```http
POST /api/v1/routes/{route_id}/vehicle-matrices
Content-Type: application/json

{"origin": {"latitude": 0, "longitude": 0, "label": "partida"},
 "destination": {"latitude": 0, "longitude": 0, "label": "chegada"}}

POST /api/v1/routes/{route_id}/vehicle-orders
Content-Type: application/json

{"plan_id": "UUID", "origin": {...}, "destination": {...},
 "vehicle_matrix_id": "UUID opcional"}

GET /api/v1/routes/{route_id}/vehicle-matrices
GET /api/v1/vehicle-matrices/{matrix_id}
GET /api/v1/vehicle-matrices/{matrix_id}/entries
```

Quando `vehicle_matrix_id` é omitido, a ordem calcula e persiste a matriz
veicular com a configuração `car` atual. Repetir com a mesma partida, chegada,
pontos e provedor reaproveita a matriz (HTTP 200).

A resposta inclui `vehicle_matrix_id`, `matrix_provider`, `matrix_profile`,
`matrix_quality`, `matrix_dataset_revision`, `planning_mode`, `provisional_draft`,
`algorithm_version`, `order_rule`, `distance_basis`, `exact_base_limit`,
`origin`, `destination`, `draft`, `base_status="unverified"`, `parking_notice`,
`gps_notice`, `capability_notice`, `heuristic_notice`, `draft_notice`,
`geometry_available=false`, `maneuvers_available=false`, `voice_available=false`,
`base_count`, `package_count`, `stop_review_counts`, `exact_coverage`,
`solution_method`, `optimal`, `total_distance_m`, `total_duration_s`,
`content_hash`, `order[]` e `legs[]`.

A resposta é recusada (HTTP 409) quando:

- não há provedor veicular de rede configurado (nenhuma conectividade é inventada);
- o perfil configurado é pedestre;
- o provedor não é de rede (`estimate_only` é recusado);
- a matriz veicular não existe, está incompleta, tem custos inválidos ou pares
  inacessíveis obrigatórios;
- a matriz veicular é de outra rota, de outro perfil/provedor ou está
  desatualizada;
- a proposta está desatualizada ou não cobre cada ponto exatamente uma vez;
- a proposta pertence a outra rota.

Falha do serviço OSRM devolve HTTP 502 com mensagem explícita; nenhuma matriz é
fabricada.

O modo `coordinate_preview` continua válido: a ordem usa as bases candidatas da
proposta e **não** altera nenhum status de revisão.

## Painel

A seção **Ordem veicular** permite digitar rótulo, latitude e longitude da
partida e da chegada, calcular a ordem da proposta selecionada e ver a sequência
com as bases, os totais, as pernas e o aviso de rascunho. Nenhuma coordenada real
tem valor padrão na tela. O painel mostra o provedor veicular configurado
(provedor, perfil e revisão) e informa quando ele não existe. A base continua
marcada como não verificada; o painel não promete navegação, manobras ou
economia.

## Preparar o conjunto de dados car local

O runtime instalado em `data/osrm-tools/runtime` pode ter ACL restrita. Os
wheels ficam em `data/osrm-tools/*.whl` e podem ser extraídos para uma pasta
gravável, sem tocar em `data/osrm-walking`:

```powershell
.\.venv\Scripts\python.exe scripts/setup_osrm_runtime.py `
  --output data/osrm-tools/wheel-runtime

.\.venv\Scripts\python.exe scripts/prepare_osrm_windows.py `
  data/osrm-source/<extrato>.osm.pbf `
  --profile car `
  --runtime data/osrm-tools/wheel-runtime `
  --output data/osrm-vehicle `
  --margin-degrees 0.035 `
  --include-points-file data/<pontos-privados>.json
```

`--include-points-file` aceita a forma `{"origin": {...}, "destination": {...}}`
ou uma lista de `{latitude, longitude}` e garante que partida e chegada caibam no
recorte, com a margem informada. O comando grava `data/osrm-vehicle/dataset.json`
com o `crop_sha256`, que é a revisão do conjunto de dados. Depois:

```powershell
data/osrm-tools/wheel-runtime/bin/osrm-routed.exe `
  --algorithm ch --ip 127.0.0.1 --port 5003 data/osrm-vehicle/map.osrm
```

Configure a API com endpoint, perfil e revisão próprios:

```
VEHICLE_MAP_PROVIDER=osrm
VEHICLE_OSRM_BASE_URL=http://127.0.0.1:5003
VEHICLE_OSRM_PROFILE=car
VEHICLE_OSRM_DATASET_REVISION=<crop_sha256>
VEHICLE_OSRM_SNAP_RADIUS_M=100
```

O recorte privado fica em `data/` (ignorado pelo Git). Coordenadas reais nunca
entram em arquivos versionados, testes ou exemplos.

## Relatório privado

`scripts/vehicle_order_report.py` gera o rascunho das propostas existentes e um
relatório agregado em `outputs/` **sem** endereços nem coordenadas, usando
`--endpoints-file` para ler a partida e a chegada de um arquivo local. O
relatório registra perfil, revisão, qualidade, número de nós, pares sem caminho,
método, totais e hash de conteúdo. A URL de conexão nunca é escrita.

## Testes versionados

`tests/test_vehicle_order.py` usa somente dados sintéticos e cobre: ordem aberta
não trivial, desempate por duração na mesma sequência, empate completo com ordem
canônica que ignora o endereço, base única, par inacessível obrigatório, desvio de
par inacessível quando há alternativa, cobertura exata sem duplicação, ponto
pendente em `coordinate_preview`, plano desatualizado, provedor ausente ou
pedestre, matriz `estimate_only`/incompleta/desatualizada por revisão, matriz e
plano de outra rota, 404, falha 502 sem matriz fabricada, fallback heurístico
acima do limite exato, idempotência da matriz, superfície do painel e do OpenAPI,
e o `/api/v1/maps/config` veicular. `tests/test_vehicle_dataset_prep.py` cobre a
leitura do arquivo privado de pontos, a união do recorte e os arquivos exigidos
do runtime.

## Limites e o que ainda falta

- A base é uma **entrada candidata**; não comprova vaga, acesso de veículo nem
  permissão de estacionar.
- Portões, travessias, capacidade da bag e tempos de serviço seguem sem validação
  física.
- A ordem é uma sequência de bases sobre a matriz de custos: sem geometria, não
  há instruções de manobra nem navegação por voz.
- Nenhuma economia é declarada: a planilha não registra o percurso original nem o
  estacionamento.
- A partida real deve usar o GPS confirmado do veículo.
