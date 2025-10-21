{
  description = "Zenn CLI environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        npmRoot = ./node-pkgs;
        nodejs = pkgs.nodejs_24;
        inherit (pkgs) importNpmLock;
        npmDeps = importNpmLock.buildNodeModules {
          inherit nodejs npmRoot;
        };
      in
      rec {
        packages = {
          zenn_tools = pkgs.buildEnv {
            name = "zenn_tools";
            paths = with pkgs; [
              treefmt
              lychee
              npmDeps
            ];
          };
          default = packages.zenn_tools;
        };

        devShells = {
          zenn = pkgs.mkShell {
            nativeBuildInputs = [
              packages.zenn_tools
              pkgs.go-task
              importNpmLock.hooks.linkNodeModulesHook
            ];
            inherit npmDeps;
          };
          node = pkgs.mkShell {
            packages = [
              nodejs
              pkgs.npm-check-updates
            ];
          };
          default = devShells.zenn;
        };
      }
    );
}
