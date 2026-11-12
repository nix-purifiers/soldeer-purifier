// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;
import {stdMath} from "forge-std-1.11.0/src/StdMath.sol";
import {OwnMath} from "../interfaces/OwnMath.sol";
contract Counter {
    uint256 public value = 42;
    event Changed(uint256 indexed value, address indexed sender);
    function increment() external { value++; emit Changed(value, msg.sender); }
    function distance(int256 input) external pure returns (uint256) { return OwnMath.plusOne(stdMath.abs(input)); }
}
