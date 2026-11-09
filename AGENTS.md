# Steam Saves Sync

- Usar UTF-8. Script Python 3.10+ com biblioteca padrão; não instalar dependências sem necessidade.
- Preservar saves: backup antes de sobrescrever, simulação sem escrita, conflitos sem escolha automática, sem propagação de exclusões.
- Manter identificação estável por item e configuração de caminhos por sistema. Aceitar jogos de qualquer plataforma ou sem launcher, com plataforma opcional e itens de pasta ou arquivo individual. Nunca versionar saves, backups, configurações pessoais ou estado de sincronização.
- Preservar os IDs, backups, saves e estado de cadastros antigos. Leituras e simulações não devem migrar/gravar configuração. Alteração do tipo de um ID existente deve exigir outro ID.
- Validar com `python -m unittest -v`. Não testar usando saves reais sem pedido específico.
- Ferramenta de script em repositório próprio. Distribuição na vitrine Clustter não solicitada.
