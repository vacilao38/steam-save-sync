# Validação — 09/11/2026

- Python 3.12.14 já disponível no runtime compartilhado; nenhuma dependência instalada.
- Windows: 21 testes passaram. Casos incluem ida/volta entre clientes, SHA-256 sem depender de horários, sobrescrita e backup completo, conflito por jogo e bloqueio prévio do lote, simulação sem escrita, pasta compartilhada ausente, exclusões preservadas, importação para pasta ausente, nomes/caminhos inválidos, links, trava e falha/mutação durante cópia.
- Interface de comandos `--help` verificada. Saves usados são fictícios e temporários.
- Preparada verificação automatizada em Windows e Ubuntu, com Python 3.10 e 3.12. Resultado remoto deve ser conferido após envio; preparação do fluxo não significa aprovação.
- Linux/partição dual boot reais e saves de jogos reais ainda não ensaiados nesta entrega. WSL não está instalado neste computador. Validação de shell pelo Git Bash impedida por restrição local de execução.
- Nesta sessão, testes locais usam pasta temporária dentro de `.local/tmp`, pois o diretório temporário padrão do ambiente restringiu acesso. Isso não exige alteração de comportamento do script no computador do usuário.
- Estado de sincronização, configuração pessoal e saves excluídos do repositório. Ferramenta entregue como script, sem instalação de aplicativo, publicação de downloads ou alteração de catálogo.
- Limites: backup e preparação por conjunto, substituição atômica por arquivo; restauração de backup manual em interrupção. Não converte formatos, não replica exclusões e não descobre caminhos automaticamente.
