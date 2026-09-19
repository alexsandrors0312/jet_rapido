# Jet Rápido

Assistente de entregas last-mile: planejar onde estacionar, quais pacotes levar e como fazer o circuito a pé até voltar ao carro.

**Estado: etapa 1 implementada — importação local da exportação SPX.** Ainda não há API, banco, algoritmo de macro-paradas ou aplicativo mobile. O desenvolvimento é incremental, conduzido aqui no Codex e orientado pelo [guia](docs/GUIA_DESENVOLVIMENTO.md).

## Executar no Windows

Na pasta do projeto, com Python 3.12 ou superior:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m jet_rapido.cli 'C:\Users\Alexs\Documents\rota shoppe.xlsx'
```

Para salvar detalhes com dados de entrega, forneça um caminho novo:

```powershell
.\.venv\Scripts\python.exe -m jet_rapido.cli 'C:\Users\Alexs\Documents\rota shoppe.xlsx' --output outputs/rota-01.json
```

O resumo do terminal contém apenas contagens. O JSON contém endereços, coordenadas e códigos de pacote: é local e ignorado pelo Git. O arquivo original não é modificado. A ferramenta recusa sobrescrever uma saída existente.

## Documentação

- [Guia por etapas e rotina de trabalho](docs/GUIA_DESENVOLVIMENTO.md)
- [Análise da planilha recebida](docs/ANALISE_PLANILHA.md)
- [Contrato de importação](docs/IMPORTACAO.md)
- [Arquitetura e modelo de dados planejados](docs/ARQUITETURA.md)

O repositório é Git local. Publicação no GitHub será uma etapa separada, com destino e visibilidade definidos.
