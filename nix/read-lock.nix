# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/soldeer-purifier.lock.json",
  soldeerLock ? src + "/soldeer.lock",
}:
let
  fix = message: "soldeer-purifier: ${message}; run soldeer-purifier lock";
  exists = builtins.pathExists lockFile && builtins.pathExists soldeerLock;
  data =
    if exists then
      builtins.addErrorContext (fix "cannot parse companion") (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
  native =
    if exists then
      builtins.addErrorContext (fix "cannot parse native lock") (
        builtins.fromTOML (builtins.readFile soldeerLock)
      )
    else
      { };
  records = native.dependencies or [ ];
  metadata = data.dependencies or { };
  name = e: "${e.name}-${e.version}";
  safe =
    value:
    builtins.isString value
    && builtins.match "[A-Za-z0-9@_.+-]+" value != null
    && !(builtins.elem value [
      "."
      ".."
    ]);
  names = map name records;
  files = builtins.filter (p: builtins.pathExists (src + "/${p}")) [
    "foundry.toml"
    "soldeer.toml"
    "remappings.txt"
  ];
  inputs = builtins.listToAttrs (
    map (p: {
      name = p;
      value = builtins.hashFile "sha256" (src + "/${p}");
    }) files
  );
  configs = builtins.filter (p: p != "remappings.txt") files;
  config =
    if builtins.length configs == 1 then
      builtins.fromTOML (builtins.readFile (src + "/${builtins.head configs}"))
    else
      { };
  valid =
    e:
    builtins.isAttrs e
    && safe (e.name or null)
    && safe (e.version or null)
    && builtins.stringLength (name e) <= 240
    && builtins.isAttrs (metadata.${name e} or null)
    && (
      if e ? git then
        builtins.isString e.git
        && builtins.match "[0-9a-f]{40}" (e.rev or "") != null
        && builtins.match "sha256-[A-Za-z0-9+/]{43}=" (metadata.${name e}.hash or "") != null
        && builtins.isAttrs (metadata.${name e}.commitObject or null)
        && builtins.isString (metadata.${name e}.commitObject.object or null)
        && builtins.isList (metadata.${name e}.commitObject.gitlinks or null)
      else
        builtins.match "https?://[^/@ ]+/[^ ]*" (e.url or "") != null
        && builtins.all (k: builtins.match "[0-9a-f]{64}" (e.${k} or "") != null) [
          "checksum"
          "integrity"
        ]
        && builtins.isBool (metadata.${name e}.stripTop or null)
    );
  problems = map fix (
    if !exists then
      [ "missing native or companion lock" ]
    else if !builtins.isAttrs data || (data.version or null) != 1 || (native.version or null) != 2 then
      [ "unsupported lock format" ]
    else if
      (data.contentHash or null)
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ "contentHash mismatch" ]
    else if !builtins.isList records || !builtins.isAttrs metadata || !builtins.all valid records then
      [ "invalid or missing dependency metadata" ]
    else if
      builtins.length names != builtins.length (lib.unique names)
      || lib.sort builtins.lessThan names != builtins.attrNames metadata
    then
      [ "duplicate or missing dependency entries" ]
    else if builtins.length configs != 1 || (config.soldeer.recursive_deps or false) then
      [ "use one configuration file without recursive dependencies" ]
    else if
      builtins.attrNames (config.dependencies or { })
      != lib.sort builtins.lessThan (map (e: e.name) records)
    then
      [ "native lock differs from configuration" ]
    else if
      (data.inputs or null) != inputs
      || (data.nativeHash or null) != builtins.hashFile "sha256" soldeerLock
    then
      [ "configuration or native lock changed" ]
    else if
      !builtins.isString (data.forgeVersion or null) || !builtins.isString (data.solcVersion or null)
    then
      [ "missing toolchain versions" ]
    else
      [ ]
  );
in
{
  purifier = "soldeer-purifier";
  inherit problems;
  outputs.contracts = { };
  forgeVersion = data.forgeVersion or "";
  solcVersion = data.solcVersion or "";
  entries =
    if problems != [ ] then
      [ ]
    else
      map (
        e:
        {
          path = name e;
        }
        // (
          if e ? git then
            {
              git = {
                url = e.git;
                rev = e.rev;
                submodules = true;
                leaveDotGit = true;
                commitObject = metadata.${name e}.commitObject;
              };
              hash = metadata.${name e}.hash;
            }
          else
            {
              archive = {
                url = e.url;
                mirrors = [ ];
                stripTop = metadata.${name e}.stripTop;
              };
              hash = builtins.convertHash {
                hash = e.checksum;
                hashAlgo = "sha256";
                toHashFormat = "sri";
              };
            }
        )
      ) records;
}
