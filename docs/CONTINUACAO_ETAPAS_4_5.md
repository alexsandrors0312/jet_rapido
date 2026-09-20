# Retomada em novo chat — etapas 4 e 5

## Pedido do usuário

Continuar o Jet Rápido na pasta `C:/Users/Alexs/Desktop/jet_rapido`. Desenvolver as etapas 4 (macro-paradas) e 5 (ordem veicular e circuitos pedestres) em um novo chat, após a entrega de software da etapa 3. O usuário autorizou publicação do código em `alexsandrors0312/jet_rapido`; dados reais ficam fora do Git.

## Começar pela evidência

1. Ler README, `GUIA_DESENVOLVIMENTO.md`, `ETAPA_3_GEOGRAFIA_MAPAS.md` e este arquivo.
2. Conferir `git status`, log e CI. Preservar alterações existentes do usuário.
3. Rodar migrações e testes com `.venv/Scripts/python.exe`.
4. Manter uma etapa principal em andamento e documentar cada incremento.

## O que existe

- Importação XLSX auditável e idempotente: importações, rotas, pacotes e pontos de entrega.
- Planilha recebida contém **32 pacotes, 26 paradas numeradas e 3 registros sem ordem**. Os 124 pacotes/66 paradas eram o exemplo inicial, não o tamanho desta amostra.
- Revisão geográfica: coordenadas originais preservadas, coordenadas efetivas, versão e histórico. O painel em `/` permite trabalhar sem escrever chamadas HTTP.
- Matrizes NxN dirigidas, inacessíveis explícitos, snapshot de entrada e indicador `stale`. Matrizes antigas sem snapshot são desatualizadas.
- OSRM com perfil pedestre preparado externamente; cache inclui `OSRM_DATASET_REVISION`, endpoint e raio de associação à rede. Trocar extrato requer trocar a revisão configurada e reiniciar API.
- Estimativa local marcada `estimate_only`; serve para demonstração, não para afirmar viabilidade na rede.
- CI inclui PostgreSQL e OSRM real sobre caminhos sintéticos conectados/desconectados.

## Pendências operacionais reais

- Preparar extrato da região e validar os acessos da Avenida dos Ourives usando `scripts/prepare_osrm.ps1` e `scripts/validate_walking.py`.
- Docker/WSL funcional não estava disponível localmente. O teste OSRM do CI não comprova a cobertura da amostra real.
- Flutter, Android SDK/ADB e aparelho de teste não estavam disponíveis. GPS/voz com tela bloqueada ainda não foram testados.
- API sem autenticação: manter em localhost até implementar autenticação/autorização antes de qualquer exposição pública.
- Não existem peso/volume dos pacotes, capacidade definida da bag, tempos de serviço, restrições de estacionamento ou janelas na planilha.

## Etapa 4 — próximo escopo

Criar macro-paradas com capacidade configurável em quantidade de pacotes e limites de caminhada. Usar matrizes de rede completas e atuais, recusar inacessíveis e conservar a cobertura exata dos pacotes. Uma rua textual é candidata, nunca uma obrigação de união; ruas longas e barreiras podem exigir divisão. DBSCAN sozinho não limita diâmetro.

Separar base de estacionamento, endereço e circuito de bag. Sem estacionamento validado não afirmar que um centroide é uma vaga possível. Permitir revisão humana. Comparar pacotes, distâncias e retornos com a ordem original antes de prometer ganhos.

## Etapa 5 — após validar etapa 4

Ordenar macro-paradas pela rede veicular e calcular circuitos pedestres fechados. O circuito começa e termina no veículo. Quando o motorista estacionar, usar o GPS confirmado, não o centro do cluster. A matriz otimiza custos; geometria e manobras exigem API de rotas separada antes de gerar instruções por voz.

## Prompt sugerido

> Continue o projeto Jet Rápido nesta pasta. Leia docs/CONTINUACAO_ETAPAS_4_5.md e o guia. Inicie a etapa 4 com testes de capacidade, cobertura de pacotes e viabilidade; depois avance para a etapa 5 mantendo as validações documentadas. A publicação do código no repositório está autorizada. Não publique dados reais e não trate as pendências de campo como concluídas.
