# Jet Rápido

Assistente de entregas last-mile: planejar onde estacionar, quais pacotes levar e como fazer o circuito a pé até voltar ao carro.

**Estado: etapa 4 implementada como proposta revisável; etapa 5 iniciada com circuitos pedestres fechados e ordem veicular aberta (rascunhos); homologação regional pendente.** A aplicação importa o XLSX, preserva endereços e coordenadas originais, permite confirmar ou corrigir pontos, persiste matrizes pedestres auditáveis e agrupa pontos em macro-paradas com limites configuráveis. O modo estrito continua sendo o padrão; um modo explícito por coordenadas efetivas gera rascunhos não homologados quando há pontos pendentes. Sobre uma proposta, a API calcula sob demanda o circuito pedestre fechado de cada macro-parada e a ordem veicular aberta das bases sobre uma matriz OSRM de perfil `car` própria — sequência de pontos, sem geometria, manobras, voz ou estacionamento confirmado. O adaptador OSRM está implementado; sem cobertura pedestre e veicular validada da região, nenhuma proposta deve ser usada em operação.

O painel está na página inicial da API: **http://127.0.0.1:8000/**. Nele é possível importar a planilha, buscar endereços, selecionar pontos no mapa, corrigir entradas, consultar o histórico, calcular matrizes, gerar/revisar propostas de macro-paradas, calcular os circuitos pedestres fechados e digitar a partida e a chegada para calcular a ordem veicular das bases. Matrizes e propostas de revisões anteriores aparecem como desatualizadas.

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

Para gerar macro-paradas, confirme ou corrija todos os pontos e calcule uma matriz `network` atual. O padrão provisório é 8 pacotes por saída da bag; os limites de caminhada podem ser ajustados na tela. A base calculada não é um estacionamento confirmado. Quando a conferência manual for lenta demais, o painel oferece o modo explícito **Por coordenadas**, que agrupa pelas coordenadas efetivas mesmo com entradas pendentes e marca a proposta como rascunho não homologado. Consulte [a etapa 4](docs/ETAPA_4_MACRO_PARADAS.md).

Sobre uma proposta já criada, o botão **Calcular circuitos pedestres fechados** devolve, por macro-parada, a sequência que parte da base candidata, visita cada ponto uma vez e retorna. O cálculo é determinístico e usa só a matriz pedestre persistida: grupos de até 9 pontos têm solução exata e grupos maiores usam heurística marcada como não ótima. O limite de 600 m da etapa 4 vale **por ida e volta individual** à base, não para a volta completa; quando a distância do circuito supera esse parâmetro, a API, o painel e o relatório agregado exibem o aviso sem bloquear o agrupamento. É um rascunho de sequência de pontos — sem geometria, manobras, voz ou estacionamento confirmado — e a partida real deve usar o GPS confirmado do veículo. Consulte [a etapa 5](docs/ETAPA_5_CIRCUITOS_PEDESTRES.md).

A seção **Ordem veicular** calcula a ordem aberta `partida → cada base candidata uma vez → chegada` sobre uma matriz dirigida OSRM de perfil **`car`** própria, com endpoint, revisão e raio configurados por `VEHICLE_*`. A matriz pedestre e a estimativa em linha reta não substituem a via; sem provedor veicular configurado a ordem é recusada. Distância dirigida é o critério primário, com duração da mesma sequência e ordem canônica como desempate; até 12 bases a solução é exata e acima disso a heurística é marcada como não ótima. O procedimento para preparar o recorte `car` regional está em [ETAPA_5_ORDEM_VEICULAR.md](docs/ETAPA_5_ORDEM_VEICULAR.md).

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
- [Macro-paradas](docs/ETAPA_4_MACRO_PARADAS.md)
- [Circuitos pedestres fechados (etapa 5, rascunho)](docs/ETAPA_5_CIRCUITOS_PEDESTRES.md)
- [Ordem veicular aberta (etapa 5, rascunho)](docs/ETAPA_5_ORDEM_VEICULAR.md)
- [Arquitetura e modelo de dados planejados](docs/ARQUITETURA.md)
- [Retomada das etapas 4 e 5 em novo chat](docs/CONTINUACAO_ETAPAS_4_5.md)

Repositório público: https://github.com/alexsandrors0312/jet_rapido. Nunca enviar planilhas, JSON de análise ou bancos locais ao Git.
