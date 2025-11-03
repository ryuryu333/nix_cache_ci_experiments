# nix_cache_ci_experiments
Nix を GitHub ACtions で利用する際、キャッシュツールを利用するとビルドが高速化できます。

本ディレクトリでは、以下のツールを対象に、Job 時間を比較しました。

- [cachix-action](https://github.com/cachix/cachix-action)
- [cache-nix-action](https://github.com/nix-community/cache-nix-action)
- [magic-nix-cache-action](https://github.com/DeterminateSystems/magic-nix-cache-action)

詳細はブログにて解説しています。

Zeen: GitHub Actions における Nix バイナリキャッシュ 3 ツールの実測比較

[https://zenn.dev/trifolium/articles/1a2eeca4775e56](https://zenn.dev/trifolium/articles/1a2eeca4775e56)
