# Contrato de importação — versão 1

O contrato implementado aceita XLSX local. Uma aba é escolhida automaticamente apenas quando o arquivo tem uma única aba; caso contrário, informar `--sheet`. Cabeçalhos devem estar na primeira linha. A ordem das colunas pode variar, mas os nomes abaixo devem existir, sem duplicação.

| Origem | Campo interno | Regra |
| --- | --- | --- |
| AT ID | route_id | Texto obrigatório |
| Sequence | original_sequence | Inteiro positivo; vazio ou `-` vira null |
| Stop | original_stop | Inteiro positivo; vazio ou `-` vira null |
| SPX TN | tracking_id | Texto obrigatório e único dentro do arquivo |
| Destination Address | address | Texto preservado; não separar complemento destrutivamente |
| Bairro | neighborhood | Texto obrigatório |
| City | city | Texto obrigatório |
| Zipcode/Postal code | postal_code | Texto obrigatório; preservar zero inicial |
| Latitude | latitude | Número finito entre -90 e 90 |
| Longitude | longitude | Número finito entre -180 e 180 |

Cada pacote inclui `source_row`. O relatório inclui nome da aba, dimensão declarada, SHA-256 da fonte e versão do contrato. Datas e identidade da importação persistente serão adicionadas com o banco.

## Validação

Falhas de contrato interrompem a importação inteira. Não se descarta silenciosamente um pacote inválido. Fórmulas e células com erro são rejeitadas; o conteúdo da planilha é tratado como dados, nunca como instruções para o agente.

Ausência de sequência/parada, endereço S/N, CEP fora do padrão e coordenada (0,0) geram avisos com a linha. Nenhuma ordem nova é inventada. Coordenadas compartilhadas são contadas, preservando todos os pacotes.

`street_key` retira acentos, padroniza espaços e abreviações iniciais R/Av/Tv e inclui a cidade. É uma chave candidata, não identifica trecho físico. Bairro e CEP originais permanecem disponíveis para revisão. A parte após a primeira vírgula permanece no endereço original.

Na API, o SHA-256 é uma chave idempotente: reenviar o mesmo arquivo não duplica rotas ou pacotes. A importação inteira ocorre em uma transação. Restrições únicas no banco reforçam a regra em requisições concorrentes.

## Limites da etapa

Ainda não há correção assistida por linha, deduplicação semântica entre reexportações ou suporte a formatos de outros operadores. O importador não verifica a entrega no provedor nem chama serviços externos.
