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

VERSION = "1.0.0"
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


def inventory(root):
    no_links(root)
    if not root.exists():
        return {}
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


def transfer(source, target, source_before, target_before, vault, game, direction):
    # Estagia e verifica todo o save antes de alterar o destino.
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=vault) as temporary:
        stage = Path(temporary)
        for name, checksum in source_before.items():
            atomic_copy(source / name, stage / name, checksum)
        if inventory(source) != source_before or inventory(target) != target_before:
            raise SaveError("Saves alterados durante a preparação. Feche o jogo e a Steam e tente novamente.")
        changed = {name: checksum for name, checksum in source_before.items()
                   if target_before.get(name) != checksum}
        if not changed:
            return
        if target_before:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            backup = vault / "backups" / game / stamp / direction
            for name, checksum in target_before.items():
                atomic_copy(target / name, backup / name, checksum)
            print(f"  Backup do destino: {backup}")
        if inventory(target) != target_before or inventory(source) != source_before:
            raise SaveError("Saves alterados durante o backup; operação cancelada.")
        for name, checksum in changed.items():
            if (digest(target / name) if (target / name).exists() else None) != target_before.get(name):
                raise SaveError(f"Destino mudou durante a cópia: {name}")
            atomic_copy(stage / name, target / name, checksum)
        expected = dict(target_before, **source_before)
        if inventory(target) != expected or inventory(source) != source_before:
            raise SaveError("Save mudou durante a operação; estado não atualizado. Confira o backup antes de continuar.")


def load_config(config_path, state_dir):
    config = read_json(config_path)
    if config.get("version") != 1 or not isinstance(config.get("games"), dict):
        raise SaveError("Configuração inválida ou versão não suportada.")
    vault = full_path(config.get("shared", {}).get(SYSTEM), config_path.parent)
    no_links(vault / "vault.json")
    marker = read_json(vault / "vault.json")
    if marker.get("version") != 1 or not isinstance(marker.get("id"), str):
        raise SaveError("Diretório compartilhado inválido; execute configurar.")
    state_dir = full_path(str(state_dir), config_path.parent)
    if overlap(vault, state_dir) or overlap(vault, config_path):
        raise SaveError("Configuração e estado devem ficar fora da pasta SteamSavesSync.")
    roots = {}
    for game, data in config["games"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", game):
            raise SaveError(f"Identificador de jogo inválido: {game}")
        portable_name(game)
        root = full_path(data.get(SYSTEM), config_path.parent)
        if any(overlap(root, path) for path in [vault, state_dir, config_path, *roots.values()]):
            raise SaveError(f"Pastas sobrepostas na configuração de {game}.")
        roots[game] = root
    state_key = hashlib.sha256((marker["id"] + SYSTEM).encode("utf-8")).hexdigest()
    state_path = state_dir / (state_key + ".json")
    no_links(state_path)
    return config, vault, roots, state_path


def synchronize(config_path, state_dir, mode="sync", game=None, dry_run=False):
    config, vault, roots, state_path = load_config(config_path, state_dir)
    if game and game not in roots:
        raise SaveError(f"Jogo não cadastrado: {game}")
    selected = [game] if game else list(roots)
    if not selected:
        raise SaveError("Cadastre ao menos um jogo com adicionar ou pelo menu.")
    def run():
        state = read_json(state_path) if state_path.exists() else {}
        plans = []
        for identifier in selected:
            local_root = roots[identifier]
            if not local_root.is_dir() and mode != "receber":
                raise SaveError(f"Pasta local não encontrada: {local_root}. Confira o caminho ou use receber.")
            shared_root = vault / "games" / identifier
            local, shared = inventory(local_root), inventory(shared_root)
            validate_pair(local, shared)
            key = identifier + ":" + hashlib.sha256(str(local_root).encode("utf-8")).hexdigest()
            direction = decide(local, shared, state.get(key), mode)
            print(f"{identifier}: {direction} ({len(local)} arquivo(s) local / {len(shared)} compartilhado)")
            plans.append((identifier, key, local_root, shared_root, local, shared, direction))
        if any(plan[-1] == "conflito" for plan in plans):
            raise SaveError("Conflito: ambos os lados têm saves diferentes. Nenhum jogo foi copiado. "
                            "Use enviar JOGO para preferir o local ou receber JOGO para preferir o compartilhado; haverá backup.")
        if dry_run:
            print("Simulação: nenhum arquivo foi alterado.")
            return
        for identifier, key, local_root, shared_root, local, shared, direction in plans:
            if inventory(local_root) != local or inventory(shared_root) != shared:
                raise SaveError("Arquivos mudaram desde a análise; operação cancelada.")
            if direction == "enviar":
                transfer(local_root, shared_root, local, shared, vault, identifier, direction)
                shared = dict(shared, **local)
            elif direction == "receber":
                if not local_root.parent.is_dir():
                    raise SaveError(f"Pasta pai local ausente: {local_root.parent}. Confira a montagem/caminho.")
                transfer(shared_root, local_root, shared, local, vault, identifier, direction)
                local = dict(local, **shared)
            if inventory(local_root) != local or inventory(shared_root) != shared:
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
    config = read_json(config_path) if config_path.exists() else {"version": 1, "shared": {}, "games": {}}
    if not (vault / "vault.json").exists():
        if vault.exists() and any(vault.iterdir()):
            raise SaveError("SteamSavesSync já contém arquivos sem identificação. Escolha outra pasta.")
        vault.mkdir(exist_ok=True)
        write_json(vault / "vault.json", {"version": 1, "id": str(uuid.uuid4())})
    config["shared"][SYSTEM] = str(vault)
    write_json(config_path, config)
    print(f"Pasta compartilhada de {SYSTEM}: {vault}")


def add_game(config_path, game, windows=None, linux=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", game):
        raise SaveError("Use ID de jogo com letras minúsculas sem acentos, números, hífen ou sublinhado.")
    portable_name(game)
    config = read_json(config_path)
    entry = dict(config["games"].get(game, {}))
    for system, path in (("windows", windows), ("linux", linux)):
        if path:
            if system == SYSTEM and not full_path(path, config_path.parent).is_dir():
                raise SaveError("A pasta de saves deste sistema não existe.")
            entry[system] = path
    if not entry:
        raise SaveError("Informe --windows e/ou --linux.")
    config["games"][game] = entry
    write_json(config_path, config)
    print(f"Jogo cadastrado: {game}")


def menu(config_path, state_dir):
    print("Steam Saves Sync — Windows / Linux\nFeche o jogo e a Steam antes de copiar saves.")
    while True:
        print("\n1 Configurar pasta compartilhada\n2 Cadastrar jogo neste sistema\n3 Simular sincronização"
              "\n4 Sincronizar\n5 Enviar save local (sobrescrever compartilhado)"
              "\n6 Receber save (sobrescrever local)\n0 Sair")
        option = input("Escolha: ").strip()
        try:
            if option == "0":
                return
            if option == "1":
                configure(config_path, input("Diretório compartilhado existente: ").strip().strip('"'))
            elif option == "2":
                game = input("ID do jogo (igual nos dois sistemas; pode ser o AppID Steam): ").strip()
                path = input("Pasta local dos saves: ").strip().strip('"')
                add_game(config_path, game, **{SYSTEM: path})
            elif option in {"3", "4", "5", "6"}:
                game = input("ID do jogo (vazio = todos): ").strip() or None
                mode = {"5": "enviar", "6": "receber"}.get(option, "sync")
                synchronize(config_path, state_dir, mode, game, option == "3")
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
    add = commands.add_parser("adicionar", help="Cadastrar os caminhos reais de um jogo")
    add.add_argument("game")
    add.add_argument("--windows")
    add.add_argument("--linux")
    for command in ("sync", "enviar", "receber"):
        sub = commands.add_parser(command)
        sub.add_argument("game", nargs="?")
        sub.add_argument("--simular", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = full_path(str(args.config), Path.cwd())
        if args.command == "configurar":
            configure(config_path, args.shared)
        elif args.command == "adicionar":
            add_game(config_path, args.game, args.windows, args.linux)
        elif args.command:
            synchronize(config_path, args.state_dir, args.command, args.game, args.simular)
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
