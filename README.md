# Jet Rápido

Assistente de entregas last-mile: planejar onde estacionar, quais pacotes levar e como fazer o circuito a pé até voltar ao carro.

**Estado: etapa 3 em validação operacional — revisão geográfica e mapas.** A aplicação importa o XLSX, preserva endereços e coordenadas originais, permite confirmar ou corrigir pontos e persiste matrizes pedestres auditáveis. O adaptador OSRM está implementado; a cobertura da região ainda precisa ser validada em um serviço com perfil pedestre antes de formar macro-paradas.

O painel de revisão está na página inicial da API: **http://127.0.0.1:8000/**. Nele é possível importar a planilha, buscar endereços, selecionar pontos no mapa, corrigir entradas, consultar o histórico e calcular matrizes. Matrizes de revisões anteriores aparecem como desatualizadas.

Para experimentar com três endereços fictícios, em um banco separado:

```powershell
.\.venv\Scripts\python.exe scripts/review_demo.py
$env:DATABASE_URL = 'sqlite:///outputs/review-demo.db'
.\.venv\Scripts\jet-rapido-api.exe
```

O mapa de ruas é carregado ao clicar em **Mostrar ruas**. A biblioteca Leaflet usa CDN com versão fixa e integridade verificada; a revisão por coordenadas continua disponível se o mapa não carregar. A demonstração preserva os ajustes já salvos quando executada novamente.

## Executar no Windows

Na pasta do projeto, com Python 3.12 ou superior:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m jet_rapido.cli 'C:\caminho\rota shoppe.xlsx'
```

## Iniciar a API com SQLite

SQLite é suficiente para desenvolvimento local nesta etapa. O banco fica em `data/jet_rapido.db` e não entra no Git.

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\jet-rapido-api.exe
```

A documentação interativa fica em http://127.0.0.1:8000/docs. Para importar a planilha:

```powershell
curl.exe -F "file=@C:\caminho\rota shoppe.xlsx" http://127.0.0.1:8000/api/v1/imports
```

O provedor padrão `straight_line` serve para testes locais e identifica a matriz como `estimate_only`. Para usar rede pedestre, configure `MAP_PROVIDER=osrm` e aponte `OSRM_BASE_URL` para um serviço preparado com o extrato e perfil da região. Consulte o guia da etapa 3 antes de usar uma matriz em clusterização.

## Iniciar com PostgreSQL/PostGIS

Com Docker disponível:

```powershell
docker compose up -d
$env:DATABASE_URL = 'postgresql+psycopg://jet_rapido:jet_rapido@localhost:5432/jet_rapido'
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\jet-rapido-api.exe
```

Copie os valores de `.env.example` para o gerenciador de ambiente usado na implantação. A aplicação não cria nem altera tabelas ao iniciar: executar as migrações é um passo explícito.

Para salvar detalhes com dados de entrega, forneça um caminho novo:

```powershell
.\.venv\Scripts\python.exe -m jet_rapido.cli 'C:\caminho\rota shoppe.xlsx' --output outputs/rota-01.json
```

O resumo do terminal contém apenas contagens. O JSON contém endereços, coordenadas e códigos de pacote: é local e ignorado pelo Git. O arquivo original não é modificado. A ferramenta recusa sobrescrever uma saída existente.

## Documentação

- [Guia por etapas e rotina de trabalho](docs/GUIA_DESENVOLVIMENTO.md)
- [Análise da planilha recebida](docs/ANALISE_PLANILHA.md)
- [Contrato de importação](docs/IMPORTACAO.md)
- [API e persistência](docs/ETAPA_2_API.md)
- [Revisão geográfica e mapas](docs/ETAPA_3_GEOGRAFIA_MAPAS.md)
- [Arquitetura e modelo de dados planejados](docs/ARQUITETURA.md)
- [Retomada das etapas 4 e 5 em novo chat](docs/CONTINUACAO_ETAPAS_4_5.md)

Repositório público: https://github.com/alexsandrors0312/jet_rapido. Nunca enviar planilhas, JSON de análise ou bancos locais ao Git.
