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
