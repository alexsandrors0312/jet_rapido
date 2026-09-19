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
| 2 | API e persistência | Importar, consultar e revisar rota; mesma importação não duplica pacotes; migrações testadas | Próxima |
| 3 | Revisão geográfica e mapas | Conferir entradas e coordenadas; matriz caminhável com inacessíveis explícitos | Pendente |
| 4 | Macro-paradas | Capacidade e caminhada limitadas; nenhum pacote perdido; comparação com original | Pendente |
| 5 | Ordem veicular e circuitos | Rota pedestre retorna ao carro; estacionamentos acessíveis; custos mensuráveis | Pendente |
| 6 | Mobile operacional | Confirmar estacionamento, preparar bag e registrar entregas | Pendente |
| 7 | Voz e offline | Testes em Android real com tela bloqueada, queda de rede e sincronização repetida | Pendente |
| 8 | Piloto de campo | Medir tempo total, caminhada, estacionamentos e retornos evitáveis | Pendente |

A prova técnica de GPS/áudio em Android deve ocorrer antes de investir na interface completa, idealmente ao concluir a etapa 3. Não esperar o final para descobrir restrições de execução em segundo plano.

## Próxima sessão: etapa 2

1. Definir modelos de importação, rota e pacote e migração inicial.
2. Adicionar FastAPI reutilizando import_workbook.
3. Criar importação com resultado estruturado e consulta da rota.
4. Adicionar idempotência, limites de upload e transações.
5. Verificar persistência em PostgreSQL real de desenvolvimento e testes de integração.
6. Documentar inicialização e demonstrar o resultado antes de avançar para mapas.

## Rotina de qualidade

- Rodar `python -m unittest discover -s tests -v` com PYTHONPATH=src ou pacote instalado.
- Testar entradas que podem perder pacotes: dimensão incorreta, IDs duplicados, coordenadas inválidas e ausência de ordem.
- Usar dados sintéticos nos testes versionados; o Excel real fica fora do Git.
- Inspecionar `git diff --check` e `git status` antes do commit.
- Não sobrescrever mudanças do usuário. Separar código de resultados e dados locais.
- Para algoritmos, conferir cobertura dos pacotes e viabilidade, além de distância.
- Para mobile, testes reais complementam simuladores, principalmente GPS, microfone e bateria.

## Git

Branch inicial: main. O Git é local e não há remoto configurado. O primeiro commit pode usar autoria técnica Codex quando não existir identidade Git do usuário; nunca alterar a configuração global do usuário.

Publicação no GitHub exige definir conta/repositório e visibilidade. Recomenda-se privado para o desenvolvimento, mantendo dados reais fora do histórico mesmo assim. A criação do Git local não equivale a publicar no GitHub.

## Registro da primeira entrega

- Importador CLI implementado em src/jet_rapido.
- Validação executada: 12 testes automatizados passaram; importação real preservou 32 pacotes, 26 paradas e 3 registros sem ordem. Revisão de espaços do Git sem erros.
- Análise da exportação documentada, incluindo dimensão XML incorreta.
- Relatório detalhado disponível localmente em outputs/analise-rota.json, ignorado pelo Git.
- Dependência direta fixada: openpyxl 3.1.5. Ambiente virtual recomendado no README; execução inicial verificada com o Python fornecido pelo Codex.
- API, banco, mapas e app permanecem no roadmap; não foram simulados como funcionalidades prontas.
