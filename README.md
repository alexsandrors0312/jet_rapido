# Jet Rápido

Assistente de entregas last-mile: planejar onde estacionar, quais pacotes levar e como fazer o circuito a pé até voltar ao carro.

**Estado: etapa 2 implementada — API e persistência.** A aplicação importa o XLSX, grava rotas e pacotes, evita duplicação do mesmo arquivo e permite revisar uma rota. Macro-paradas, mapas e aplicativo mobile continuam nas próximas etapas.

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
- [Arquitetura e modelo de dados planejados](docs/ARQUITETURA.md)

Repositório público: https://github.com/alexsandrors0312/jet_rapido. Nunca enviar planilhas, JSON de análise ou bancos locais ao Git.
