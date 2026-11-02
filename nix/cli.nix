# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  git,
  nix,
  foundry,
  solc,
  vscode-solidity-server,
  nix-prefetch-git,
  gh,
  cacert,
  nixpkgsSrc,
  purifierSrc,
}:
stdenvNoCC.mkDerivation {
  pname = "soldeer-purifier";
  version = "0.1.0";
  src = ../.;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib/soldeer-purifier"
    cp -r soldeer_purifier nix "$out/lib/soldeer-purifier/"
    install -m755 bin/soldeer-purifier "$out/bin/soldeer-purifier"
    substituteInPlace "$out/lib/soldeer-purifier/nix/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@runtime@' "$out"
    wrapProgram "$out/bin/soldeer-purifier" \
      --prefix PATH : ${
        lib.makeBinPath [
          python3
          git
          nix
          foundry
          solc
          vscode-solidity-server
          nix-prefetch-git
          gh
        ]
      } \
      --prefix PYTHONPATH : "$out/lib/soldeer-purifier" \
      --set SOLDEER_PURIFIER_FORGE ${foundry}/bin/forge \
      --set SOLDEER_PURIFIER_FORGE_VERSION ${foundry.version} \
      --set SOLDEER_PURIFIER_SOLC_VERSION ${solc.version} \
      --set SOLDEER_PURIFIER_SOLC ${solc}/bin/solc \
      --set SOLDEER_PURIFIER_REALIZE "$out/lib/soldeer-purifier/nix/realize.nix" \
      --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt
    makeWrapper "$out/bin/soldeer-purifier" "$out/bin/forge" --add-flags "native --"
  '';
  meta = {
    description = "Locked, Nix-resolved Solidity dependencies";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "soldeer-purifier";
    homepage = "https://nix-purifiers.github.io/";
  };
}
