{
  description = "Marp environment";

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
      in
      rec {
        packages = {
          marp_build = pkgs.buildEnv {
            name = "marp_build_tools";
            paths = with pkgs; [
              marp-cli
              chromium
              noto-fonts-cjk-sans
            ];
          };
          default = packages.marp_build;
        };

        devShells = {
          default = pkgs.mkShell {
            nativeBuildInputs = with pkgs; [
              packages.marp_build
              gh
            ];
          };
        };

        apps = {
          marp = {
            type = "app";
            program = "${pkgs.marp-cli}/bin/marp";
          };
          default = apps.marp;
        };
      }
  );
}
