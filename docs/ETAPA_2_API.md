# Etapa 2 — API e persistência

## Resultado

A API FastAPI recebe a exportação XLSX, reutiliza o importador da etapa 1 e persiste a importação em uma transação. O modelo inicial contém `import_batches`, `routes` e `packages`. Alembic controla a evolução do schema.

Uma importação byte a byte idêntica retorna a mesma entidade: a primeira resposta usa HTTP 201 e as seguintes usam HTTP 200 com `idempotent: true`. A restrição única no SHA-256 protege também contra duas requisições concorrentes. Um XLSX reexportado pode ter bytes diferentes mesmo quando seus registros parecem iguais; deduplicação semântica será uma decisão separada.

## Endpoints

| Método | Caminho | Função |
| --- | --- | --- |
| GET | `/health` | Testa conexão com o banco |
| POST | `/api/v1/imports` | Valida e importa um XLSX multipart |
| GET | `/api/v1/imports/{id}` | Consulta resultado, avisos e rotas |
| GET | `/api/v1/routes` | Lista rotas com `limit`, `offset` e filtro `import_id` |
| GET | `/api/v1/routes/{id}` | Consulta a rota e todos os seus pacotes |
| PATCH | `/api/v1/routes/{id}/review` | Marca ou desmarca revisão humana |

Swagger/OpenAPI fica disponível em `/docs` durante a execução local.

## Regras operacionais

- Upload padrão limitado a 5 MiB.
- Conteúdo descompactado limitado a 50 MiB e mil membros internos.
- Arquivo temporário removido após sucesso ou falha.
- Extensão, estrutura OOXML, fórmulas, IDs, coordenadas e tamanhos de texto são validados.
- Um erro de qualquer linha cancela toda a gravação; nenhum pacote válido é descartado silenciosamente.
- `source_row`, referência original, endereço, coordenadas e chave candidata de rua permanecem auditáveis.
- Planilha original não é armazenada pelo serviço nesta etapa.

Os limites podem ser definidos pelas variáveis descritas em `.env.example`. Alterar limites exige considerar memória, tempo de processamento e capacidade do serviço.

## Banco

O ambiente local usa SQLite por padrão. PostgreSQL é o banco alvo e o `compose.yaml` fornece PostGIS para as próximas etapas geográficas. A migração inicial é compatível com ambos. O CI inicia PostgreSQL real, aplica Alembic e testa a importação idempotente.

Não existe autenticação ainda. A API deve permanecer local ou atrás de controle de acesso até uma etapa de segurança operacional. O endpoint também não implementa antivírus, retenção da fonte, fila de jobs ou limitação por usuário.

## Testar

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes locais cobrem importação, migração SQLite, leitura, revisão, idempotência, rollback de arquivo inválido, limites e estrutura do XLSX. O teste PostgreSQL é ativado quando `JET_RAPIDO_TEST_POSTGRES_URL` está definido; o workflow do GitHub define essa variável com um banco descartável.
