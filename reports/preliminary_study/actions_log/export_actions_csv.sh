#!/usr/bin/env bash
set -euo pipefail

# GitHub Actions の実行結果（runs / jobs / steps）を CSV に出力します。
# 必要コマンド: curl, jq
# 認証: パブリックリポジトリなら不要。必要に応じて GH_TOKEN を環境変数に設定してください。
#
# 既定値は環境変数で上書き可能です:
#   OWNER, REPO, WORKFLOW, OUTDIR, PER_PAGE, GITHUB_API
# 例:
#   OWNER=ryuryu333 REPO=nix_cache_ci_experiments WORKFLOW=build.yml ./scripts/export_actions_csv.sh

OWNER="${OWNER:-ryuryu333}"
REPO="${REPO:-nix_cache_ci_experiments}"
WORKFLOW="${WORKFLOW:-build.yml}"
OUTDIR="${OUTDIR:-.}"
PER_PAGE="${PER_PAGE:-100}"
GITHUB_API="${GITHUB_API:-https://api.github.com}"

AUTH_HEADER=()
if [[ -n "${GH_TOKEN:-}" ]]; then
  AUTH_HEADER=(
    -H "Authorization: Bearer ${GH_TOKEN}"
    -H "X-GitHub-Api-Version: 2022-11-28"
  )
fi

api() {
  curl -sS "${AUTH_HEADER[@]}" "$@"
}

mkdir -p "${OUTDIR}"

echo "[1/3] Export runs -> ${OUTDIR}/actions_runs.csv" >&2
api "${GITHUB_API}/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=${PER_PAGE}" \
  | jq -r '
    def dur(a;b): ((a|fromdateiso8601) - (b|fromdateiso8601));
    ["run_id","run_number","branch","event","status","conclusion","run_started_at","updated_at","duration_s","html_url"],
    (.workflow_runs
      | sort_by(.run_number) | reverse
      | map({
          run_id: .id, run_number, branch: .head_branch, event, status, conclusion,
          run_started_at, updated_at,
          duration_s: dur(.updated_at; (.run_started_at // .created_at)),
          html_url
        })
      | .[]
      | [ .run_id, .run_number, .branch, .event, .status, (.conclusion // ""), .run_started_at, .updated_at, .duration_s, .html_url ]
    ) | @csv
  ' > "${OUTDIR}/actions_runs.csv"

# RUN IDs を同一ソースから取得
RUN_IDS=$(api "${GITHUB_API}/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=${PER_PAGE}" \
  | jq -r '.workflow_runs | sort_by(.run_number) | reverse | .[].id')

echo "[2/3] Export jobs -> ${OUTDIR}/actions_jobs.csv" >&2
{
  echo "run_id,job_id,job_name,status,conclusion,started,ended,duration_s,html_url";
  for id in ${RUN_IDS}; do
    api "${GITHUB_API}/repos/${OWNER}/${REPO}/actions/runs/${id}/jobs?per_page=100" \
      | jq -r --arg id "${id}" '
          def dur(a;b): if (a==null or b==null) then null else ((a|fromdateiso8601) - (b|fromdateiso8601)) end;
          .jobs[] | [ $id, .id, .name, .status, (.conclusion // ""), .started_at, .completed_at, dur(.completed_at; .started_at), .html_url ] | @csv'
  done
} > "${OUTDIR}/actions_jobs.csv"

echo "[3/3] Export steps -> ${OUTDIR}/actions_steps.csv" >&2
{
  echo "run_id,job_name,step_name,status,conclusion,started,ended,duration_s";
  for id in ${RUN_IDS}; do
    api "${GITHUB_API}/repos/${OWNER}/${REPO}/actions/runs/${id}/jobs?per_page=100" \
      | jq -r --arg id "${id}" '
          def dur(a;b): if (a==null or b==null) then null else ((a|fromdateiso8601) - (b|fromdateiso8601)) end;
          .jobs[] as $j | ($j.steps // [])[] | [ $id, $j.name, .name, .status, (.conclusion // ""), .started_at, .completed_at, dur(.completed_at; .started_at) ] | @csv'
  done
} > "${OUTDIR}/actions_steps.csv"

echo "Done. Files written to ${OUTDIR}/" >&2

