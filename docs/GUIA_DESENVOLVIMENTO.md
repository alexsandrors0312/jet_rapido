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
| 5 | Ordem veicular e circuitos | Rota pedestre retorna ao carro; estacionamentos acessíveis; custos mensuráveis | Pendente |
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
