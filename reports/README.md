
```
$ date "+%Y-%m-%d %H:%M:%S"
2025-10-25 00:02:48

$ gh cache list -L 5

Showing 5 of 2202 caches in ryuryu333/nix_cache_ci_experiments

ID          KEY                                                                 SIZE       CREATED               ACCESSED            
1481812529  078jihrnm6mj5g7zb73a5056z4pvz19y59v748lzrkmisyhkgvvw.nar.zstd-IuX7  18.64 KiB  about 59 minutes ago  about 56 minutes ago
1481813635  1lblmv9cd62j802x530j0m4xsnxk2ibv3az3lnf3bm6wr66268aq.nar.zstd-WE5l  18.55 KiB  about 59 minutes ago  about 56 minutes ago
1481808893  1liszxj3pwrvmmhqzshnl9f1vlfx0wh0w9x6wy8rjjk2bfb3ci5w.nar.zstd-9TTl  11.89 KiB  about 59 minutes ago  about 56 minutes ago
1481806845  0dbizmvddd1fg5q534gad1qn9gj8laf1dxlwvr3nqn011f4ba8n2.nar.zstd-oroo  542 B      about 1 hour ago      about 56 minutes ago
1481813213  1zd34b8spq6nsvhdx6aspxajah47qwwls1lkq6ljl6frwgkd96df.nar.zstd-GnIH  8.80 KiB   about 59 minutes ago  about 56 minutes ago

$ gh api repos/ryuryu333/nix_cache_ci_experiments/actions/cache/usage
{
  "full_name": "ryuryu333/nix_cache_ci_experiments",
  "active_caches_size_in_bytes": 2307640705,
  "active_caches_count": 2202
}
```

cachix
65.2 MiB
