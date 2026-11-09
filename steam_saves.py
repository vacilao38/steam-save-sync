#!/usr/bin/env python3
"""Sincronização de saves por diretório compartilhado; somente biblioteca padrão."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid
import unicodedata

VERSION = "1.1.0"
SYSTEM = "windows" if os.name == "nt" else "linux"
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.local.json")


class SaveError(Exception):
    pass


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".steam-save-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def no_links(path):
    """Recusa links, junctions e outros reparse points nos caminhos existentes."""
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise SaveError(f"Link/junction não permitido: {item}")


def full_path(value, relative_to):
    if not isinstance(value, str) or not value.strip():
        raise SaveError(f"Caminho de {SYSTEM} ainda não configurado.")
    expanded = os.path.expanduser(os.path.expandvars(value))
    if re.search(r"%[^%]+%|\$\{?\w+", expanded):
        raise SaveError(f"Variável de ambiente não resolvida: {value}")
    path = Path(expanded)
    if not path.is_absolute():
        path = relative_to / path
    path = Path(os.path.abspath(path))
    no_links(path)
    return path


def digest(path):
    no_links(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if sys.version_info >= (3, 11) else hash_stream(stream)


def hash_stream(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def portable_name(name):
    if (name in {".", ".."} or name.endswith((".", " "))
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name.split(".")[0], re.I)):
        raise SaveError(f"Nome incompatível com Windows/Linux: {name}")


def inventory(root, kind="folder"):
    no_links(root)
    if not root.exists():
        return {}
    if kind == "file":
        if not stat.S_ISREG(root.stat().st_mode):
            raise SaveError(f"Informe um arquivo de save: {root}")
        return {"save": digest(root)}
    if not root.is_dir():
        raise SaveError(f"Informe uma pasta de saves: {root}")
    result = {}
    def on_error(error):
        raise error
    for base, dirs, files in os.walk(root, followlinks=False, onerror=on_error):
        names = {}
        for name in dirs + files:
            portable_name(name)
            key = name.casefold()
            if key in names:
                raise SaveError(f"Nomes diferem apenas em maiúsculas/minúsculas: {base}/{name}")
            names[key] = name
            no_links(Path(base) / name)
        for name in files:
            path = Path(base) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise SaveError(f"Arquivo especial não permitido: {path}")
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def validate_pair(local, shared):
    # Evita colisões entre as duas árvores inclusive em Linux case-sensitive.
    all_paths = {}
    for key in set(local) | set(shared):
        parts = Path(key).parts
        for index in range(1, len(parts) + 1):
            name = "/".join(parts[:index])
            folded = name.casefold()
            if folded in all_paths and all_paths[folded] != name:
                raise SaveError(f"Colisão de maiúsculas/minúsculas: {name}")
            all_paths[folded] = name
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if parent in local or parent in shared:
                raise SaveError(f"Colisão entre arquivo e pasta: {parent}")


@contextmanager
def lock(vault):
    path = vault / ".sync-lock"
    try:
        path.mkdir()
    except FileExistsError:
        raise SaveError(f"Sincronização bloqueada. Se nenhuma execução estiver ativa, remova somente {path}") from None
    try:
        yield
    finally:
        path.rmdir()


def decide(local, shared, baseline, mode):
    if mode == "enviar":
        if not local:
            raise SaveError("Pasta local vazia; envio cancelado.")
        return "enviar" if local != shared else "igual"
    if mode == "receber":
        if not shared:
            raise SaveError("Não há save compartilhado para receber.")
        return "receber" if local != shared else "igual"
    if local == shared:
        return "igual"
    if baseline is None:
        if not shared:
            if not local:
                return "igual"
            return "enviar"
        if not local:
            return "receber"
        return "conflito"
    local_changed = local != baseline["local"]
    shared_changed = shared != baseline["shared"]
    if local_changed and shared_changed:
        return "conflito"
    if local_changed:
        if not local:
            raise SaveError("Saves locais desapareceram; exclusões não são propagadas. Use receber para restaurar.")
        return "enviar"
    if shared_changed:
        if not shared:
            raise SaveError("Saves compartilhados desapareceram; use enviar para restaurar.")
        return "receber"
    return "igual"


def atomic_copy(source, target, expected):
    no_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".steam-save-", dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, name)
        if digest(Path(name)) != expected:
            raise SaveError(f"Arquivo mudou durante a cópia: {source}")
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def content_path(root, name, kind):
    return root if kind == "file" else root / name


def transfer(source, target, source_before, target_before, vault, game, direction,
             source_kind="folder", target_kind="folder"):
    # Estagia e verifica todo o save antes de alterar o destino.
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=vault) as temporary:
        stage = Path(temporary)
        for name, checksum in source_before.items():
            atomic_copy(content_path(source, name, source_kind), stage / name, checksum)
        if inventory(source, source_kind) != source_before or inventory(target, target_kind) != target_before:
            raise SaveError("Saves alterados durante a preparação. Feche o jogo e seu launcher e tente novamente.")
        changed = {name: checksum for name, checksum in source_before.items()
                   if target_before.get(name) != checksum}
        if not changed:
            return
        if target_before:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            backup = vault / "backups" / game / stamp / direction
            for name, checksum in target_before.items():
                atomic_copy(content_path(target, name, target_kind), backup / name, checksum)
            print(f"  Backup do destino: {backup}")
        if inventory(target, target_kind) != target_before or inventory(source, source_kind) != source_before:
            raise SaveError("Saves alterados durante o backup; operação cancelada.")
        for name, checksum in changed.items():
            destination = content_path(target, name, target_kind)
            if (digest(destination) if destination.exists() else None) != target_before.get(name):
                raise SaveError(f"Destino mudou durante a cópia: {name}")
            atomic_copy(stage / name, destination, checksum)
        expected = dict(target_before, **source_before)
        if inventory(target, target_kind) != expected or inventory(source, source_kind) != source_before:
            raise SaveError("Save mudou durante a operação; estado não atualizado. Confira o backup antes de continuar.")


def valid_id(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", identifier):
        raise SaveError("Use ID com letras minúsculas sem acentos, números, hífen ou sublinhado.")
    portable_name(identifier)


def read_config(config_path):
    """Lê a versão anterior sem gravar durante listagem ou simulação."""
    config = read_json(config_path)
    if not isinstance(config, dict):
        raise SaveError("Configuração inválida ou versão não suportada.")
    if config.get("version") == 1 and isinstance(config.get("games"), dict):
        config["items"] = config.pop("games")
        config["version"] = 2
    if (config.get("version") != 2 or not isinstance(config.get("items"), dict)
            or not isinstance(config.get("shared"), dict)):
        raise SaveError("Configuração inválida ou versão não suportada.")
    for identifier, item in config["items"].items():
        valid_id(identifier)
        if not isinstance(item, dict) or item.get("kind", "folder") not in {"folder", "file"}:
            raise SaveError(f"Tipo de item inválido: {identifier}")
        for field in ("name", "platform"):
            if field in item and not isinstance(item[field], str):
                raise SaveError(f"Campo {field} inválido: {identifier}")
    return config


def select_ids(config, requested=None):
    items = config["items"]
    if isinstance(requested, str):
        requested = [requested]
    if requested:
        selected = list(dict.fromkeys(requested))
        for identifier in selected:
            if identifier not in items:
                raise SaveError(f"Item não cadastrado: {identifier}")
            if not items[identifier].get(SYSTEM):
                raise SaveError(f"Configure o caminho de {SYSTEM} para o item {identifier}.")
    else:
        selected = [identifier for identifier, item in items.items() if item.get(SYSTEM)]
    if not selected:
        raise SaveError(f"Nenhum item configurado em {SYSTEM}. Cadastre um item pelo menu ou com adicionar.")
    return selected


def load_config(config_path, state_dir, requested=None):
    config = read_config(config_path)
    selected = select_ids(config, requested)
    vault = full_path(config.get("shared", {}).get(SYSTEM), config_path.parent)
    no_links(vault / "vault.json")
    marker = read_json(vault / "vault.json")
    if marker.get("version") != 1 or not isinstance(marker.get("id"), str):
        raise SaveError("Diretório compartilhado inválido; execute configurar.")
    state_dir = full_path(str(state_dir), config_path.parent)
    if overlap(vault, state_dir) or overlap(vault, config_path):
        raise SaveError("Configuração e estado devem ficar fora da pasta SteamSavesSync.")
    roots = {}
    for game in selected:
        data = config["items"][game]
        root = full_path(data.get(SYSTEM), config_path.parent)
        if any(overlap(root, path) for path in [vault, state_dir, config_path, *roots.values()]):
            raise SaveError(f"Pastas sobrepostas na configuração de {game}.")
        roots[game] = root
    state_key = hashlib.sha256((marker["id"] + SYSTEM).encode("utf-8")).hexdigest()
    state_path = state_dir / (state_key + ".json")
    no_links(state_path)
    return config, vault, roots, state_path


def check_shared_kind(vault, identifier, kind, shared):
    marker_path = vault / "items" / (identifier + ".json")
    no_links(marker_path)
    if marker_path.exists():
        marker = read_json(marker_path)
        if not isinstance(marker, dict) or marker.get("kind") != kind:
            raise SaveError(f"Tipo diferente no compartilhado para {identifier}; use o mesmo tipo nos dois sistemas.")
    elif kind == "file" and shared:
        raise SaveError(f"O ID {identifier} já tem uma pasta de saves anterior. Use outro ID para o arquivo individual.")
    if kind == "file" and set(shared) - {"save"}:
        raise SaveError(f"Conteúdo compartilhado inesperado para o arquivo {identifier}.")
    return marker_path


def synchronize(config_path, state_dir, mode="sync", game=None, dry_run=False):
    config, vault, roots, state_path = load_config(config_path, state_dir, game)
    selected = list(roots)
    if not game:
        skipped = set(config["items"]) - set(selected)
        if skipped:
            print("Sem caminho neste sistema; ignorados: " + ", ".join(sorted(skipped)))
    def run():
        state = read_json(state_path) if state_path.exists() else {}
        plans = []
        for identifier in selected:
            item = config["items"][identifier]
            kind = item.get("kind", "folder")
            local_root = roots[identifier]
            if not local_root.exists() and mode != "receber":
                raise SaveError(f"Pasta local não encontrada: {local_root}. Confira o caminho ou use receber.")
            shared_root = vault / "games" / identifier
            local, shared = inventory(local_root, kind), inventory(shared_root)
            check_shared_kind(vault, identifier, kind, shared)
            validate_pair(local, shared)
            key = identifier + ":" + hashlib.sha256(str(local_root).encode("utf-8")).hexdigest()
            if kind == "file":
                key += ":file"
            direction = decide(local, shared, state.get(key), mode)
            print(f"{item.get('name', identifier)} [{identifier}]: {direction} "
                  f"({len(local)} arquivo(s) local / {len(shared)} compartilhado)")
            plans.append((identifier, key, local_root, shared_root, local, shared, kind, direction))
        if any(plan[-1] == "conflito" for plan in plans):
            raise SaveError("Conflito: ambos os lados têm saves diferentes. Nenhum item foi copiado. "
                            "Use enviar ITEM para preferir o local ou receber ITEM para preferir o compartilhado; haverá backup.")
        if dry_run:
            print("Simulação: nenhum arquivo foi alterado.")
            return
        for identifier, key, local_root, shared_root, local, shared, kind, direction in plans:
            if inventory(local_root, kind) != local or inventory(shared_root) != shared:
                raise SaveError("Arquivos mudaram desde a análise; operação cancelada.")
            marker_path = check_shared_kind(vault, identifier, kind, shared)
            if not marker_path.exists():
                write_json(marker_path, {"kind": kind})
            if direction == "enviar":
                transfer(local_root, shared_root, local, shared, vault, identifier, direction, source_kind=kind)
                shared = dict(shared, **local)
            elif direction == "receber":
                if not local_root.parent.is_dir():
                    raise SaveError(f"Pasta pai local ausente: {local_root.parent}. Confira a montagem/caminho.")
                transfer(shared_root, local_root, shared, local, vault, identifier, direction, target_kind=kind)
                local = dict(local, **shared)
            if inventory(local_root, kind) != local or inventory(shared_root) != shared:
                raise SaveError("Saves mudaram antes de registrar o estado; sincronize novamente com o jogo fechado.")
            state[key] = {"local": local, "shared": shared}
            write_json(state_path, state)
        print("Concluído. Arquivos exclusivos do destino foram preservados.")
    if dry_run:
        run()
    else:
        with lock(vault):
            run()


def configure(config_path, shared):
    base = full_path(shared, config_path.parent)
    if not base.is_dir():
        raise SaveError("Escolha um diretório compartilhado existente e montado.")
    vault = base / "SteamSavesSync"
    no_links(vault)
    no_links(vault / "vault.json")
    if overlap(vault, config_path):
        raise SaveError("O cadastro deve ficar fora da subpasta SteamSavesSync.")
    config = read_config(config_path) if config_path.exists() else {"version": 2, "shared": {}, "items": {}}
    if not (vault / "vault.json").exists():
        if vault.exists() and any(vault.iterdir()):
            raise SaveError("SteamSavesSync já contém arquivos sem identificação. Escolha outra pasta.")
        vault.mkdir(exist_ok=True)
        write_json(vault / "vault.json", {"version": 1, "id": str(uuid.uuid4())})
    config["shared"][SYSTEM] = str(vault)
    write_json(config_path, config)
    print(f"Pasta compartilhada de {SYSTEM}: {vault}")


def label(value, field):
    value = value.strip()
    if len(value) > 200 or any(ord(char) < 32 for char in value):
        raise SaveError(f"{field} inválido; use até 200 caracteres sem quebras de linha.")
    return value


def add_item(config_path, identifier, windows=None, linux=None, name=None, platform=None, kind=None,
             must_exist=False):
    valid_id(identifier)
    config = read_config(config_path)
    previous = config["items"].get(identifier)
    if must_exist and previous is None:
        raise SaveError(f"Item não cadastrado: {identifier}")
    entry = dict(previous or {})
    actual_kind = kind or entry.get("kind", "folder")
    if actual_kind not in {"folder", "file"}:
        raise SaveError("Escolha pasta ou arquivo como tipo do item.")
    if previous and actual_kind != entry.get("kind", "folder"):
        raise SaveError("Para mudar entre pasta e arquivo, cadastre outro ID; saves existentes serão preservados.")
    entry["kind"] = actual_kind
    if name is not None:
        entry["name"] = label(name, "Nome") or identifier
    else:
        entry.setdefault("name", identifier)
    if platform is not None:
        entry["platform"] = label(platform, "Plataforma")
    else:
        entry.setdefault("platform", "")
    for system, path in (("windows", windows), ("linux", linux)):
        if path is not None:
            if not isinstance(path, str) or not path.strip():
                raise SaveError("Informe um caminho para o item.")
            if system == SYSTEM:
                root = full_path(path, config_path.parent)
                if root.exists():
                    if actual_kind == "file" and not root.is_file():
                        raise SaveError("O item deve apontar para um arquivo.")
                    if actual_kind == "folder" and not root.is_dir():
                        raise SaveError("O item deve apontar para uma pasta.")
                elif not root.parent.is_dir():
                    raise SaveError("O caminho não existe e sua pasta pai também não; confira o destino.")
                # Guarda caminho absoluto; um nome relativo não deve mudar de alvo no outro computador.
                path = str(root)
            entry[system] = path.strip()
    if not any(entry.get(system) for system in ("windows", "linux")):
        raise SaveError("Informe --windows e/ou --linux.")
    config["items"][identifier] = entry
    write_json(config_path, config)
    print(f"Item salvo: {entry['name']} [{identifier}]")


def add_game(config_path, game, windows=None, linux=None):
    """Compatibilidade com integrações Python da versão anterior."""
    add_item(config_path, game, windows, linux)


def list_items(config_path):
    items = read_config(config_path)["items"]
    if not items:
        print("Nenhum item cadastrado.")
    for index, (identifier, item) in enumerate(items.items(), 1):
        platform = item.get("platform") or "Sem plataforma"
        kind = "Arquivo" if item.get("kind") == "file" else "Pasta"
        print(f"{index}. {item.get('name', identifier)} [{identifier}] — {platform} — {kind}")
        print(f"   Windows: {item.get('windows') or '(não configurado)'}")
        print(f"   Linux:   {item.get('linux') or '(não configurado)'}")
    return items


def parse_selection(value, identifiers):
    value = value.strip()
    if value == "0":
        return []
    if value in {"", "*"}:
        return list(identifiers)
    selected = []
    for token in re.split(r"[,;\s]+", value):
        if not token.isdigit() or not 1 <= int(token) <= len(identifiers):
            raise SaveError("Seleção inválida. Informe os números exibidos, separados por vírgula.")
        identifier = identifiers[int(token) - 1]
        if identifier not in selected:
            selected.append(identifier)
    return selected


def choose_items(config_path, available_only=False):
    items = list_items(config_path)
    if not items:
        return []
    value = input("Itens (ex.: 1,3; Enter = todos configurados; 0 = cancelar): ")
    if available_only and value.strip() in {"", "*"}:
        return select_ids({"items": items})
    return parse_selection(value, list(items))


def pick_path(kind, initial=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        raise SaveError("Seletor gráfico indisponível neste Python. Digite ou cole o caminho completo.") from None
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        options = {"parent": root, "title": "Selecione o save deste item"}
        if initial:
            candidate = Path(initial)
            options["initialdir"] = str(candidate if candidate.is_dir() else candidate.parent)
        if kind == "file":
            return filedialog.askopenfilename(**options)
        return filedialog.askdirectory(mustexist=True, **options)
    except tk.TclError:
        raise SaveError("Seletor gráfico indisponível. Digite ou cole o caminho completo.") from None
    finally:
        if root is not None:
            root.destroy()


def prompt_path(kind, current=None):
    prompt = "Arquivo" if kind == "file" else "Pasta"
    if current:
        print(f"Caminho atual de {SYSTEM}: {current}")
    value = input(f"{prompt} do save (? = procurar; Enter = manter): ").strip().strip('"')
    if value == "?":
        value = pick_path(kind, current)
    if not value:
        if current:
            return current
        raise SaveError("Cadastro cancelado: nenhum caminho foi escolhido.")
    return value


def suggest_id(name, items):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:65] or "item"
    try:
        portable_name(base)
    except SaveError:
        base = "item-" + base
    candidate, index = base, 2
    while candidate in items:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def edit_item_menu(config_path, edit=False):
    config = read_config(config_path)
    if edit:
        selected = choose_items(config_path)
        if not selected:
            return
        if len(selected) != 1:
            raise SaveError("Escolha somente um item para editar.")
        identifier = selected[0]
        item = config["items"][identifier]
        name = input(f"Nome [{item.get('name', identifier)}] (Enter = manter): ").strip() or item.get("name", identifier)
        platform = input(f"Plataforma [{item.get('platform') or 'Sem plataforma'}] (Enter = manter; - = limpar): ").strip()
        platform = "" if platform == "-" else platform or item.get("platform", "")
        kind = item.get("kind", "folder")
        path = prompt_path(kind, item.get(SYSTEM))
    else:
        name = input("Nome do item (jogo, perfil ou slot): ").strip()
        if not name:
            raise SaveError("Informe um nome para o item.")
        suggested = suggest_id(name, config["items"])
        identifier = input(f"ID estável [{suggested}] (use o mesmo nos dois sistemas): ").strip() or suggested
        if identifier in config["items"]:
            raise SaveError("Esse ID já existe. Use a opção Editar para configurar seu caminho neste sistema.")
        platform = input("Plataforma/launcher (opcional; Enter = sem plataforma): ").strip()
        option = input("Tipo: 1 pasta inteira; 2 arquivo individual [1]: ").strip() or "1"
        if option not in {"1", "2"}:
            raise SaveError("Tipo inválido; escolha 1 ou 2.")
        kind = "file" if option == "2" else "folder"
        path = prompt_path(kind)
    add_item(config_path, identifier, name=name, platform=platform, kind=kind, **{SYSTEM: path})


def menu(config_path, state_dir):
    print("Saves Sync — Windows / Linux\nQualquer jogo ou plataforma. Feche o jogo e seu launcher antes de copiar.")
    while True:
        print("\n1 Configurar pasta compartilhada\n2 Cadastrar item de save\n3 Simular sincronização"
              "\n4 Sincronizar\n5 Enviar save local (sobrescrever compartilhado)"
              "\n6 Receber save (sobrescrever local)\n7 Listar itens e caminhos"
              "\n8 Editar nome, plataforma ou caminho de um item\n0 Sair")
        option = input("Escolha: ").strip()
        try:
            if option == "0":
                return
            if option == "1":
                configure(config_path, prompt_path("folder"))
            elif option == "2":
                edit_item_menu(config_path)
            elif option in {"3", "4", "5", "6"}:
                selected = choose_items(config_path, available_only=True)
                if not selected:
                    continue
                mode = {"5": "enviar", "6": "receber"}.get(option, "sync")
                synchronize(config_path, state_dir, mode, selected, option == "3")
            elif option == "7":
                list_items(config_path)
            elif option == "8":
                edit_item_menu(config_path, edit=True)
        except (SaveError, OSError, ValueError, KeyError, TypeError) as error:
            print(f"Erro: {error}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".steam-save-sync")
    commands = parser.add_subparsers(dest="command")
    setup = commands.add_parser("configurar", help="Configurar o diretório compartilhado neste sistema")
    setup.add_argument("shared", help="Diretório existente; será criada a subpasta SteamSavesSync")
    for command in ("adicionar", "editar"):
        add = commands.add_parser(command, help="Cadastrar/alterar um item de qualquer jogo ou plataforma")
        add.add_argument("item")
        add.add_argument("--windows")
        add.add_argument("--linux")
        add.add_argument("--nome")
        add.add_argument("--plataforma", help="Rótulo opcional; não exige conta ou launcher")
        add.add_argument("--tipo", choices=["pasta", "arquivo"])
    commands.add_parser("listar", help="Listar os itens e seus caminhos em cada sistema")
    for command in ("sync", "enviar", "receber"):
        sub = commands.add_parser(command)
        sub.add_argument("items", nargs="*", help="IDs dos itens; vazio = todos configurados neste sistema")
        sub.add_argument("--simular", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = full_path(str(args.config), Path.cwd())
        if args.command == "configurar":
            configure(config_path, args.shared)
        elif args.command in {"adicionar", "editar"}:
            kind = {"pasta": "folder", "arquivo": "file"}.get(args.tipo)
            add_item(config_path, args.item, args.windows, args.linux, args.nome, args.plataforma,
                     kind, must_exist=args.command == "editar")
        elif args.command == "listar":
            list_items(config_path)
        elif args.command:
            synchronize(config_path, args.state_dir, args.command, args.items, args.simular)
        else:
            menu(config_path, args.state_dir)
        return 0
    except (SaveError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nOperação interrompida. Confira backups se a cópia já havia começado.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
