# Análise da exportação recebida

Fonte: `rota shoppe.xlsx`, aba `Sheet1`, conteúdo efetivo `A1:J33`. Arquivo original mantido fora do repositório.

## Resultado observado

| Medida | Resultado |
| --- | ---: |
| Registros de pacote | 32 |
| Códigos SPX TN distintos | 32 |
| AT IDs distintos | 1 |
| Paradas originais numeradas | 26 |
| Registros sem parada | 3 |
| Registros sem sequência | 3 |
| Textos de endereço distintos | 32 |
| Pares latitude/longitude distintos | 29 |
| Grupos de coordenadas compartilhadas | 2 |
| Bairros com grafia distinta | 8 |
| Cidades distintas | 1 |

Esta amostra não contém os 124 pacotes/66 paradas do exemplo inicial. Uma linha representa um pacote identificado por SPX TN, não uma macro-parada. Existem 29 pacotes com sequência e 3 sem sequência. A parada 1 tem 2 pacotes, a parada 25 tem 3 e as demais paradas numeradas têm 1 cada.

## Problema técnico confirmado

O XML declara a dimensão `A1:A1`, mas contém dez colunas e 33 linhas. Uma leitura em streaming que respeite essa dimensão pode retornar apenas o primeiro cabeçalho. O importador usa `reset_dimensions()` antes de iterar. Há teste de regressão com um XLSX sintético que reproduz o defeito.

## Evidência relacionada ao problema de roteirização

`Avenida dos Ourives` e `Av dos Ourives` aparecem nas paradas 4, 5 e 6. A normalização textual encontra um único candidato de rua distribuído entre várias paradas. Isso não comprova retorno desnecessário: as paradas são consecutivas e ainda é preciso medir distâncias, acessos e capacidade.

Não há campos vazios nas dez colunas, exceto os marcadores `-` de Sequence e Stop em três registros. Há um endereço com `S/N`, que requer atenção na localização da entrada. Todas as coordenadas passam na validação numérica e de limites globais; isso não comprova precisão da entrada ou correspondência com o endereço.

Coordenadas repetidas com endereços distintos não autorizam fundir pacotes ou edifícios. Podem representar o mesmo acesso, aproximação do geocodificador ou um erro. A próxima etapa deve permitir revisão.

## O que falta para otimizar com segurança operacional

- Distâncias e geometria na rede pedestre, incluindo barreiras e acessos.
- Pontos candidatos de estacionamento e posição real confirmada pelo motorista.
- Capacidade prática da bag. O arquivo não fornece peso nem volume.
- Tempo de atendimento, restrições e eventuais janelas de entrega.
- Identidade de trecho de rua. A chave textual gerada nesta etapa é apenas uma candidata.

Conclusão: o arquivo é utilizável para iniciar o produto, sem geocodificar novamente todos os registros. A revisão de qualidade e o cálculo de caminhos reais antecedem qualquer promessa de economia.
