# Arquitetura planejada

## Decisões

- Python para domínio, importação e otimização. Etapa atual depende somente de openpyxl.
- FastAPI implementada para importação e consulta, reutilizando o núcleo sem regras duplicadas.
- SQLAlchemy e Alembic implementados. PostgreSQL/PostGIS é o alvo; SQLite atende desenvolvimento local.
- Flutter como escolha inicial para Android primeiro; confirmar viabilidade de GPS e voz com tela bloqueada em aparelho real antes de ampliar a interface.
- Provedor de mapas atrás da interface de matriz pedestre. O adaptador OSRM e o modo estimado local estão implementados; matriz veicular e geometria entram quando seus fluxos forem usados.
- Fila de processamento quando a integração de mapas tornar as operações demoradas; não adicionar Redis/Celery antes dessa necessidade.

## Fluxo

XLSX → validação → revisão geográfica → macro-paradas → ordem veicular → estacionamento confirmado → bag → circuito pedestre → retorno ao carro.

A macro-parada representa uma base de estacionamento, com um ou mais circuitos de bag. A parada original do operador é preservada separadamente. Nem a ordem original nem uma rua textual são restrições absolutas do novo plano.

## Modelo previsto para o banco

| Entidade | Responsabilidade |
| --- | --- |
| importacao | Hash, versão do contrato, origem, análise e status |
| rota | Motorista, operação, versão do plano |
| pacote | Identificador, endereço, referência original e estado |
| ponto_entrega | Entrada original, coordenada importada, coordenada efetiva e proveniência da revisão |
| matriz_pedestre | Versão do provedor, perfil, hash das entradas e contagens de acessibilidade |
| matriz_pedestre_par | Custo dirigido entre dois pontos ou motivo explícito da inacessibilidade |
| macro_parada | Base planejada e ordem veicular |
| macro_parada_endereco | Associação dos endereços ao plano |
| sessao_macro_parada | Execução e GPS real do estacionamento |
| circuito_bag | Percurso a pé com início/fim no veículo |
| bag_item | Pacote carregado, retirada e resultado |
| evento_entrega | Confirmação auditável e chave idempotente |

Importação, rota, pacote, ponto de entrega e matriz pedestre estão implementados. As entidades de execução entram quando seus fluxos existirem, evitando tabelas especulativas sem comportamento validado.

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

## Referências de mapas

- https://developers.google.com/maps/documentation/routes/compute_route_matrix
- https://developers.google.com/maps/documentation/routes/reference/rest/v2/RouteTravelMode
- https://project-osrm.org/docs/v5.24.0/api/
- https://developers.google.com/optimization/routing/routing_tasks

Rever limites, suporte e condições atuais quando a integração for implementada.
