# Validação — 09/11/2026

## Versão 1.1.0 — itens de qualquer jogo/plataforma

- Nome livre, plataforma opcional, tipos pasta/arquivo, caminho individual Windows/Linux e edição de itens.
- Seleção de vários itens no menu e na linha de comando; itens não selecionados não são acessados. Itens sem caminho neste sistema são ignorados no comando sem IDs e na seleção padrão do menu.
- Seletor nativo opcional via Tkinter, com alternativa por caminho digitado. Testes do fluxo do menu/seletor usam entradas simuladas; o diálogo gráfico real não foi ensaiado nesta sessão.
- 44 testes locais aprovados no Windows com Python 3.12.14: regressões da versão anterior, arquivos individuais com nomes distintos nos sistemas, backup e conflitos de arquivo, preservação dos vizinhos, plataforma vazia, seleção múltipla/cancelamento, edição dos caminhos sem alterar o outro sistema, tipo divergente entre clientes e leitura/migração do cadastro anterior sem gravação em simulação.
- Verificação remota Windows/Ubuntu com Python 3.10/3.12: consultar resultado da execução referente ao commit 1.1.0; não reutilizar como evidência o fluxo da versão 1.0 abaixo.
- Nenhum save real acessado; ensaio em dual boot real e compatibilidade dos formatos dos jogos continuam pendentes.

## Versão 1.0.0 — entrega inicial

- Python 3.12.14 já disponível no runtime compartilhado; nenhuma dependência instalada.
- Windows: 21 testes passaram. Casos incluem ida/volta entre clientes, SHA-256 sem depender de horários, sobrescrita e backup completo, conflito por jogo e bloqueio prévio do lote, simulação sem escrita, pasta compartilhada ausente, exclusões preservadas, importação para pasta ausente, nomes/caminhos inválidos, links, trava e falha/mutação durante cópia.
- Interface de comandos `--help` verificada. Saves usados são fictícios e temporários.
- Verificação automatizada [42645728269](https://github.com/vacilao38/steam-save-sync/actions/runs/42645728269): os quatro ambientes Windows/Ubuntu com Python 3.10/3.12 concluíram com sucesso, incluindo a suíte de 21 testes e a interface `--help`.
- Linux/partição dual boot reais e saves de jogos reais ainda não ensaiados nesta entrega. WSL não está instalado neste computador. Validação de shell pelo Git Bash impedida por restrição local de execução.
- Nesta sessão, testes locais usam pasta temporária dentro de `.local/tmp`, pois o diretório temporário padrão do ambiente restringiu acesso. Isso não exige alteração de comportamento do script no computador do usuário.
- Estado de sincronização, configuração pessoal e saves excluídos do repositório. Ferramenta entregue como script, sem instalação de aplicativo, publicação de downloads ou alteração de catálogo.
- Limites: backup e preparação por conjunto, substituição atômica por arquivo; restauração de backup manual em interrupção. Não converte formatos, não replica exclusões e não descobre caminhos automaticamente.
