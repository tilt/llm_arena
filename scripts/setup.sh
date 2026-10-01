#!/bin/sh
# Set up LLM Arena on macOS or Linux (Windows: use WSL2).
#   sh scripts/setup.sh           check prerequisites, then install what the project needs
#   sh scripts/setup.sh --check   only check and report (make doctor)
# It never installs system software itself: for a missing tool it prints the command to install it.
set -u

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1
cd "$(dirname "$0")/.." || exit 1

OS=$(uname -s)
missing_required=0
if [ -t 1 ]; then OK="\033[32m✓\033[0m"; NO="\033[31m✗\033[0m"; OPT="\033[33m–\033[0m"; else OK="ok"; NO="MISSING"; OPT="-"; fi
say() { printf "  %b %-22s %s\n" "$1" "$2" "$3"; }
has() { command -v "$1" >/dev/null 2>&1; }
hint() {  # install hint per OS
  case "$OS" in
    Darwin) printf "%s" "$1" ;;
    *) printf "%s" "$2" ;;
  esac
}

case "$OS" in
  Darwin|Linux) ;;
  *) echo "Unsupported system $OS: use macOS, Linux, or WSL2 on Windows."; exit 1 ;;
esac

echo "LLM Arena setup on $OS"
echo
echo "Required"
if has git; then say "$OK" "git" "$(git --version | cut -d' ' -f3)"; else say "$NO" "git" "$(hint 'xcode-select --install' 'sudo apt install git  (or your package manager)')"; missing_required=1; fi
if has make; then say "$OK" "make" ""; else say "$NO" "make" "$(hint 'xcode-select --install' 'sudo apt install make')"; missing_required=1; fi
if has uv; then
  say "$OK" "uv" "$(uv --version | cut -d' ' -f2) (installs Python 3.12 for the project)"
else
  say "$NO" "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh   (then open a new shell)"
  missing_required=1
fi

echo
echo "Recommended"
node_ok=0
if has node; then
  major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  if [ "$major" -ge 20 ] 2>/dev/null; then node_ok=1; say "$OK" "Node.js" "$(node --version) (builds the web UI)"
  else say "$NO" "Node.js" "$(node --version) is too old: need 20 or newer for the web UI"; fi
else
  say "$OPT" "Node.js ≥ 20" "for the web UI: $(hint 'brew install node' 'https://nodejs.org or your package manager (nodejs 20+)')"
fi
docker_state="missing"
if has docker; then
  if docker info >/dev/null 2>&1; then
    if docker image inspect llm-arena-sandbox:latest >/dev/null 2>&1; then docker_state="ready"; say "$OK" "Docker sandbox" "running, image built: model-written code runs isolated"
    else docker_state="no-image"; say "$OPT" "Docker sandbox" "running, image not built yet (setup builds it)"; fi
    # Containers run as your user either way; this is about the daemon that starts them.
    if [ "$OS" = "Linux" ]; then
      if docker info --format '{{json .SecurityOptions}}' 2>/dev/null | grep -q rootless; then
        say "$OK" "Docker daemon" "rootless: no part of the sandbox runs as root"
      elif docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -q "Docker Desktop"; then
        say "$OK" "Docker daemon" "Docker Desktop: runs inside a VM"
      else
        say "$OPT" "Docker daemon" "runs as root (standard install). Rootless Docker avoids that: https://docs.docker.com/engine/security/rootless/"
      fi
    fi
  else
    docker_state="stopped"
    say "$NO" "Docker sandbox" "$(hint 'start Docker Desktop' 'start Docker (sudo systemctl start docker); without sudo, use rootless Docker (https://docs.docker.com/engine/security/rootless/) or join the docker group (sudo usermod -aG docker $USER), which is root-equivalent')"
  fi
else
  say "$OPT" "Docker" "isolates model-written code: $(hint 'https://www.docker.com/products/docker-desktop' 'https://docs.docker.com/engine/install/')"
fi

echo
echo "Optional (local models)"
probe() { curl -fsS -m 2 "$2" >/dev/null 2>&1 && say "$OK" "$1" "reachable at $2" || say "$OPT" "$1" "$3"; }
if has curl; then
  probe "Ollama" "http://localhost:11434/api/tags" "not running (https://ollama.com)"
  probe "LM Studio" "http://localhost:1234/v1/models" "not running (start its local server)"
  probe "Ollaya (winnow)" "http://localhost:11435/v1/models" "not running (decision models; optional)"
else
  say "$OPT" "curl" "not found: skipping local model checks"
fi
if [ -f .env ]; then say "$OK" ".env" "present (API keys are optional)"; else say "$OPT" ".env" "not yet created (setup copies .env.example)"; fi

if [ "$missing_required" -ne 0 ]; then
  echo
  echo "Install the required tools above, then run: make setup"
  exit 1
fi
[ "$CHECK_ONLY" -eq 1 ] && exit 0

echo
echo "Installing"
uv sync --all-extras --python 3.12 || exit 1
if [ ! -f .env ]; then cp .env.example .env && echo "  created .env from .env.example (add API keys there if you use remote models)"; fi
if [ "$node_ok" -eq 1 ]; then
  make web || exit 1
else
  echo "  skipped the web UI build (needs Node.js 20+); the CLI works without it"
fi
if [ "$docker_state" = "no-image" ]; then
  make sandbox-image || echo "  could not build the sandbox image; code scenarios stay unavailable unless you explicitly use --sandbox unsafe-process"
fi

echo
echo "Done. Next:"
echo "  make test        run the checks (no models needed)"
echo "  make ui          start the app on http://127.0.0.1:8787"
echo "  uv run arena models list   see which models were found"
