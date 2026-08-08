#!/usr/bin/env bash
# Preflight shared by the scripts the evaluator runs.
#
# Every command here shells out to Docker. Without this check the first `docker`
# call fails with the shell's own "command not found", or with a permission error
# from the socket, neither of which names a package the evaluator can install --
# and the package name is not "docker" on every distribution.

_pkg_mgr() {
    local m
    for m in apt-get dnf pacman zypper; do
        if command -v "$m" >/dev/null 2>&1; then printf '%s\n' "$m"; return 0; fi
    done
    printf 'unknown\n'
}

require_docker() {
    command -v docker >/dev/null 2>&1 || {
        {
            echo "need: docker"
            case "$(_pkg_mgr)" in
                apt-get) echo "  sudo apt-get update && sudo apt-get install -y docker.io" ;;
                dnf)     echo "  sudo dnf install -y docker" ;;
                pacman)  echo "  sudo pacman -Sy --needed docker" ;;
                zypper)  echo "  sudo zypper install -y docker" ;;
                *)       echo "  install Docker Engine for your distribution" ;;
            esac
            echo "  upstream instructions: https://docs.docker.com/engine/install/"
            echo "  then allow this user to use it without sudo:"
            echo "    sudo usermod -aG docker \"\$USER\" && newgrp docker"
        } >&2
        exit 1
    }
    docker info >/dev/null 2>&1 || {
        {
            echo "need: a running docker daemon reachable by this user"
            echo "  start it:  sudo systemctl start docker"
            echo "  and allow this user without sudo:"
            echo "    sudo usermod -aG docker \"\$USER\" && newgrp docker"
        } >&2
        exit 1
    }
}
