# Etapa 3 — revisão geográfica e mapas

## Resultado desta etapa

A importação passa a criar um ponto de entrega para cada endereço normalizado dentro da rota. Vários pacotes no mesmo endereço compartilham o ponto, mas continuam sendo registros independentes. O endereço e a coordenada recebidos da planilha permanecem imutáveis; a revisão altera somente a coordenada efetiva usada pelo planejamento.

Uma matriz pedestre registra todos os pares origem/destino, inclusive a diagonal. Um par sem caminho tem `reachable=false`, distância e duração nulas e um `error_code`. Ele não recebe uma distância artificial alta, pois isso esconderia uma barreira real do algoritmo da etapa 4.

## Estados da revisão

| Estado | Significado | Pode gerar matriz? |
| --- | --- | --- |
| `pending` | Ainda não conferido | Somente com `allow_unreviewed=true` |
| `confirmed` | Entrada importada aceita | Sim |
| `corrected` | Coordenada efetiva ajustada | Sim |
| `rejected` | Ponto inválido ou não localizado | Não |

Uma correção exige latitude e longitude. Confirmar ou rejeitar não aceita novas coordenadas. A confirmação em lote altera somente pontos pendentes, portanto não apaga correções nem rejeições anteriores.

## Escolha do provedor

O backend usa a interface `WalkingMatrixProvider`. A primeira integração de rede é OSRM e o modo local padrão é `straight_line`.

| Opção | Uso pretendido | Limites relevantes | Decisão |
| --- | --- | --- | --- |
| OSRM próprio | Matriz de rede no backend | O perfil é definido na preparação dos dados; pares sem rota vêm como `null`; exige manter extrato e serviço | Integração principal desta etapa |
| Google Routes | Alternativa gerenciada e possível navegação no app | Compute Route Matrix limita normalmente a 625 elementos e cobra por elemento; rotas a pé têm aviso de beta | Avaliar no piloto, sem acoplar o domínio |
| Mapbox Matrix | Alternativa gerenciada | Perfis de caminhada aceitam no máximo 25 coordenadas por requisição e há limite padrão de 60 requisições por minuto | Útil para lotes menores |
| Linha reta ajustada | Desenvolvimento offline | Ignora muros, portões, passarelas, sentido e acessibilidade | Proibida como evidência para formar macro-paradas em produção |

Referências oficiais consultadas em 18/09/2026:

- [OSRM HTTP API](https://project-osrm.org/docs/v5.24.0/api/)
- [Google Compute Route Matrix](https://developers.google.com/maps/documentation/routes/compute_route_matrix)
- [Google Route Matrix options](https://developers.google.com/maps/documentation/routes/reference/rest/v2/RouteMatrixElement)
- [Mapbox Matrix API](https://docs.mapbox.com/api/navigation/matrix/)

A distância devolvida pelo Table Service do OSRM é a distância da rota mais rápida para o perfil carregado. Ela não deve ser descrita como a menor distância geométrica. O algoritmo poderá ponderar distância e duração separadamente na etapa 4.

## Configuração

O modo padrão permite desenvolver sem rede:

```text
MAP_PROVIDER=straight_line
STRAIGHT_LINE_DETOUR_FACTOR=1.25
WALKING_SPEED_MPS=1.3
```

Para usar um serviço OSRM preparado com um perfil pedestre:

```text
MAP_PROVIDER=osrm
OSRM_BASE_URL=http://localhost:5000
OSRM_PROFILE=foot
OSRM_TIMEOUT_SECONDS=20
OSRM_BLOCK_SIZE=50
MAX_MATRIX_POINTS=200
```

O backend divide a matriz em blocos. O valor `MAX_MATRIX_POINTS` também limita o crescimento quadrático no banco: 200 pontos geram 40.000 pares. Um endpoint OSRM de produção precisa ser controlado pela operação, usar um extrato atualizado da área atendida e ser observado quanto a latência e falhas. O servidor público de demonstração não é uma dependência operacional.

## Fluxo HTTP

Depois de importar a planilha, obtenha o `route_id` e consulte:

```http
GET /api/v1/routes/{route_id}/delivery-points
```

Confirme uma coordenada importada:

```http
PATCH /api/v1/delivery-points/{point_id}/review
Content-Type: application/json

{"review_status":"confirmed","review_source":"operator"}
```

Ou registre uma entrada corrigida, preservando o valor original:

```http
PATCH /api/v1/delivery-points/{point_id}/review
Content-Type: application/json

{
  "review_status":"corrected",
  "review_source":"operator",
  "review_note":"Portão lateral",
  "latitude":-23.5001,
  "longitude":-46.6001
}
```

Para aceitar todas as coordenadas ainda pendentes:

```http
POST /api/v1/routes/{route_id}/delivery-points/confirm-imported
```

Gere e consulte a matriz:

```http
POST /api/v1/routes/{route_id}/walking-matrices
Content-Type: application/json

{}

GET /api/v1/walking-matrices/{matrix_id}
GET /api/v1/walking-matrices/{matrix_id}/entries?limit=1000&offset=0
```

A identidade da matriz inclui provedor, perfil, IDs e coordenadas efetivas. Repetir a chamada sem alterar esses dados devolve a matriz existente com HTTP 200 e `idempotent=true`. Uma correção geográfica produz uma nova matriz e conserva a anterior para auditoria.

## Limite da validação atual

O protocolo OSRM, os lotes, respostas incompletas e pares sem rota possuem testes automatizados. A planilha real também é validada localmente no fluxo de revisão e no modo estimado. A aceitação de cobertura pedestre da Avenida dos Ourives exige um endpoint OSRM com extrato e perfil pedestre da região; sem esse serviço, a etapa não afirma que a rede local está correta.

O próximo incremento técnico da etapa 3 é executar essa verificação de cobertura em um serviço OSRM próprio e realizar a prova Android de GPS e áudio em segundo plano. A etapa 4 só deve usar a matriz de qualidade `network`.

## Painel de revisão e auditoria

Abra a raiz da API (`http://127.0.0.1:8000/`). Selecione ou importe uma rota, busque um endereço e confirme, corrija ou rejeite a entrada. Para corrigir, clique no mapa ou informe as coordenadas, revise a proposta e use **Salvar revisão**. Confirmação significa aceitar a coordenada **importada**, inclusive quando havia uma correção anterior; o texto da opção informa esse comportamento.

O mapa usa [Leaflet 1.9.4](https://leafletjs.com/reference.html). **Mostrar ruas** consulta somente os tiles da área exibida, com atribuição visível ao OpenStreetMap e cache normal do navegador. Não há download em massa nem modo offline de tiles. A disponibilidade desse serviço público é best effort, segundo a [política de tiles](https://operations.osmfoundation.org/policies/tiles/). Endereços e pacotes não são enviados a um geocodificador.

A revisão envia `expected_revision`. Uma versão divergente retorna HTTP 409; o operador deve recarregar o ponto. Cada gravação cria um evento em `delivery_point_reviews`, com estado anterior/posterior. A origem declarada é `operator`, `driver` ou `map`; ainda não identifica usuário autenticado.

Novos endpoints de consulta:

- `GET /api/v1/maps/config`: modo e limite configurados, sem expor endereço privado do serviço.
- `GET /api/v1/delivery-points/{id}/reviews?limit=50&offset=0`: histórico paginado.
- `GET /api/v1/routes/{id}/walking-matrices?limit=20&offset=0`: histórico de matrizes.

`input_snapshot` guarda as coordenadas, IDs, estados e revisões usados no cálculo. `stale=true` indica mudança nos pontos ou na configuração do provedor. Uma matriz legada sem snapshot também é desatualizada. O consumidor da etapa 4 deverá exigir `stale=false`, qualidade `network` e revisão dos pontos; a consulta de uma matriz histórica permanece permitida para auditoria.

## Preparar OSRM e verificar a região

Com Docker disponível e um extrato local licenciado de OpenStreetMap em `.osm.pbf`:

```powershell
.\scripts\prepare_osrm.ps1 -InputFile 'C:\mapas\regiao.osm.pbf'
docker compose -f compose.osrm.yaml up -d
$env:MAP_PROVIDER = 'osrm'
$env:OSRM_BASE_URL = 'http://localhost:5000'
$env:OSRM_PROFILE = 'foot'
$env:OSRM_DATASET_REVISION = 'cole-o-hash-exibido-pelo-script'
$env:OSRM_SNAP_RADIUS_M = '50'
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\jet-rapido-api.exe
```

O script prepara `foot.lua` com CH, recusa sobrescrever `data/osrm` existente e não baixa dados da região. `OSRM_PROFILE=foot` na URL sozinho não muda um grafo de carro para pedestre: o perfil deve ser aplicado no `osrm-extract`. A [documentação de perfis OSRM](https://project-osrm.org/docs/v26.4.0/profiles) explica essa distinção.

O limite padrão de associação à rede é 50 m, configurável. Se um ponto não encontra segmento nesse raio, a API retorna erro de provedor; isso exige revisar a entrada/cobertura, não ampliar silenciosamente o raio. A integração recusa custos parciais, respostas malformadas e versões de dados diferentes entre blocos. O timeout é por requisição; o endpoint ainda é síncrono e pode durar vários blocos.

Depois de conferir as entradas no painel, produza o relatório privado:

```powershell
.\.venv\Scripts\python.exe scripts/validate_walking.py ID_DA_ROTA --output outputs/cobertura-regiao.json
```

Esse script exige provedor `network`, não confirma coordenadas, preserva pares dirigidos de ruas divididas e recusa sobrescrita da saída. O relatório mantém `field_acceptance` pendente: custo calculado não prova portão aberto, travessia segura ou estacionamento permitido.

## Verificações desta continuação

- Testes de correções concorrentes, histórico, snapshots, desatualização por revisão/configuração e revisão durante consulta de rede.
- CI prepara o binário OSRM com uma rede **sintética**, verifica custo em footway e `NO_ROUTE` entre componentes separados. Não usa dados de entrega nem depende de servidor público.
- SQLite local, migração retrocompatível e testes de API. PostgreSQL é verificado no CI.
- Interface exercitada em navegador com dados fictícios; adaptação para desktop e celular.
- Cobertura da região real e prova Android continuam pendentes por ausência de serviço regional e aparelho/SDK.
