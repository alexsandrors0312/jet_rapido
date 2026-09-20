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
| 4 | Macro-paradas | Capacidade e caminhada limitadas; nenhum pacote perdido; comparação com original | Pendente |
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

As etapas 4 e 5 serão desenvolvidas em um novo chat, conforme combinado. Podem ser verificadas inicialmente com redes sintéticas; o uso em operação exige validar cobertura pedestre e entradas da região. A prova Android antecede a interface mobile completa. A API rejeita pontos geográficos marcados como inválidos, e matrizes `estimate_only` não servem como evidência de viabilidade pedestre.

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
