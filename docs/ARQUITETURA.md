# Arquitetura planejada

## Decisões

- Python para domínio, importação e otimização. Etapa atual depende somente de openpyxl.
- FastAPI para API na próxima etapa, reutilizando o núcleo sem regras duplicadas.
- PostgreSQL/PostGIS e migrações para persistência de rotas e execução.
- Flutter como escolha inicial para Android primeiro; confirmar viabilidade de GPS e voz com tela bloqueada em aparelho real antes de ampliar a interface.
- Provedor de mapas atrás de interfaces para matriz pedestre, matriz veicular e geometria. Seleção final depende de cobertura, custo e termos de uso. Não há provedor contratado nem chamadas externas nesta etapa.
- Fila de processamento quando a integração de mapas tornar as operações demoradas; não adicionar Redis/Celery antes dessa necessidade.

## Fluxo

XLSX → validação → revisão geográfica → macro-paradas → ordem veicular → estacionamento confirmado → bag → circuito pedestre → retorno ao carro.

A macro-parada representa uma base de estacionamento, com um ou mais circuitos de bag. A parada original do operador é preservada separadamente. Nem a ordem original nem uma rua textual são restrições absolutas do novo plano.

## Modelo previsto para o banco

| Entidade | Responsabilidade |
| --- | --- |
| importacao | Hash, versão do contrato, origem e status |
| rota | Motorista, operação, versão do plano |
| pacote | Identificador, endereço, referência original e estado |
| endereco | Entrada geográfica revisada, complemento e proveniência |
| macro_parada | Base planejada e ordem veicular |
| macro_parada_endereco | Associação dos endereços ao plano |
| sessao_macro_parada | Execução e GPS real do estacionamento |
| circuito_bag | Percurso a pé com início/fim no veículo |
| bag_item | Pacote carregado, retirada e resultado |
| evento_entrega | Confirmação auditável e chave idempotente |

`sessao_macro_parada.veiculo_estacionado_em` será geography(Point,4326), acompanhado de precisão em metros, instante e confirmação por voz/botão. Nunca substituir pelo centro calculado do cluster.

`pacotes_na_bag` será projeção de bag_item, não um array sem integridade no banco. Pacote de tentativa frustrada permanece fisicamente na bag até sua retirada. Transações e restrições devem impedir duas bags ativas para o mesmo pacote. O circuito permite reposição sem mover o carro.

## Invariantes futuras

1. Nenhum pacote desaparece entre importação e plano.
2. Um endereço pertence a uma macro-parada por versão do plano.
3. Todo circuito pedestre termina no estacionamento real.
4. Rua igual não implica acesso próximo; DBSCAN não limita diâmetro sozinho.
5. Geometria e manobras vêm da rede; a ordem de visita não gera instruções de esquina por si só.
6. Aproximação GPS não confirma estacionamento nem entrega automaticamente.
7. Eventos offline são reprocessáveis sem duplicar entregas.
8. Reotimização preserva execução em andamento.

## Referências para a etapa de mapas

- https://developers.google.com/maps/documentation/routes/compute_route_matrix
- https://developers.google.com/maps/documentation/routes/reference/rest/v2/RouteTravelMode
- https://project-osrm.org/docs/v5.22.0/api/
- https://developers.google.com/optimization/routing/routing_tasks

Rever limites, suporte e condições atuais quando a integração for implementada.
