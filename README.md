# Saves Sync — Windows / Linux

Script Python para copiar e sobrescrever saves nos dois sentidos por um **diretório compartilhado**. Funciona com **qualquer jogo**, de qualquer loja/plataforma, emuladores ou jogos sem launcher. Não acessa contas nem depende da Steam.

Cada **item** tem nome livre, plataforma opcional e caminho próprio em cada sistema. Um item pode ser uma **pasta inteira** ou **um arquivo individual**. Você pode cadastrar vários perfis/slots do mesmo jogo e escolher quais itens sincronizar. Requer **Python 3.10+**, sem pacotes obrigatórios adicionais.

O nome do repositório, o arquivo `steam_saves.py` e a pasta `SteamSavesSync` são mantidos para preservar os atalhos e saves da primeira versão.

## Usar pelo menu

Extraia a pasta dos scripts no diretório compartilhado, fora da subpasta `SteamSavesSync` criada pela ferramenta. Assim, Windows e Linux podem usar o mesmo cadastro.

1. Feche o jogo e seu launcher antes de copiar saves.
2. Windows: abra `iniciar.cmd`. Linux: execute `sh iniciar.sh` em um terminal.
3. Opção **1 — Configurar pasta compartilhada**: faça isso uma vez em cada sistema. A mesma partição terá caminhos diferentes, por exemplo `D:\Compartilhado` e `/mnt/compartilhado`.
4. Opção **2 — Cadastrar item**: informe nome, ID estável, plataforma opcional e tipo (pasta ou arquivo). Informe o caminho deste sistema. Digite **`?`** para procurar no seletor gráfico ou cole/digite o caminho completo.
5. No outro sistema, use **8 — Editar item**, selecione o mesmo item e configure o caminho correspondente. O cadastro guarda os dois caminhos separadamente.
6. **7 — Listar itens e caminhos** mostra nomes, plataformas, tipos e caminhos Windows/Linux.
7. **3 — Simular** ou **4 — Sincronizar** exibe os itens para seleção: digite, por exemplo, **`1,3`**. Enter seleciona todos configurados neste sistema; **`0` cancela**. As opções **5 — Enviar** e **6 — Receber** também aceitam seleção de vários itens.

Depois de jogar, sincronize. Antes de jogar no outro sistema, sincronize novamente. Na primeira vez, se os dois lados já tiverem saves diferentes, escolha explicitamente enviar ou receber o item desejado. Há backup antes da sobrescrita.

O seletor gráfico usa o Tkinter do Python e precisa de uma sessão gráfica. Se não estiver disponível, digite ou cole o caminho; não é preciso instalar pacotes para usar o script pelo terminal. O seletor procura caminhos existentes. Para um destino que ainda não existe, digite seu caminho completo; a pasta pai deve existir e a primeira operação deverá ser **Receber**.

Se usar cópias separadas do script, configure ambas para o mesmo diretório compartilhado e use os mesmos **IDs e tipos** para os itens correspondentes.

## Exemplos de itens

| ID | Nome | Plataforma opcional | Tipo | Caminho de cada sistema |
| --- | --- | --- | --- | --- |
| aventura | Minha aventura | GOG | Pasta | Pasta de saves Windows e pasta Linux |
| corrida-slot1 | Corrida — slot 1 | Epic Games | Arquivo | Arquivo específico em cada sistema |
| emulador-perfil | Perfil do emulador | Emulador | Pasta | Pasta do perfil em cada sistema |
| jogo-livre | Meu jogo independente | Sem plataforma | Arquivo | Arquivo de save em cada sistema |

A plataforma é apenas um rótulo livre, sem restrição de lojas. Os nomes dos arquivos individuais **podem ser diferentes** entre Windows e Linux. O ID identifica o conteúdo correspondente. Renomear o item ou editar seu caminho não muda esse ID nem apaga os saves anteriores. Se o novo caminho já contiver um save diferente, a primeira sincronização por esse caminho exigirá escolher qual lado prevalece.

Evite cadastrar simultaneamente uma pasta inteira e arquivos que ficam dentro dela na mesma seleção: caminhos sobrepostos são recusados. Para mudar um item entre pasta e arquivo, crie outro ID.

## Comandos diretos

No Windows use `py -3`; no Linux, `python3`. Execute na pasta do script e troque os caminhos fictícios pelos reais.

```powershell
py -3 steam_saves.py configurar "D:\Compartilhado"
py -3 steam_saves.py adicionar aventura --nome "Minha aventura" --plataforma GOG --tipo pasta --windows "C:\Jogos\Aventura\Saves"
py -3 steam_saves.py adicionar jogo-livre --nome "Meu jogo independente" --tipo arquivo --windows "C:\Jogos\Independente\slot1.sav"
py -3 steam_saves.py listar
py -3 steam_saves.py sync aventura jogo-livre --simular
py -3 steam_saves.py sync aventura jogo-livre
```

No Linux, usando o mesmo cadastro:

```sh
python3 steam_saves.py configurar /mnt/compartilhado
python3 steam_saves.py editar aventura --linux "$HOME/Jogos/Aventura/Saves"
python3 steam_saves.py editar jogo-livre --linux "$HOME/Jogos/Independente/progresso.dat"
python3 steam_saves.py sync aventura jogo-livre --simular
python3 steam_saves.py sync aventura jogo-livre
```

Também é possível informar `--windows` e `--linux` juntos no cadastro/edição. `--nome` altera o nome exibido; `--plataforma ""` limpa a plataforma. Campos omitidos são preservados.

```sh
python3 steam_saves.py editar aventura --nome "Aventura — perfil principal"
python3 steam_saves.py enviar aventura       # local -> compartilhado, com backup do destino
python3 steam_saves.py receber jogo-livre    # compartilhado -> local, com backup do destino
python3 steam_saves.py sync                 # todos configurados neste sistema
```

Acrescente `--simular` a `sync`, `enviar` ou `receber` para conferir sem alterar arquivos. Itens sem caminho neste sistema são ignorados no comando sem IDs; se forem selecionados explicitamente, o script pede para configurar o caminho.

## Cadastros anteriores

O cadastro da versão 1.0 continua legível, com IDs, dados compartilhados e estado preservados; os jogos existentes são tratados como itens de pasta. O cadastro é atualizado para a versão 2 **quando você o edita ou configura**, sem mover saves. Listar ou simular não grava/migra o cadastro. Atualize o script nos dois sistemas antes de editar o cadastro, pois a versão antiga não lê o formato novo.

## Sincronização e backups

O script compara hashes SHA-256 com a última sincronização deste sistema, sem depender do relógio. Alteração apenas local: envia. Apenas compartilhada: recebe. Alterações nos dois lados: interrompe o lote e informa conflito. O conflito é verificado no conjunto de cada item para evitar misturar automaticamente arquivos de sessões distintas. Resolva o conflito enviando ou recebendo o ID desejado.

Arquivos exclusivos do destino são preservados: **exclusões não são propagadas**. É cópia com atualização/sobrescrita, não espelho exato. Backup e preparação cobrem o item inteiro, mas a substituição é atômica **por arquivo**. Uma interrupção pode deixar uma pasta parcialmente atualizada; restaure o backup completo antes de continuar.

```text
Diretório compartilhado/
  SteamSavesSync/
    vault.json                  identificação da área compartilhada
    games/<ID>/                 conteúdo compartilhado (nome legado)
    items/<ID>.json             tipo do item para conferência entre sistemas
    backups/<ID>/<DATA-ID>/      cópias anteriores do destino
```

Para itens de **arquivo individual**, o conteúdo compartilhado e os backups usam o nome interno **`save`**, independentemente do nome local. Ao receber, o script grava no arquivo exato escolhido para aquele sistema, sem copiar os arquivos vizinhos.

`config.local.json` fica junto do script. O histórico de hashes fica no usuário de cada sistema, em `~/.steam-save-sync`; não compartilhe essa pasta de estado. As opções globais `--config CAMINHO` e `--state-dir PASTA` mudam esses locais e devem vir antes do comando. Cadastro e estado precisam ficar fora de `SteamSavesSync` e dos saves.

Backups não são apagados automaticamente. Para restaurar manualmente: feche jogo/launcher, guarde uma cópia do save atual e copie o backup desejado para o caminho local. Para arquivo individual, copie o arquivo interno `save` para o **nome e caminho locais** do item. Para pasta, restaure o conjunto completo; se necessário, separe os arquivos atuais antes. Confira o save no jogo antes de sincronizar novamente.

Após encerramento forçado, pode restar `SteamSavesSync/.sync-lock`. Remova **somente essa pasta vazia** depois de confirmar que não há outra sincronização ativa. Esta ferramenta usa uma partição/diretório compartilhado, não coordena cópias independentes de nuvem.

## Limites

Escolha os arquivos/pastas de saves do jogo ou perfil, em vez de toda a biblioteca, AppData ou prefixo de compatibilidade. Confirme se o formato é compatível entre os sistemas: **o script copia, não converte saves**. Se o jogo usa sincronização própria de nuvem, coordene-a para evitar que ela restaure uma versão anterior após a cópia manual.

Links simbólicos, junctions, caminhos sobrepostos e nomes de pastas incompatíveis entre Windows e Linux são recusados. Mantenha a partição montada e gravável, com jogo/launcher fechados.

## Validar

```sh
python3 -m unittest -v
```

Os testes usam pastas temporárias e saves fictícios. Não acessam saves reais. Consulte `VALIDACAO.md` para os resultados e os limites da entrega.
