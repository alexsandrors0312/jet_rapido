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
| 3 | Revisão geográfica e mapas | Conferir entradas e coordenadas; matriz caminhável com inacessíveis explícitos | Próxima |
| 4 | Macro-paradas | Capacidade e caminhada limitadas; nenhum pacote perdido; comparação com original | Pendente |
| 5 | Ordem veicular e circuitos | Rota pedestre retorna ao carro; estacionamentos acessíveis; custos mensuráveis | Pendente |
| 6 | Mobile operacional | Confirmar estacionamento, preparar bag e registrar entregas | Pendente |
| 7 | Voz e offline | Testes em Android real com tela bloqueada, queda de rede e sincronização repetida | Pendente |
| 8 | Piloto de campo | Medir tempo total, caminhada, estacionamentos e retornos evitáveis | Pendente |

A prova técnica de GPS/áudio em Android deve ocorrer antes de investir na interface completa, idealmente ao concluir a etapa 3. Não esperar o final para descobrir restrições de execução em segundo plano.

## Próxima sessão: etapa 3

1. Definir uma interface de provedor de mapas independente de Google, Mapbox ou OSRM.
2. Criar revisão de endereço/entrada sem alterar o valor original importado.
3. Calcular e armazenar matriz pedestre com resultados inacessíveis explícitos.
4. Avaliar Avenida dos Ourives da amostra com distância de rede, não somente texto.
5. Preparar a prova técnica Android de GPS e áudio em segundo plano.
6. Documentar custo, cobertura e limites do provedor escolhido antes de formar clusters.

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
