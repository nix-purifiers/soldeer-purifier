import assert from 'node:assert/strict';
import { ContractFactory, Interface, JsonRpcProvider, keccak256 } from 'ethers';

const [rpc, selected, resourceURL, expectedText] = process.argv.slice(2);
const expected = Number(expectedText);
const library = await import(selected);
let { abi, bytecode, deployedBytecode } = library;
if (resourceURL !== '-') {
  const native = await (await fetch(resourceURL + '/contract.json')).json();
  assert.deepEqual(native.abi, abi);
  assert.equal(native.bytecode.object, bytecode);
  assert.equal(native.deployedBytecode.object, deployedBytecode);
  const iface = new Interface(abi);
  for (const [signature, selector] of Object.entries(native.methodIdentifiers)) {
    assert.equal(iface.getFunction(signature).selector.slice(2), selector);
  }
  abi = native.abi; bytecode = native.bytecode.object;
}
assert.deepEqual(library.linkReferences, {});
const provider = new JsonRpcProvider(rpc);
try {
  const signer = await provider.getSigner(0);
  const factory = new ContractFactory(abi, bytecode, signer);
  const contract = await factory.deploy();
  await contract.waitForDeployment();
  const address = await contract.getAddress();
  assert.equal(await provider.getCode(address), deployedBytecode);
  assert.equal(Number(await contract.value()), expected);
  assert.equal(Number(await contract.distance(-17n)), 18);
  const receipt = await (await contract.increment()).wait();
  assert.equal(Number(await contract.value()), expected + 1);
  const events = receipt.logs.map(log => { try { return contract.interface.parseLog(log); } catch { return null; } })
    .filter(log => log?.name === 'Changed');
  assert.equal(events.length, 1);
  assert.equal(Number(events[0].args.value), expected + 1);
  assert.equal(events[0].args.sender.toLowerCase(), (await signer.getAddress()).toLowerCase());
  console.log(JSON.stringify({ initial: expected, after: expected + 1, distance: 18,
    eventValue: Number(events[0].args.value), address, bytecodeKeccak: keccak256(bytecode),
    source: library.sourceName, compiler: library.compilerVersion }));
} finally { provider.destroy(); }
