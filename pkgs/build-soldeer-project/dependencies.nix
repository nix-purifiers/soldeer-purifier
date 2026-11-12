# SPDX-License-Identifier: MIT
{
  runCommand,
  fetchurl,
  fetchgit,
  python3,
  unzip,
  zstd,
  purifier,
}:
{
  lock,
  fetchers ? { },
}:
purifier.tree (
  {
    name = "soldeer-dependencies";
    entries = (purifier.checkLock lock).entries;
    inherit
      runCommand
      fetchurl
      fetchgit
      python3
      unzip
      zstd
      ;
  }
  // fetchers
)
