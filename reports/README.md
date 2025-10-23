**概要**
- 目的: Nix ビルドに対するキャッシュツールの短縮効果を比較・整理
- 対象ワークフロー: `.github/workflows/build.yml`
- 対象ジョブ: `zenn_build`（Node ベース）/ `marp_build`（nixpkgs ベース）
- 解析データ: `reports/actions_log/` の `actions_{runs|jobs|steps}.csv`
- 解析出力: `reports/my_result/` 配下（CSV と画像）

**計測方法**
- 主指標: ステップ名が `Run nix build` の所要時間（秒）
- 付随指標: ジョブ合計時間（`actions_jobs.csv` より）
- 比較軸: ベースライン(run 2)/初回(run 3,7,9)/2回目(run 4,8,10)
- 主要ファイル:
  - `reports/my_result/detail.csv`（run ごとの build 時間）
  - `reports/my_result/combined.csv`（build 時間とジョブ合計の結合）
  - 図: `reports/my_result/figures/*.png`

**ツールの仕様と挙動**
- cache-nix-action（GitHub Actions Cache 利用）
  - 仕組み: GHA Cache にビルド成果をアーカイブとして保存・復元。
  - 本リポジトリでの実態: キャッシュエントリ数=2（`zenn`/`marp` 各1ファイル）。合計サイズ ≈ 1.18GB。
  - 特徴: 復元/保存が各1回で済み、オーバーヘッドが小さい。キー設計（例: OS + job + `flake.lock` ハッシュ）で安定動作。
  - 注意点: リポジトリの GHA Cache 制限（容量上限、エントリ上限、TTL）。不要キャッシュの整理が必要。
  - 期待される効果: 同一リポジトリ/ブランチでの2回目以降で大きく短縮。

- magic-nix-cache（GitHub Actions Cache 利用、パス粒度）
  - 仕組み: Nix ストアパス単位で多数の小さなキャッシュを GHA Cache に保存。
  - 本リポジトリでの実態: エントリ数 ≈ 2,200、合計サイズ ≈ 1.13GB。
  - 挙動: `Post Run` で多数のアップロードが発生しやすく、ジョブ合計時間を押し上げる傾向。
  - 期待される効果: 条件が合えば部分的な再利用が効くが、GHA Cache の API/圧縮コストがネックになり得る。

- cachix（外部バイナリキャッシュ）
  - 仕組み: `cache.nixos.org` に無い成果物を専用キャッシュ（例: `ryuryu333.cachix.org`）へ push/pull。
  - 特徴: リポジトリや環境を跨いだ共有・再現性に強い。ネットワーク I/O 中心のオーバーヘッド。
  - 期待される効果: 独自ビルドが多いワークロード（例: Node 依存を含む `zenn`）で効きやすい。

**今回の観測（抜粋）**
- marp_build（ベースライン 24s）
  - cachix: 28s → 26s（改善小）
  - cache-nix-action: 22s → 10s（2回目で大幅短縮）
  - magic-nix-cache: 31s → 46s（悪化、Post Run 重い）
- zenn_build（ベースライン 53s）
  - cachix: 74s → 30s（約1.77x 短縮）
  - cache-nix-action: 99s → 8s（約6.63x 短縮）
  - magic-nix-cache: 68s → 53s（改善乏しい、Post Run 長時間化事例）

**解釈**
- `marp_build` は nixpkgs 由来が中心で、元から `cache.nixos.org` の置換が効いており、追加キャッシュのメリットは限定的。
- `zenn_build` は Node 依存等で独自ビルドが多く、cache-nix-action/cachix の効果が顕著。
- magic-nix-cache は多数エントリの保存・復元で GHA Cache のオーバーヘッドが大きく、今回の規模では不利。

**次の検証案**
- 反復回数の増加（各条件 3–5 回）。

**再現コマンド**
- 環境構築: `cd reports` `nix develop`
- 解析（CSV と図の生成）: `uv run main.py`

**ログ**
```
# cache-nix-action
(nix:nix-shell-env) ryu@main:~/dev/nix_cache_ci_experiments/marp$ gh cache list

Showing 2 of 2 caches in ryuryu333/nix_cache_ci_experiments

ID          KEY                                                                              SIZE        CREATED              ACCESSED              
1446301780  nix-zenn-Linux-803e8359ef0c01c7bfbcf0a6630e8a60cb4b005605a830bbdd5081a0c1b6aff8  478.22 MiB  about 1 minute ago   less than a minute ago
1446279298  nix-marp-Linux-803e8359ef0c01c7bfbcf0a6630e8a60cb4b005605a830bbdd5081a0c1b6aff8  645.31 MiB  about 2 minutes ago  less than a minute ago


(nix:nix-shell-env) ryu@main:~/dev/nix_cache_ci_experiments/marp$ gh api repos/ryuryu333/nix_cache_ci_experiments/actions/cache/usage
{
  "full_name": "ryuryu333/nix_cache_ci_experiments",
  "active_caches_size_in_bytes": 1178117209,
  "active_caches_count": 2
}

(nix:nix-shell-env) ryu@main:~/dev/nix_cache_ci_experiments/marp$ time gh cache delete --all
✓ Deleted 2 caches from ryuryu333/nix_cache_ci_experiments

real    0m1.870s
user    0m0.054s
sys     0m0.065s



# magic-nix-cache
(nix:nix-shell-env) ryu@main:~/dev/nix_cache_ci_experiments/marp$ gh cache list

Showing 30 of 2200 caches in ryuryu333/nix_cache_ci_experiments

ID          KEY                                                                 SIZE        CREATED               ACCESSED           
1446532216  078jihrnm6mj5g7zb73a5056z4pvz19y59v748lzrkmisyhkgvvw.nar.zstd-aN0m  18.64 KiB   about 46 minutes ago  about 4 minutes ago
1446533029  1lblmv9cd62j802x530j0m4xsnxk2ibv3az3lnf3bm6wr66268aq.nar.zstd-xwtV  18.55 KiB   about 46 minutes ago  about 4 minutes ago
...

(nix:nix-shell-env) ryu@main:~/dev/nix_cache_ci_experiments/marp$ gh api repos/ryuryu333/nix_cache_ci_experiments/actions/cache/usage
{
  "full_name": "ryuryu333/nix_cache_ci_experiments",
  "active_caches_size_in_bytes": 1129804528,
  "active_caches_count": 2200
}
```
