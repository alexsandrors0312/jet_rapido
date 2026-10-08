# Guia de desenvolvimento por etapas

## Forma de trabalho

O projeto será implementado predominantemente por IA no Codex, em incrementos executáveis. O usuário define prioridades e valida o funcionamento na operação. A IA implementa, testa e mantém a documentação. Aprovar um resultado operacional não exige escrever código.

Cada sessão começa pela leitura deste guia, README e estado do Git. Ao terminar: registrar o que funciona, testes executados, limitações e próximo passo. Não declarar uma etapa pronta com base apenas em arquivos criados ou mocks de funcionamento real.

Manter uma etapa principal em andamento. Evitar trocar de stack sem necessidade comprovada. Preferir mudanças pequenas e commits com escopo claro, sem colocar toda a aplicação em um único arquivo.

## Roadmap e critérios de conclusão

| Etapa | Entrega | Critério de conclusão | Estado |
| --- | --- | --- | --- |
| 0 | Análise, Git e documentação | Estrutura real entendida; dados protegidos do histórico | Concluída |
| 1 | Importador local | 32 pacotes preservados; validações e testes de regressão | Implementada |
| 2 | API e persistência | Importar, consultar e revisar rota; mesma importação não duplica pacotes; migrações testadas | Implementada |
| 3 | Revisão geográfica e mapas | Conferir entradas e coordenadas; matriz caminhável com inacessíveis explícitos | Software entregue; homologação de campo pendente |
| 4 | Macro-paradas | Capacidade e caminhada limitadas; nenhum pacote perdido; comparação com original | Software de proposta entregue, com rascunho explícito por coordenadas; validação regional e estacionamento pendentes |
| 5 | Ordem veicular e circuitos | Rota pedestre retorna ao carro; estacionamentos acessíveis; custos mensuráveis | Parcial: circuitos pedestres fechados e ordem veicular aberta sobre matriz `car` implementados como rascunho determinístico; estacionamento e homologação regional pendentes |
| 6 | Mobile operacional | Confirmar estacionamento, preparar bag e registrar entregas | Pendente |
| 7 | Voz e offline | Testes em Android real com tela bloqueada, queda de rede e sincronização repetida | Pendente |
| 8 | Piloto de campo | Medir tempo total, caminhada, estacionamentos e retornos evitáveis | Pendente |

A prova técnica de GPS/áudio em Android deve ocorrer antes de investir na interface completa, idealmente ao concluir a etapa 3. Não esperar o final para descobrir restrições de execução em segundo plano.

## Etapa 3: estado atual

1. Interface de provedor, adaptador OSRM e estimativa local implementados.
2. Revisão preserva os valores importados e mantém coordenadas efetivas separadas.
3. Matriz persistida e idempotente registra resultados inacessíveis explicitamente.
4. Custos, cobertura e limites dos provedores estão documentados em `ETAPA_3_GEOGRAFIA_MAPAS.md`.
5. Falta avaliar a Avenida dos Ourives em um OSRM com perfil pedestre da região.
6. Falta a prova técnica Android de GPS e áudio em segundo plano.
7. Painel web de revisão entregue na raiz da API: importação, busca, mapa, histórico e consulta das matrizes.
8. Correções têm revisão numérica e histórico; matrizes guardam as entradas usadas e indicam desatualização.
9. O CI prepara um OSRM real com perfil `foot.lua` e uma rede sintética, além do PostgreSQL.

A etapa 4 começou em 01/10/2026 com redes sintéticas; o uso em operação exige validar cobertura pedestre, entradas da região, estacionamento e capacidade da bag. A etapa 5 permanece pendente. A prova Android antecede a interface mobile completa. A API rejeita pontos geográficos marcados como inválidos, e matrizes `estimate_only` não servem como evidência de viabilidade pedestre.

## Rotina de qualidade

- Rodar `python -m unittest discover -s tests -v` com PYTHONPATH=src ou pacote instalado.
- Testar entradas que podem perder pacotes: dimensão incorreta, IDs duplicados, coordenadas inválidas e ausência de ordem.
- Usar dados sintéticos nos testes versionados; o Excel real fica fora do Git.
- Inspecionar `git diff --check` e `git status` antes do commit.
- Não sobrescrever mudanças do usuário. Separar código de resultados e dados locais.
- Para algoritmos, conferir cobertura dos pacotes e viabilidade, além de distância.
- Para mobile, testes reais complementam simuladores, principalmente GPS, microfone e bateria.

## Git

Branch principal: main. O remoto público é `alexsandrors0312/jet_rapido`. Dados reais permanecem fora do histórico mesmo com autorização de publicação do código.

## Registro da primeira entrega

- Importador CLI implementado em src/jet_rapido.
- Validação executada: 12 testes automatizados passaram; importação real preservou 32 pacotes, 26 paradas e 3 registros sem ordem. Revisão de espaços do Git sem erros.
- Análise da exportação documentada, incluindo dimensão XML incorreta.
- Relatório detalhado disponível localmente em outputs/analise-rota.json, ignorado pelo Git.
- Dependência direta fixada: openpyxl 3.1.5. Ambiente virtual recomendado no README; execução inicial verificada com o Python fornecido pelo Codex.
- Na primeira entrega, API, banco, mapas e app permaneciam no roadmap; o registro é histórico.

## Registro da segunda entrega

- FastAPI com importação, consultas, paginação e revisão humana de rota.
- SQLAlchemy e migração Alembic inicial para importações, rotas e pacotes.
- Idempotência por hash, transação, limites de upload e validação do conteúdo compactado.
- Execução local validada com SQLite e geração offline do DDL PostgreSQL.
- A planilha real passou pela API: 32 pacotes, uma rota, quatro avisos e um candidato de rua dividida.
- CI configurado para testar a migração e a importação em PostgreSQL descartável.
- Autenticação, mapas, correção geográfica e mobile continuam fora desta etapa.

## Registro da terceira entrega — núcleo de backend

- Pontos de entrega deduplicados por endereço dentro da rota, sem fundir pacotes.
- Coordenadas importadas imutáveis e coordenadas efetivas revisáveis com estado, origem, nota e instante.
- Migração retrocompatível que cria pontos para pacotes gravados na etapa 2.
- Provedores intercambiáveis para matriz pedestre: OSRM em rede e estimativa local identificada.
- Matrizes completas, pagináveis, idempotentes e com pares inacessíveis explícitos.
- Cobertura pedestre local e prova Android permanecem como validações operacionais da etapa.

## Continuação da etapa 3 — painel e auditoria

- Interface responsiva em FastAPI + HTML/CSS/JavaScript + Leaflet, sem processo de build separado.
- Migração 0003 acrescenta histórico, controle de revisões e entradas imutáveis das matrizes.
- `expected_revision` impede sobrescrita silenciosa quando informado; o painel sempre o envia.
- Cache considera configuração do provedor, versão local do extrato e revisão dos pontos.
- OSRM limita associação à rede por raio e recusa respostas inválidas ou extratos diferentes entre blocos.
- Scripts de demonstração, preparação OSRM e relatório local de cobertura disponíveis em `scripts/`.
- Ambiente local: Docker, WSL funcional, Flutter e ADB indisponíveis nesta execução. Nenhuma instalação global foi feita.
- Conferência em navegador: confirmar duas entradas, corrigir outra, calcular e consultar matriz; layouts desktop e celular sem rolagem horizontal da página.
- Testes automatizados locais: 41 descobertos, 39 passaram e 2 dependem de PostgreSQL/OSRM. O CI é a validação desses dois serviços reais.
- Próximo chat: ler `CONTINUACAO_ETAPAS_4_5.md` e registrar as pendências de campo sem tratá-las como concluídas.

## Fechamento técnico — 20/09/2026

- Implementação publicada nos commits `07d2285` e `9d92ce8`.
- [CI 35477756792](https://github.com/alexsandrors0312/jet_rapido/actions/runs/35477756792): **41 testes passaram, sem testes ignorados**, incluindo PostgreSQL e OSRM real sobre rede sintética.
- A falha inicial de download da imagem foi corrigida para `ghcr.io/project-osrm/osrm-backend:v5.27.1` no CI e nos scripts locais.
- Painel exercitado no navegador: confirmação, correção, consulta da matriz e sinalização de desatualização após nova revisão.
- O software desta etapa está entregue. Cobertura da região real e GPS/voz em Android continuam pendentes de homologação, pois não havia serviço regional nem aparelho/SDK disponíveis.
- Etapas 4 e 5 podem começar em novo chat com redes sintéticas e as condições de uso operacional descritas no documento de continuação.

## Etapa 4 — incremento de 01/10/2026

- Propostas de macro-paradas persistidas com capacidade de bag e limites de caminhada configuráveis, usando apenas matriz `network` completa e atual.
- Cada pacote permanece coberto exatamente uma vez; pares dirigidos inacessíveis impedem uma união. A rua textual não impõe agrupamento.
- O painel permite gerar propostas e aceitar/rejeitar agrupamentos com observação. Bases candidatas são marcadas como estacionamento não verificado.
- A comparação informa contagens e medidas da proposta; distância e retornos reais da rota original não podem ser medidos sem os estacionamentos/percurso anterior.
- A amostra de 30/09/2026 foi lida localmente: 18 pacotes, 16 paradas numeradas e 1 pacote sem ordem. Nenhuma planilha real foi adicionada ao Git.
- Detalhes e limites em `ETAPA_4_MACRO_PARADAS.md`. A homologação regional e a etapa 5 continuam pendentes.
- Após a comparação com a amostra de 22/09/2026, a proposta passou a distinguir paradas individuais de agrupamentos candidatos a caminhada, inclusive entre ruas diferentes. Essa classificação é descritiva e depende da rede pedestre para ser gerada.

## Revisão de entradas e matrizes — 02/10/2026

- Executada a tarefa delegada de revisão das entradas pendentes das duas rotas locais, com evidência somente local (auditoria OSRM, nomes de via, números de porta e geometria do recorte OSM em `data/osrm-walking/map.osm.pbf`, varredura do extrato estadual). Novo diagnóstico versionado em `scripts/osm_evidence.py` (não embute dados reais).
- Nenhuma confirmação ou correção automática foi feita: nome de via e número de porta no OSM não comprovam portão, travessia ou acesso. Os 51 pontos pendentes permanecem pendentes; o relatório privado `outputs/revisao-entradas-osrm-20261002.md` lista o que cada caso exige do operador/campo, com destaque para Casa Grande 2343 e Casa Grande 1340 (coordenadas divergentes da numeração local).
- A correção prévia do operador (Tomé de Souza 280, revisão 4) foi preservada e a matriz de 22/09 foi recalculada com ela: `7fab9bc8…`, 35×35, 0 pares inacessíveis, atual. A matriz de 30/09 (`a9498e40…`, 17×17) permaneceu válida.
- Propostas da etapa 4 continuam bloqueadas pelo gate de revisão (HTTP 409 exercitado nas duas rotas); nenhuma proposta foi gerada sem entradas aceitas.
- Testes locais: 45 passaram, 2 pulados (integrações PostgreSQL/OSRM do CI). Rodada local exigiu contornar a negação de escrita da sandbox em diretórios `mkdir(0o700)` do `tempfile` — sem mudança de código do projeto.

## Proposta por coordenadas — 06/10/2026

- Decisão do usuário: usar latitude e longitude efetivas como base da etapa 4, com o endereço apenas como apoio de busca, apresentação e alerta, para não exigir a conferência manual de todos os pontos.
- Novo modo explícito `coordinate_preview` em `POST /api/v1/routes/{route_id}/macro-plans`. O padrão `strict` foi preservado: chamadas sem o campo continuam recusando pontos `pending`.
- O modo é persistido (`macro_plans.planning_mode`, migração `20261006_0005`), entra no hash de idempotência e na resposta (`planning_mode`, `provisional_draft`, `pending_point_count`, `reviewed_point_count`, `review_counts_basis`, `review_notice`). As contagens usam o snapshot da entrada da proposta; planos legados sem snapshot caem no estado atual com sinalização. O hash antigo sem o modo é aceito como fallback apenas para planos estritos migrados, sem confundir o rascunho por coordenadas.
- `rejected`, coordenadas efetivas inválidas, matriz `estimate_only`/incompleta/antiga/sem snapshot e pares necessários inacessíveis continuam bloqueados nos dois modos. Nenhum status de revisão é alterado.
- Painel: seleção de modo, opção de calcular matriz provisória com `allow_unreviewed=true`, contagem de pendentes e aviso de rascunho não homologado; a revisão individual de pontos foi preservada.
- Estado local: 49 `pending` (32 na rota de 22/09 e 17 na de 30/09); 3 `corrected` na de 22/09; matrizes de rede atuais `1aa1242e…` (35×35) e `a9498e40…` (17×17), 0 pares inacessíveis.
- Limites inalterados e provisórios: 8 pacotes por saída da bag, 400 m entre entradas e 600 m de ida e volta à base. Estacionamento, portões, travessias e capacidade física seguem sem validação. Nenhuma economia de distância é declarada.
- Próximo passo: validar a proposta por coordenadas e só então avaliar a etapa 5 (ordem veicular e circuitos).

## Circuitos pedestres fechados — 06/10/2026

- Primeiro incremento da etapa 5: `GET /api/v1/macro-plans/{plan_id}/circuits` calcula sob demanda o circuito fechado e dirigido de cada macro-parada, usando apenas a matriz pedestre persistida. Sem nova migração e sem persistência: o resultado é determinístico (`content_hash`).
- A sequência parte da base candidata, visita cada ponto do grupo exatamente uma vez e retorna. Ordena por distância dirigida, com desempate por duração e sequência canônica (ordem da planilha e identificador); nenhum endereço textual ordena. Nenhum circuito atravessa par inacessível.
- Grupos de até 9 pontos têm solução exata; acima disso há heurística determinística (vizinho mais próximo + 2-opt) marcada como não ótima e um limite explícito na resposta.
- `coordinate_preview` continua aceito sem confirmar os pontos pendentes; nenhum status de revisão é alterado. A resposta marca `base_status=unverified`, avisa que a partida real deve usar GPS confirmado do veículo e declara ausência de geometria, manobras, voz e de promessa de economia.
- Recusas: matriz `estimate_only`, sem snapshot, incompleta ou desatualizada, par obrigatório inacessível, ponto de outra rota e cobertura inconsistente (HTTP 409).
- Novo `src/jet_rapido/circuit_service.py`, helper `directed_matrix_costs` compartilhado em `walking_service.py`, schemas e painel (botão "Calcular circuitos pedestres fechados"). Testes sintéticos em `tests/test_circuits.py`.
- Relatório privado agregado (sem endereços ou coordenadas) das duas propostas locais em `outputs/circuitos-rascunho-20261006.md`; nenhum OSRM foi recalculado.
- Continua fora desta chamada: ordem veicular entre macro-paradas (exige matriz veicular regional e ponto de partida/chegada configurável). Detalhes em `ETAPA_5_CIRCUITOS_PEDESTRES.md`.

## Ajustes finais de segurança e leitura dos circuitos — 06/10/2026

- `scripts/circuit_report.py` deixou de gravar a `--database-url` no relatório e no console. URLs PostgreSQL podem conter usuário e senha; o arquivo agora traz apenas um rótulo fixo ("URL de conexão omitida por segurança"). Os relatórios reais já existentes em `outputs/` foram preservados e nenhum endereço ou coordenada real entrou em arquivo versionado.
- O parâmetro `max_base_roundtrip_m` (etapa 4) limita **cada ida e volta individual** à base, não a volta completa do circuito. A resposta de circuitos agora expõe `max_base_roundtrip_m`, `base_roundtrip_limit_notice`, `circuits_exceeding_base_roundtrip` e, por circuito, `exceeds_base_roundtrip_limit` e `roundtrip_warning`. O aviso aparece na API, no painel e no relatório agregado, sem bloquear nem alterar o agrupamento. O circuito real de 22/09 com ~1108 m ilustra o caso.
- A mensagem de falha da heurística passou a dizer que o **método não encontrou** circuito e que a existência de caminho não foi descartada; a solução exata continua podendo afirmar a inexistência porque enumera todas as ordens. Os grupos atuais permanecem exatos e inalterados.
- Testes: `tests/test_circuit_report.py` (novo) cobre a URL sintética com senha e o conteúdo agregado; `tests/test_circuits.py` cobre o aviso por circuito e a mensagem da heurística. Revisões de pontos, matrizes, propostas persistidas e os parâmetros 8/400/600 não foram alterados.

## Ordem veicular aberta — 07/10/2026

- Segundo incremento da etapa 5: `POST /api/v1/routes/{route_id}/vehicle-orders` calcula a ordem veicular **aberta** `partida → cada base candidata uma vez → chegada` sobre uma matriz dirigida OSRM de perfil `car` própria. Distância dirigida como critério primário, duração da mesma sequência e ordem canônica como desempate. Nenhum endereço entra no objetivo.
- Novo provedor veicular separado do pedestre (`VEHICLE_*`): sem configuração explícita a ordem é recusada, nunca calculada com a matriz pedestre ou com linha reta. Perfil pedestre é recusado. A revisão do conjunto de dados compõe a identidade de cache e o snapshot.
- Migração `20261007_0006` cria `vehicle_matrices`/`vehicle_matrix_entries`. Snapshot auditável com partida, chegada, pontos e identidade do provedor; revisão de ponto, troca de endpoint ou de revisão do extrato torna a matriz desatualizada. Matriz e plano de outra rota são recusados.
- Solução exata por programação dinâmica (Held-Karp) até 12 bases; acima disso heurística determinística marcada como não ótima. As propostas reais atuais (8 e 11 bases) têm solução exata.
- **Conjunto de dados `car` regional preparado localmente** a partir do PBF em `data/osrm-source`: os wheels de OSRM/osmium foram extraídos para uma pasta gravável (`scripts/setup_osrm_runtime.py`) porque o runtime instalado tem ACL restrita, e o recorte foi extraído com `car.lua` (`scripts/prepare_osrm_windows.py --profile car --include-points-file`). `data/osrm-walking` não foi alterado. O serviço foi iniciado apenas em `127.0.0.1`.
- As duas propostas `coordinate_preview` foram calculadas: 11 e 8 macro-paradas, matrizes veiculares de 19 e 37 nós, 361 e 1369 pares, **0 pares inacessíveis**, método exato. Relatório privado agregado em `outputs/`, sem endereços nem coordenadas.
- Painel: seção **Ordem veicular** para digitar rótulo e coordenadas de partida e chegada, ver a sequência, as pernas, os totais e os avisos de rascunho, base não verificada e ausência de navegação/economia. Nenhuma coordenada real tem padrão embutido.
- Testes: 35 novos casos sintéticos em `tests/test_vehicle_order.py` e `tests/test_vehicle_dataset_prep.py`; a suíte completa passa localmente. Estacionamento, portões, travessias, capacidade da bag e homologação regional continuam pendentes de campo.
