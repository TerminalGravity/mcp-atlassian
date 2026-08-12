#!/bin/bash
# Set or rotate the Jira credential used by the adr-jira MCP server and Hermes.
#
# The credential is duplicated across three .env files. Writing only one of them
# leaves the others on a dead token, which is how DS-era rotations silently
# broke Hermes while the MCP kept working (and vice versa). This script writes
# all of them, preserves unrelated keys, and refuses to save a credential that
# does not authenticate.
set -euo pipefail
umask 077

ENV_FILES=(
  "$HOME/.hermes/tools/mcp-atlassian/.env"
  "$HOME/.hermes/.env"
  "$HOME/.hermes/profiles/prompts/.env"
)

printf 'Jira site URL (for example https://company.atlassian.net): '
IFS= read -r jira_url
printf 'Jira username/email: '
IFS= read -r jira_username
printf 'Jira API token (input hidden): '
IFS= read -rs jira_token
printf '\n'

if [[ -z "$jira_url" || -z "$jira_username" || -z "$jira_token" ]]; then
  printf 'All three values are required. Nothing was written.\n' >&2
  exit 1
fi

jira_url="${jira_url%/}"

# Verify BEFORE writing. Catches an expired token and, just as importantly, a
# token minted under a different Atlassian account than the username above --
# that mismatch authenticates as the wrong identity or not at all.
printf 'Verifying against %s ... ' "$jira_url"
http_code=$(curl -s -o /tmp/.jira-verify.$$ -w '%{http_code}' \
  -u "$jira_username:$jira_token" \
  -H 'Accept: application/json' \
  "$jira_url/rest/api/3/myself" || true)

if [[ "$http_code" != "200" ]]; then
  printf 'FAILED (HTTP %s)\n' "$http_code" >&2
  printf 'Nothing was written. Check the site URL, the email, and that the token\n' >&2
  printf 'was created while signed in as that same account.\n' >&2
  rm -f /tmp/.jira-verify.$$
  exit 1
fi

account=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("emailAddress") or d.get("displayName") or d.get("accountId"))' /tmp/.jira-verify.$$ 2>/dev/null || echo 'unknown')
rm -f /tmp/.jira-verify.$$
printf 'OK -- authenticated as %s\n' "$account"

if [[ "$account" != "$jira_username" && "$account" != 'unknown' ]]; then
  printf '\nWARNING: token authenticates as "%s" but you entered "%s".\n' "$account" "$jira_username"
  printf 'Continue anyway? [y/N] '
  IFS= read -r confirm
  [[ "$confirm" == [yY]* ]] || { printf 'Aborted. Nothing was written.\n'; exit 1; }
fi

stamp=$(date +%Y%m%d-%H%M%S)
for env_file in "${ENV_FILES[@]}"; do
  [[ -e "$env_file" ]] || { printf 'skip (absent): %s\n' "$env_file"; continue; }
  cp -p "$env_file" "$env_file.bak.$stamp"

  # Rewrite only the three keys; every other line is preserved verbatim so
  # settings like JIRA_PROJECTS_FILTER survive a rotation.
  JIRA_URL="$jira_url" JIRA_USERNAME="$jira_username" JIRA_API_TOKEN="$jira_token" \
  python3 - "$env_file" <<'PY'
import os, re, sys, pathlib
path = pathlib.Path(sys.argv[1])
updates = {k: os.environ[k] for k in ("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN")}
seen = set()
out = []
for line in path.read_text().splitlines():
    m = re.match(r'^\s*(JIRA_URL|JIRA_USERNAME|JIRA_API_TOKEN)\s*=', line)
    if m:
        key = m.group(1)
        out.append(f'{key}={updates[key]}')
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
path.write_text('\n'.join(out) + '\n')
PY
  chmod 600 "$env_file"
  printf 'updated: %s (backup .bak.%s)\n' "$env_file" "$stamp"
done

unset jira_token
printf '\nDone. Reconnect the adr-jira MCP server (/mcp in Claude Code) and reload\n'
printf 'Hermes so both pick up the new value -- running processes cache the old one.\n'
