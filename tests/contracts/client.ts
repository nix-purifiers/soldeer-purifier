import { ContractFactory, Interface, type InterfaceAbi } from 'ethers';
import { abi, bytecode, deployedBytecode, contractName } from '@fixture/counter-abi';

const nativeABI: InterfaceAbi = abi;
const nativeFactory = new ContractFactory(nativeABI, bytecode);
const nativeInterface = new Interface(abi);
const identity: 'Counter' = contractName;
void [nativeFactory, nativeInterface, deployedBytecode, identity];
