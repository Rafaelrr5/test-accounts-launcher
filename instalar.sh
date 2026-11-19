#!/usr/bin/env bash
# Instalação do zero no macOS e no Linux: ambiente Python, biblioteca, configuração das contas e atalhos.
# Uso: abra o Terminal na pasta e rode:  bash instalar.sh
main() {
  set -e
  cd "$(dirname "$0")"

  PY=""
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.9 ou mais novo não encontrado."
    echo "  macOS: instale em https://www.python.org/downloads/ (ou aceite as ferramentas de desenvolvedor que o macOS oferecer)."
    echo "  Linux: instale pelo gerenciador de pacotes, ex.: sudo apt install python3 python3-venv"
    echo "Depois rode de novo: bash instalar.sh"
    exit 1
  fi

  if [ ! -x .venv/bin/python ]; then
    echo "Criando ambiente Python..."
    if ! "$PY" -m venv .venv; then
      rm -rf .venv
      echo "Não deu para criar o ambiente Python. No Ubuntu/Debian instale o módulo venv:  sudo apt install python3-venv"
      exit 1
    fi
  fi
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

  .venv/bin/python launcher.py setup
  .venv/bin/python launcher.py shortcut
  echo
  echo 'Pronto. Use o atalho "Contas de teste" (na Mesa/Área de Trabalho ou no menu de aplicativos).'
}
main "$@"
