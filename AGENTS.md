# Steam Saves Sync

- Usar UTF-8. Script Python 3.10+ com biblioteca padrão; não instalar dependências sem necessidade.
- Preservar saves: backup antes de sobrescrever, simulação sem escrita, conflitos sem escolha automática, sem propagação de exclusões.
- Manter identificação estável por jogo e configuração de caminhos por sistema. Nunca versionar saves, backups, configurações pessoais ou estado de sincronização.
- Validar com `python -m unittest -v`. Não testar usando saves reais sem pedido específico.
- Ferramenta de script em repositório próprio. Distribuição na vitrine Clustter não solicitada.
