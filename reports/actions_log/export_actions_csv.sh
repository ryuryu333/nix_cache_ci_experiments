#!/usr/bin/env bash
set -euo pipefail

# GitHub Actions の実行結果（runs / jobs / steps）を CSV に出力します。
# 現在の仕様: OUTDIR/selection.csv に列挙された run_id の実行のみを対象にします。
# 必要コマンド: curl, jq
# 認証: パブリックリポジトリなら不要。必要に応じて GH_TOKEN を環境変数に設定してください。
#
# 既定値（環境変数で上書き可）:
#   OWNER, REPO, OUTDIR, GITHUB_API, SELECTION
# 例:
#   OWNER=ryuryu333 REPO=nix_cache_ci_experiments OUTDIR=reports/actions_log \
#     GH_TOKEN=$GH_TOKEN bash reports/actions_log/export_actions_csv.sh

OWNER="${OWNER:-ryuryu333}"
REPO="${REPO:-nix_cache_ci_experiments}"
OUTDIR="${OUTDIR:-.}"
SELECTION="${SELECTION:-${OUTDIR}/selection.csv}"
GITHUB_API="${GITHUB_API:-https://api.github.com}"

AUTH_HEADER=(
  -H "Accept: application/vnd.github+json"
  -H "X-GitHub-Api-Version: 2022-11-28"
)
if [[ -n "${GH_TOKEN:-}" ]]; then
  AUTH_HEADER+=( -H "Authorization: Bearer ${GH_TOKEN}" )
fi

api() {
  curl -sS "${AUTH_HEADER[@]}" "$@"
}

mkdir -p "${OUTDIR}"

echo "[prep] Determine target run IDs (from selection.csv)" >&2
if [[ ! -s "${SELECTION}" ]]; then
  echo "ERROR: selection.csv is required and must not be empty: ${SELECTION}" >&2
  exit 2
fi
# Extract first column (run_id), skip header; strip quotes; drop empties and dedupe
RUN_IDS=$(tail -n +2 "${SELECTION}" | awk -F, '{gsub(/\r/,"",$1); gsub(/"/,"",$1); if($1!="") print $1}' | sort -u)
if [[ -z "${RUN_IDS}" ]]; then
  echo "ERROR: selection.csv contains no run_id rows." >&2
  exit 2
fi

echo "[1/3] Export runs -> ${OUTDIR}/actions_runs.csv" >&2
{
  echo '"run_id","run_number","branch","event","status","conclusion","run_started_at","updated_at","duration_s","html_url"';
  while read -r id; do
    [[ -z "$id" ]] && continue
    api "${GITHUB_API}/repos/${OWNER}/${REPO}/actions/runs/${id}" \
      | jq -r '
        def dur(a;b): ((a|fromdateiso8601) - (b|fromdateiso8601));
        . as $r | [
          ($r.id), ($r.run_number), ($r.head_branch), ($r.event), ($r.status), ($r.conclusion // ""),
          ($r.run_started_at // $r.created_at), ($r.updated_at), (dur($r.updated_at; ($r.run_started_at // $r.created_at))), ($r.html_url)
        ] | @csv'
  done <<< "${RUN_IDS}"
} > "${OUTDIR}/actions_runs.csv"

echo "[2/3] Export jobs -> ${OUTDIR}/actions_jobs.csv" >&2
echo "[3/3] Export steps -> ${OUTDIR}/actions_steps.csv" >&2
{
  echo "run_id,job_id,job_name,status,conclusion,started,ended,duration_s,html_url" > "${OUTDIR}/actions_jobs.csv";
  echo "run_id,job_name,step_name,status,conclusion,started,ended,duration_s" > "${OUTDIR}/actions_steps.csv";
  for id in ${RUN_IDS}; do
    tmp_json=$(mktemp)
    api "${GITHUB_API}/repos/${OWNER}/${REPO}/actions/runs/${id}/jobs?per_page=100" > "${tmp_json}"
    # jobs
    jq -r --arg id "${id}" '
      def dur(a;b): if (a==null or b==null) then null else ((a|fromdateiso8601) - (b|fromdateiso8601)) end;
      .jobs[] | [ $id, .id, .name, .status, (.conclusion // ""), .started_at, .completed_at, dur(.completed_at; .started_at), .html_url ] | @csv' "${tmp_json}" \
      >> "${OUTDIR}/actions_jobs.csv"
    # steps
    jq -r --arg id "${id}" '
      def dur(a;b): if (a==null or b==null) then null else ((a|fromdateiso8601) - (b|fromdateiso8601)) end;
      .jobs[] as $j | ($j.steps // [])[] | [ $id, $j.name, .name, .status, (.conclusion // ""), .started_at, .completed_at, dur(.completed_at; .started_at) ] | @csv' "${tmp_json}" \
      >> "${OUTDIR}/actions_steps.csv"
    rm -f "${tmp_json}"
  done
}

echo "Done. Files written to ${OUTDIR}/" >&2
