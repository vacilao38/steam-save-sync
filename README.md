# Steam Saves Sync

Script Python para copiar saves nos dois sentidos entre **Windows e Linux**, usando um **diretório compartilhado**. Não exige pacotes externos. Python **3.10 ou superior** nos dois sistemas.

## Começar pelo menu

Coloque esta pasta de scripts no diretório compartilhado, fora da subpasta `SteamSavesSync` que a ferramenta vai criar. Assim, os dois sistemas podem usar o mesmo script e o mesmo cadastro.

1. Feche o jogo **e a Steam** antes de sincronizar.
2. No Windows, abra `iniciar.cmd`. No Linux, execute `sh iniciar.sh` pelo terminal.
3. Opção **1**: indique o diretório compartilhado existente. Faça isso uma vez em cada sistema: a mesma partição terá caminhos diferentes, por exemplo `D:\Compartilhado` e `/mnt/compartilhado`.
4. Opção **2**: cadastre cada jogo com um ID estável (pode usar o AppID da Steam) e a **pasta que contém seus saves**. Repita no outro sistema com o **mesmo ID** e o caminho local correspondente. O cadastro guarda os dois caminhos.
5. Opção **3**: simule. Opção **4**: sincronize. Depois de jogar em um sistema, sincronize; antes de jogar no outro, sincronize novamente.

Se usar cópias separadas do script, configure cada cópia apontando para o mesmo diretório compartilhado e cadastre os mesmos IDs.

## Comandos diretos

Execute na pasta do script. Troque os caminhos fictícios pelos caminhos reais.

Windows:

```powershell
py -3 steam_saves.py configurar "D:\Compartilhado"
py -3 steam_saves.py adicionar 123 --windows "C:\Users\SEU_USUARIO\Documents\MeuJogo\Saves"
py -3 steam_saves.py sync --simular
py -3 steam_saves.py sync
```

Linux, usando o mesmo cadastro na partição compartilhada:

```sh
python3 steam_saves.py configurar /mnt/compartilhado
python3 steam_saves.py adicionar 123 --linux "$HOME/.local/share/MeuJogo/Saves"
python3 steam_saves.py sync --simular
python3 steam_saves.py sync
```

Sincronizar um jogo: `python3 steam_saves.py sync 123`. No Windows use `py -3` em vez de `python3`.

Na primeira execução, se ambos os lados já tiverem saves diferentes, escolha qual preservar como principal:

```sh
python3 steam_saves.py enviar 123    # local -> compartilhado
python3 steam_saves.py receber 123   # compartilhado -> local
```

Ambos criam **backup completo dos arquivos do destino** antes de sobrescrever. Acrescente `--simular` para conferir sem copiar. Se a pasta local ainda não existir, `receber` pode criá-la quando a pasta pai já existir.

## Como decide o sentido

A ferramenta compara hashes SHA-256 com a última sincronização deste sistema, sem depender do relógio. Alteração apenas local: envia. Alteração apenas compartilhada: recebe. Alterações nos dois lados: interrompe e informa conflito. O conflito é verificado no conjunto do save de cada jogo, para evitar misturar automaticamente arquivos de sessões distintas. Um conflito impede a execução do lote inteiro; resolva-o por ID.

Arquivos exclusivos do destino são preservados: **exclusões não são propagadas**. É uma cópia com atualização/sobrescrita, não um espelho exato. Saves de vários arquivos recebem backup e preparação completos, mas a substituição é atômica **por arquivo**, não por pasta. Uma queda durante a gravação pode deixar o destino parcialmente atualizado: restaure o backup completo antes de continuar.

## Onde ficam os arquivos

```text
Diretório compartilhado/
  SteamSavesSync/
    vault.json                  identificação da área compartilhada
    games/<ID>/                 saves compartilhados
    backups/<ID>/<DATA-ID>/      cópias anteriores do destino
```

`config.local.json` fica junto do script. O histórico de hashes fica no usuário de cada sistema, em `~/.steam-save-sync`; não compartilhe essa pasta de estado. Opções globais `--config CAMINHO` e `--state-dir PASTA` permitem mudar esses locais e devem vir antes do comando. Configuração e estado precisam ficar fora de `SteamSavesSync` e das pastas dos saves.

Backups não são apagados automaticamente. Para restaurar: feche jogo/Steam, localize a pasta do backup desejado e copie seu conteúdo para a pasta local do jogo. Guarde antes uma cópia da pasta atual; se precisar restaurar exatamente o conjunto antigo, separe os arquivos atuais em outra pasta antes da restauração. Confira no jogo antes de sincronizar outra vez.

Se a execução for encerrada à força, pode restar `SteamSavesSync/.sync-lock`. Só remova **essa pasta vazia** após confirmar que nenhuma outra execução está ativa. A trava protege execuções que acessam o mesmo sistema de arquivos; esta versão é destinada à partição/diretório compartilhado, não à coordenação entre cópias independentes de nuvem.

## Encontrar os saves

Cada jogo define sua própria pasta. Não aponte para toda a biblioteca Steam, todo o `userdata`, `AppData` ou todo o prefixo Proton: cadastre somente a pasta de saves do jogo, por perfil/conta quando necessário. Se um jogo salvar em vários locais independentes, cadastre cada pasta com ID próprio.

No Windows, saves podem estar em Documentos, Saved Games, AppData ou `Steam/userdata`. No Linux, jogos nativos e jogos via Proton podem usar locais diferentes; bibliotecas adicionais, instalações Flatpak e prefixos Proton precisam de caminhos próprios. Consulte a documentação do jogo para confirmar tanto o caminho quanto a compatibilidade do formato entre Windows e Linux. **O script copia arquivos; não converte formatos de save.**

A Valve documenta a diversidade de locais e a configuração específica para saves entre plataformas em [Steam Cloud / Steamworks](https://partner.steamgames.com/doc/features/cloud) e [suporte Steam Cloud](https://help.steampowered.com/en/faqs/view/68d2-35ab-09a9-7678). A Steam sincroniza a nuvem antes/depois de sessões; se o jogo também usa Steam Cloud, coordene esse recurso para que ele não restaure uma cópia anterior após a cópia manual. Em caso de dúvida, desative o Cloud **desse jogo** durante o teste de migração, preservando backups.

O script recusa links simbólicos, junctions, caminhos sobrepostos e nomes incompatíveis entre Windows e Linux. Mantenha a partição montada e gravável. Não execute enquanto o jogo ou a Steam estiverem usando os saves. A detecção de mudanças reduz riscos, mas não substitui fechar esses programas.

## Validar

```sh
python3 -m unittest -v
```

Os testes usam pastas temporárias e saves fictícios. Nunca leem os saves reais. Consulte `VALIDACAO.md` para o resultado e os limites desta entrega.
